import os
import re
import hashlib
import mimetypes
from typing import List, Dict, Any, Optional
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
import requests
import urllib.parse
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, Response

class LibraryManager:
    """Escanea, cataloga y sirve pistas de audio locales con metadatos y streaming con soporte de Byte-Range."""

    AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".webm", ".opus"}

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        self.covers_dir = os.path.join(self.cache_dir, "covers")
        os.makedirs(self.covers_dir, exist_ok=True)
        self._tracks_cache: Dict[str, Dict[str, Any]] = {}

    def set_base_dir(self, new_dir: str):
        self.base_dir = os.path.abspath(new_dir)
        self._tracks_cache.clear()

    @staticmethod
    def get_track_id(filepath: str) -> str:
        """Genera un ID consistente y seguro a partir de la ruta del archivo."""
        norm = os.path.normpath(filepath).lower()
        return hashlib.md5(norm.encode("utf-8")).hexdigest()

    def scan_library(self) -> Dict[str, Any]:
        """Escanea recursivamente el directorio base y devuelve pistas, carpetas/playlists y estadísticas."""
        tracks = []
        playlists_map: Dict[str, List[Dict[str, Any]]] = {}
        artists_set = set()

        if not os.path.exists(self.base_dir):
            return {"tracks": [], "playlists": [], "total": 0, "artists_count": 0}

        for root, dirs, files in os.walk(self.base_dir):
            rel_folder = os.path.relpath(root, self.base_dir)
            playlist_name = "Biblioteca General" if rel_folder == "." else rel_folder.replace("\\", " / ")

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.AUDIO_EXTENSIONS:
                    full_path = os.path.join(root, file)
                    track_info = self._extract_metadata(full_path, playlist_name)
                    tracks.append(track_info)
                    self._tracks_cache[track_info["id"]] = track_info

                    if playlist_name not in playlists_map:
                        playlists_map[playlist_name] = []
                    playlists_map[playlist_name].append(track_info)
                    if track_info.get("artist") and track_info["artist"] != "Desconocido":
                        artists_set.add(track_info["artist"])

        # Ordenar canciones por fecha de modificación (más recientes primero)
        tracks.sort(key=lambda t: t.get("mtime", 0), reverse=True)

        playlists_list = []
        for name, items in playlists_map.items():
            first_cover = next((i["cover_url"] for i in items if i.get("cover_url")), "")
            playlists_list.append({
                "name": name,
                "count": len(items),
                "cover": first_cover,
                "tracks": [t["id"] for t in items]
            })

        return {
            "tracks": tracks,
            "playlists": playlists_list,
            "total": len(tracks),
            "artists_count": len(artists_set),
            "library_path": self.base_dir
        }

    def _extract_metadata(self, full_path: str, playlist_name: str) -> Dict[str, Any]:
        track_id = self.get_track_id(full_path)
        stat = os.stat(full_path)
        filename = os.path.basename(full_path)
        name_no_ext = os.path.splitext(filename)[0]
        ext = os.path.splitext(filename)[1].lower()

        # Valores por defecto basados en nombre de archivo (ej. "Artista - Título")
        artist = "Desconocido"
        title = name_no_ext
        if " - " in name_no_ext:
            parts = name_no_ext.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()

        album = playlist_name
        duration_seconds = 0
        has_embedded_cover = False

        try:
            audio = MutagenFile(full_path)
            if audio is not None:
                if audio.info and hasattr(audio.info, "length"):
                    duration_seconds = int(audio.info.length)

                # MP3 Tags
                if isinstance(audio, MP3):
                    if audio.tags:
                        if "TIT2" in audio.tags:
                            title = str(audio.tags["TIT2"])
                        if "TPE1" in audio.tags:
                            artist = str(audio.tags["TPE1"])
                        if "TALB" in audio.tags:
                            album = str(audio.tags["TALB"])
                        for k in audio.tags.keys():
                            if k.startswith("APIC"):
                                has_embedded_cover = True
                                break
                # MP4 / M4A Tags
                elif isinstance(audio, MP4):
                    if audio.tags:
                        if "\xa9nam" in audio.tags:
                            title = str(audio.tags["\xa9nam"][0])
                        if "\xa9ART" in audio.tags:
                            artist = str(audio.tags["\xa9ART"][0])
                        if "\xa9alb" in audio.tags:
                            album = str(audio.tags["\xa9alb"][0])
                        if "covr" in audio.tags and len(audio.tags["covr"]) > 0:
                            has_embedded_cover = True
        except Exception:
            pass

        # Generar URL de carátula permanente para cada pista
        cover_url = f"/api/cover/{track_id}"

        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}:{seconds:02d}" if duration_seconds > 0 else "--:--"

        return {
            "id": track_id,
            "title": title,
            "artist": artist,
            "album": album,
            "playlist": playlist_name,
            "filename": filename,
            "filepath": full_path,
            "format": ext.replace(".", ""),
            "duration": duration_str,
            "duration_seconds": duration_seconds,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "mtime": stat.st_mtime,
            "cover_url": cover_url,
            "stream_url": f"/api/stream/{track_id}"
        }

    def get_track_by_id(self, track_id: str) -> Optional[Dict[str, Any]]:
        if track_id in self._tracks_cache:
            return self._tracks_cache[track_id]
        self.scan_library()
        return self._tracks_cache.get(track_id)

    def extract_cover_bytes(self, track_id: str) -> Optional[tuple[bytes, str]]:
        """Extrae la carátula embebida en la pista o una imagen adjunta."""
        track = self.get_track_by_id(track_id)
        if not track:
            return None

        filepath = track["filepath"]
        cache_file = os.path.join(self.covers_dir, f"{track_id}.jpg")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "rb") as f:
                    return f.read(), "image/jpeg"
            except Exception:
                pass

        try:
            audio = MutagenFile(filepath)
            if isinstance(audio, MP3) and audio.tags:
                for k in audio.tags.keys():
                    if k.startswith("APIC"):
                        apic = audio.tags[k]
                        mime = apic.mime or "image/jpeg"
                        data = apic.data
                        with open(cache_file, "wb") as f:
                            f.write(data)
                        return data, mime
            elif isinstance(audio, MP4) and audio.tags and "covr" in audio.tags:
                covers = audio.tags["covr"]
                if covers:
                    data = bytes(covers[0])
                    with open(cache_file, "wb") as f:
                        f.write(data)
                    return data, "image/jpeg"
        except Exception:
            pass

        # Buscar imagen en misma carpeta
        dir_path = os.path.dirname(filepath)
        name_no_ext = os.path.splitext(track["filename"])[0]
        for img_name in [f"{name_no_ext}.jpg", f"{name_no_ext}.png", "cover.jpg", "folder.jpg"]:
            cand = os.path.join(dir_path, img_name)
            if os.path.exists(cand):
                mime = "image/png" if cand.endswith(".png") else "image/jpeg"
                with open(cand, "rb") as f:
                    return f.read(), mime

        # Buscar carátula oficial en línea (iTunes Search API en HD 600x600)
        official_cover = self.fetch_official_cover(track["title"], track["artist"], track_id, filename=track.get("filename"))
        if official_cover:
            return official_cover

        return None

    def fetch_official_cover(self, title: str, artist: str, track_id: str, filename: Optional[str] = None) -> Optional[tuple[bytes, str]]:
        """Busca y descarga la carátula oficial en HD (iTunes 600x600 o Deezer 500x500) priorizando estrictamente Artista + Canción."""
        cache_file = os.path.join(self.covers_dir, f"{track_id}.jpg")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "rb") as f:
                    data = f.read()
                    if len(data) > 1000:
                        return data, "image/jpeg"
            except Exception:
                pass

        try:
            # Limpieza de títulos y caracteres de codificación corruptos
            clean_t = re.sub(r"[\ufffd\x00-\x1f]", "", title or "")
            clean_a = re.sub(r"[\ufffd\x00-\x1f]", "", artist or "")
            clean_t = re.sub(r"\(.*?\)|\[.*?\]", "", clean_t).strip()
            clean_a = re.sub(r"\(.*?\)|\[.*?\]", "", clean_a).strip()
            clean_t = re.sub(r"(?i)\b(video oficial|official video|official audio|audio oficial|video|lyrics|letra|remix)\b", "", clean_t).strip()

            # Si el artista no viene o es 'Desconocido', intentar extraerlo del nombre de archivo (ej. 'Artista - Cancion.ext')
            if not clean_a or clean_a.lower() in ["desconocido", "unknown", "búsqueda", "sound studio", "arachiz"]:
                clean_a = ""
                if filename and " - " in filename:
                    base_fn = os.path.splitext(filename)[0]
                    parts = base_fn.split(" - ", 1)
                    cand_artist = parts[0].strip()
                    cand_title = parts[1].strip()
                    if cand_artist and cand_artist.lower() not in ["desconocido", "unknown"]:
                        clean_a = cand_artist
                        if not clean_t or clean_t == base_fn:
                            clean_t = cand_title

            first_artist = clean_a.split(",")[0].split("feat.")[0].split("ft.")[0].strip() if clean_a else ""

            queries_to_try = []
            # REGLA ESTRICTA: La búsqueda SIEMPRE debe incluir el Artista para no traer canciones homónimas de otros cantantes
            if clean_a and clean_t:
                queries_to_try.append(f"{clean_a} {clean_t}")
            if first_artist and first_artist != clean_a and clean_t:
                queries_to_try.append(f"{first_artist} {clean_t}")
            if clean_a:
                queries_to_try.append(f"{clean_a} {clean_t}".strip())
            # Solo como último recurso desesperado si no hay ningún artista identificable
            if not clean_a and clean_t:
                queries_to_try.append(clean_t)

            downloaded_bytes = None

            # 1. Intentar con Apple iTunes Search API (HD 600x600)
            for q in queries_to_try[:2]:
                try:
                    res = requests.get(
                        "https://itunes.apple.com/search",
                        params={"term": q, "entity": "song", "limit": 2},
                        timeout=3.5,
                    )
                    if res.status_code == 200:
                        results = res.json().get("results", [])
                        if results:
                            art_url = results[0].get("artworkUrl100", "")
                            if art_url:
                                hd_url = art_url.replace("100x100bb.jpg", "600x600bb.jpg")
                                img_res = requests.get(hd_url, timeout=4)
                                if img_res.status_code == 200 and len(img_res.content) > 1000:
                                    downloaded_bytes = img_res.content
                                    break
                except Exception:
                    pass

            # 2. Si iTunes no lo encontró, intentar con Deezer API (Cover Big 500x500)
            if not downloaded_bytes:
                for q in queries_to_try[:2]:
                    try:
                        dz_res = requests.get(
                            "https://api.deezer.com/search",
                            params={"q": q, "limit": 2},
                            timeout=3.5,
                        )
                        if dz_res.status_code == 200:
                            dz_data = dz_res.json().get("data", [])
                            if dz_data:
                                dz_url = dz_data[0].get("album", {}).get("cover_big") or dz_data[0].get("album", {}).get("cover_medium")
                                if dz_url:
                                    img_res = requests.get(dz_url, timeout=4)
                                    if img_res.status_code == 200 and len(img_res.content) > 1000:
                                        downloaded_bytes = img_res.content
                                        break
                    except Exception:
                        pass

            # 3. Fallback infalible: Extraer carátula HD original de YouTube Music / YouTube
            if not downloaded_bytes and clean_t:
                try:
                    search_q = f"{clean_a} {clean_t}".strip()
                    ydl_opts = {"quiet": True, "extract_flat": True, "no_warnings": True}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(f"ytsearch1:{search_q}", download=False)
                        entries = info.get("entries", []) if info else []
                        if entries and entries[0]:
                            thumbs = entries[0].get("thumbnails", [])
                            if thumbs:
                                thumb_url = thumbs[-1].get("url")
                                if thumb_url:
                                    img_res = requests.get(thumb_url, timeout=5)
                                    if img_res.status_code == 200 and len(img_res.content) > 1000:
                                        downloaded_bytes = img_res.content
                except Exception:
                    pass

            if downloaded_bytes:
                with open(cache_file, "wb") as f:
                    f.write(downloaded_bytes)

                # Incrustar en MP3 si existe para hacerlo permanente en el archivo físico
                track = self.get_track_by_id(track_id)
                if track and track.get("filepath") and track["filepath"].lower().endswith(".mp3"):
                    try:
                        audio = MP3(track["filepath"], ID3=ID3)
                        try:
                            audio.add_tags()
                        except Exception:
                            pass
                        audio.tags.delall("APIC")
                        audio.tags.add(
                            APIC(
                                encoding=3,
                                mime="image/jpeg",
                                type=3,
                                desc="Cover",
                                data=downloaded_bytes
                            )
                        )
                        audio.save()
                    except Exception:
                        pass

                return downloaded_bytes, "image/jpeg"

        except Exception:
            pass

        return None


    def stream_file(self, track_id: str, range_header: Optional[str] = None):
        """Sirve el archivo de audio con soporte de Byte-Range (HTTP 206 Partial Content)."""
        track = self.get_track_by_id(track_id)
        if not track or not os.path.exists(track["filepath"]):
            raise HTTPException(status_code=404, detail="Pista no encontrada en disco")

        filepath = track["filepath"]
        file_size = os.path.getsize(filepath)
        mime_type, _ = mimetypes.guess_type(filepath)
        if not mime_type:
            mime_type = "audio/mpeg" if filepath.endswith(".mp3") else "audio/mp4"

        if range_header:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                if start >= file_size:
                    raise HTTPException(status_code=416, detail="Rango solicitado fuera de límites")
                end = min(end, file_size - 1)
                content_length = end - start + 1

                def iterfile():
                    with open(filepath, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        chunk_size = 64 * 1024
                        while remaining > 0:
                            read_bytes = min(chunk_size, remaining)
                            chunk = f.read(read_bytes)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                headers = {
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                    "Content-Type": mime_type,
                }
                return StreamingResponse(iterfile(), status_code=206, headers=headers)

        def iterfile_all():
            with open(filepath, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
        }
        return StreamingResponse(iterfile_all(), status_code=200, headers=headers)

    def delete_track(self, track_id: str) -> bool:
        """Elimina un archivo de música del almacenamiento y de la caché."""
        track = self.get_track_by_id(track_id)
        if not track:
            return False

        filepath = track.get("filepath")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"[Library] Error al eliminar archivo de audio {filepath}: {e}")
                return False

            # Limpiar posibles archivos secundarios (.lrc, .jpg)
            base_no_ext = os.path.splitext(filepath)[0]
            for ext in [".lrc", ".jpg", ".png", ".webp"]:
                extra_f = f"{base_no_ext}{ext}"
                if os.path.exists(extra_f):
                    try:
                        os.remove(extra_f)
                    except Exception:
                        pass

        # Limpiar carátula de caché si existe
        cache_cover = os.path.join(self.covers_dir, f"{track_id}.jpg")
        if os.path.exists(cache_cover):
            try:
                os.remove(cache_cover)
            except Exception:
                pass

        if track_id in self._tracks_cache:
            del self._tracks_cache[track_id]

        return True

    def check_track_exists(self, title: str, artist: str = "") -> Dict[str, Any]:
        """Comprueba si una canción ya existe descargada en la biblioteca con coincidencia flexible."""
        self.scan_library()

        def normalize(s: str) -> str:
            if not s:
                return ""
            s = s.lower().strip()
            # Remover palabras secundarias como video oficial, audio, remix, ft, etc.
            s = re.sub(r"(?i)\b(official music video|official video|video oficial|official audio|audio oficial|video|letra|lyrics)\b", "", s)
            s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
            return re.sub(r"[^\w\s]", "", s).strip()

        norm_title = normalize(title)
        norm_artist = normalize(artist)

        for track in self._tracks_cache.values():
            t_title = normalize(track.get("title", ""))
            t_artist = normalize(track.get("artist", ""))

            # Coincidencia exacta o muy alta
            if norm_artist and t_artist:
                if (norm_title == t_title or norm_title in t_title or t_title in norm_title) and (norm_artist in t_artist or t_artist in norm_artist):
                    return {"exists": True, "track": track}
            else:
                if norm_title and norm_title == t_title:
                    return {"exists": True, "track": track}

        return {"exists": False, "track": None}

    def find_duplicates(self) -> List[Dict[str, Any]]:
        """Identifica todas las canciones duplicadas en la biblioteca."""
        self.scan_library()
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for track in self._tracks_cache.values():
            def clean_key(s: str) -> str:
                s = s.lower().strip()
                s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
                return re.sub(r"[^\w\s]", "", s).strip()

            t_key = clean_key(track.get("title", ""))
            a_key = clean_key(track.get("artist", ""))
            if not t_key:
                continue

            dedupe_key = f"{a_key}:::{t_key}" if a_key and a_key != "desconocido" else t_key
            if dedupe_key not in groups:
                groups[dedupe_key] = []
            groups[dedupe_key].append(track)

        duplicates_list = []
        for key, tracks in groups.items():
            if len(tracks) > 1:
                # Ordenar por tamaño y calidad (la mejor primero)
                tracks.sort(key=lambda t: (t.get("size_bytes", 0), t.get("mtime", 0)), reverse=True)
                duplicates_list.append({
                    "key": key,
                    "count": len(tracks),
                    "best_track": tracks[0],
                    "redundant_tracks": tracks[1:]
                })

        return duplicates_list

    def clean_duplicates(self) -> Dict[str, Any]:
        """Elimina automáticamente los archivos duplicados redundantes, conservando siempre la mejor copia."""
        dups = self.find_duplicates()
        deleted_count = 0
        freed_bytes = 0

        for item in dups:
            for red in item["redundant_tracks"]:
                freed_bytes += red.get("size_bytes", 0)
                if self.delete_track(red["id"]):
                    deleted_count += 1

        self.scan_library()
        return {
            "deleted_count": deleted_count,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "remaining_duplicates": len(self.find_duplicates())
        }
