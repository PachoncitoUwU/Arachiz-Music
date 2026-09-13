import os
import sys
import re
import time
import asyncio
import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
import requests
from typing import Callable, Optional, Dict, Any

# Asegurar ffmpeg disponible (usando static_ffmpeg si está instalado)
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception as e:
    print("Static ffmpeg warning:", e)


class PelotaDownloader:
    """Motor de descarga optimizada en MP3 (192-320k) o MP4 HD."""

    def __init__(self, output_base_dir: str = None):
        if output_base_dir:
            self.output_base_dir = output_base_dir
        else:
            user_downloads = os.path.join(os.path.expanduser("~"), "Downloads", "PelotaMp")
            self.output_base_dir = user_downloads
        os.makedirs(self.output_base_dir, exist_ok=True)

    def clean_filename(self, text: str) -> str:
        """Limpia caracteres inválidos para nombres de archivo en Windows."""
        return re.sub(r'[\\/*?:"<>|]', "", text).strip()

    def download_track(
        self,
        track_info: Dict[str, Any],
        playlist_name: str = "General",
        format_type: str = "mp3",
        quality_mode: str = "balanced",
        genre_tag: str = "",
        video_mode: str = "official",
        progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Descarga una pista individual y la guarda en la carpeta correspondiente.
        Soporta MP3 (128k, 192k, 320k) y Video Oficial YouTube HD (1080p) o Estándar.
        """
        clean_playlist = self.clean_filename(playlist_name) or "General"
        target_dir = os.path.join(self.output_base_dir, clean_playlist)
        os.makedirs(target_dir, exist_ok=True)

        title = track_info.get("title", "Unknown")
        artist = track_info.get("artist", "Unknown")
        direct_url = track_info.get("direct_url")
        query = track_info.get("query", f"{artist} - {title}")
        cover_url = track_info.get("cover", "")

        clean_artist = self.clean_filename(artist)
        clean_title = self.clean_filename(title)

        if clean_artist and clean_artist.lower() != "unknown" and clean_artist not in clean_title:
            filename_base = f"{clean_artist} - {clean_title}"
        else:
            filename_base = clean_title

        output_template = os.path.join(target_dir, f"{filename_base}.%(ext)s")

        fmt = format_type.lower().strip()
        is_video = fmt in ["mp4", "video", "video_official", "mp4_official", "video_standard", "mp4_standard"]

        # Determinar URL de búsqueda inteligente
        if direct_url and ("youtube.com" in direct_url or "youtu.be" in direct_url):
            search_target = direct_url
        else:
            search_query = query if query else f"{artist} - {title}"
            # Si el usuario eligió video oficial, buscar específicamente el videoclip oficial
            if is_video:
                if video_mode == "official" or fmt in ["video_official", "mp4_official"]:
                    search_target = f"ytsearch1:{search_query} official music video"
                else:
                    search_target = f"ytsearch1:{search_query} video clip"
            else:
                search_target = f"ytsearch1:{search_query} audio"

        def _yt_hook(d):
            if not progress_hook:
                return
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = int((downloaded / total) * 100) if total else 0
                speed = d.get("_speed_str", "")
                eta = d.get("_eta_str", "")
                progress_hook({
                    "status": "downloading",
                    "percent": pct,
                    "speed": speed,
                    "eta": eta,
                    "track": title,
                })
            elif status == "finished":
                progress_hook({
                    "status": "converting",
                    "percent": 95,
                    "track": title,
                })

        ydl_opts = {
            "outtmpl": output_template,
            "progress_hooks": [_yt_hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            # Evitar vídeos muy largos (> 18 min) que claramente no son la canción o videoclip
            "match_filter": yt_dlp.utils.match_filter_func("!is_live & duration < 1080"),
        }

        if fmt == "mp3":
            if quality_mode in ["eco", "save_space"]:
                audio_quality = "128"  # Ultra Ahorro: ~2.8 MB/canción
            elif quality_mode == "balanced":
                audio_quality = "192"  # Balanceado: ~4.5 MB/canción
            else:
                audio_quality = "320"  # Estudio: ~9.0 MB/canción

            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": audio_quality,
                }],
            })
        elif fmt in ["m4a", "aac"]:
            ydl_opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "128",
                }],
            })
        else:
            # Formatos de Video (MP4 Oficial / Estándar en Alta Definición 1080p o 4K)
            if quality_mode in ["max", "2160p", "4k", "uhd"]:
                video_selector = "bestvideo+bestaudio/best"
            elif quality_mode in ["720p", "hd"]:
                video_selector = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            else:
                # 1080p Full HD por defecto
                video_selector = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"

            ydl_opts.update({
                "format": video_selector,
                "merge_output_format": "mp4",
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(search_target, download=True)

            # Buscar el archivo descargado (el nombre exacto puede variar levemente)
            if is_video:
                ext = "mp4"
            elif fmt in ["m4a", "aac"]:
                ext = "m4a"
            else:
                ext = "mp3"
            downloaded_file = os.path.join(target_dir, f"{filename_base}.{ext}")

            # Si no se encuentra con el nombre exacto, buscar el más reciente
            if not os.path.exists(downloaded_file):
                candidates = [
                    f for f in os.listdir(target_dir)
                    if f.lower().endswith(f".{ext}")
                ]
                if candidates:
                    # Tomar el más recientemente modificado
                    candidates.sort(
                        key=lambda f: os.path.getmtime(os.path.join(target_dir, f)),
                        reverse=True,
                    )
                    downloaded_file = os.path.join(target_dir, candidates[0])

            # Aplicar Tags ID3 para MP3
            if format_type.lower() == "mp3" and os.path.exists(downloaded_file):
                self._apply_mp3_tags(
                    file_path=downloaded_file,
                    title=title,
                    artist=artist,
                    album=clean_playlist,
                    genre=genre_tag,
                    cover_url=cover_url,
                    track_info=track_info,
                )

            if progress_hook:
                progress_hook({
                    "status": "completed",
                    "percent": 100,
                    "track": title,
                    "filePath": downloaded_file,
                })

            return {
                "success": True,
                "title": title,
                "artist": artist,
                "file": downloaded_file,
                "folder": target_dir,
            }

        except Exception as e:
            err_msg = str(e)
            # Simplificar mensajes de error comunes
            if "No video formats found" in err_msg or "No such format" in err_msg:
                err_msg = "No se encontró el audio en YouTube. Intenta de nuevo."
            elif "Unsupported URL" in err_msg:
                err_msg = "URL no soportada. Usa links de YouTube o Spotify."

            if progress_hook:
                progress_hook({
                    "status": "error",
                    "error": err_msg,
                    "track": title,
                })
            return {
                "success": False,
                "title": title,
                "error": err_msg,
            }

    def _fetch_song_individual_cover(self, artist: str, title: str, fallback_url: str = "") -> Optional[bytes]:
        """
        Obtiene la portada ORIGINAL e INDIVIDUAL de la canción (álbum/single).
        NUNCA usa la foto de la playlist.
        Usa:
        1. iTunes Search API (oficial, HD 600x600, libre y ultrarrápido)
        2. Fallback URL (siempre que sea carátula del tema)
        """
        try:
            # 1. Intentar iTunes Search API para carátula oficial en HD (600x600)
            clean_title = re.sub(r"\(feat\..*?\)|\[.*?\]|\(con .*?\)", "", title, flags=re.IGNORECASE).strip()
            clean_artist = re.sub(r",.*", "", artist).strip()
            term = f"{clean_artist} {clean_title}".strip()
            if term:
                r = requests.get(
                    "https://itunes.apple.com/search",
                    params={"term": term, "entity": "song", "limit": 1},
                    headers={"User-Agent": "PelotaMp/2.0"},
                    timeout=5,
                )
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    if results and results[0].get("artworkUrl100"):
                        # Reemplazar 100x100 por 600x600 para máxima definición
                        hd_url = results[0]["artworkUrl100"].replace("100x100bb.jpg", "600x600bb.jpg")
                        img_res = requests.get(hd_url, timeout=6)
                        if img_res.status_code == 200 and len(img_res.content) > 1000:
                            return img_res.content
        except Exception as e:
            print(f"[Cover Fetch] iTunes search error: {e}")

        # 2. Intentar Deezer API (HD 500x500 libre)
        try:
            term = f"{clean_artist} {clean_title}".strip()
            if term:
                dz_res = requests.get(
                    "https://api.deezer.com/search",
                    params={"q": term, "limit": 1},
                    timeout=5,
                )
                if dz_res.status_code == 200:
                    dz_data = dz_res.json().get("data", [])
                    if dz_data and dz_data[0].get("album", {}).get("cover_big"):
                        dz_url = dz_data[0]["album"]["cover_big"]
                        img_res = requests.get(dz_url, timeout=6)
                        if img_res.status_code == 200 and len(img_res.content) > 1000:
                            return img_res.content
        except Exception as e:
            print(f"[Cover Fetch] Deezer error: {e}")

        # 3. Si no se encontró en iTunes ni Deezer, usar fallback_url si es válida
        if fallback_url and not fallback_url.endswith("playlist_default.jpg"):
            try:
                img_res = requests.get(fallback_url, timeout=6)
                if img_res.status_code == 200 and len(img_res.content) > 1000:
                    return img_res.content
            except Exception as e:
                print(f"[Cover Fetch] Fallback cover error: {e}")

        return None

    def _apply_mp3_tags(
        self,
        file_path: str,
        title: str,
        artist: str,
        album: str,
        genre: str,
        cover_url: str,
        track_info: Optional[Dict[str, Any]] = None,
    ):
        """Incrusta tags ID3 limpios y la portada INDIVIDUAL del álbum directamente en el MP3."""
        try:
            audio = MP3(file_path, ID3=EasyID3)
            try:
                audio.add_tags()
            except Exception:
                pass

            audio["title"] = title
            audio["artist"] = artist
            if album and album.lower() not in ("general", ""):
                audio["album"] = album
            if genre:
                audio["genre"] = genre
            audio.save()

            # Evitar usar la foto de la playlist
            is_playlist_cover = False
            if track_info:
                is_playlist_cover = bool(track_info.get("is_playlist_cover", False))

            valid_fallback = "" if is_playlist_cover else cover_url

            # Obtener carátula individual de la canción
            img_data = self._fetch_song_individual_cover(artist, title, valid_fallback)

            if img_data:
                try:
                    id3 = ID3(file_path)
                    id3.delall("APIC")  # Eliminar carátulas previas
                    id3.add(
                        APIC(
                            encoding=3,       # UTF-8
                            mime="image/jpeg",
                            type=3,           # Cover (front)
                            desc="Cover",
                            data=img_data,
                        )
                    )
                    id3.save(v2_version=3)
                except Exception as img_err:
                    print("Error embedding cover art:", img_err)
        except Exception as e:
            print(f"Error tagging MP3 {file_path}: {e}")

