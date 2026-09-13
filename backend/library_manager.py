import os
import re
import hashlib
import mimetypes
from typing import List, Dict, Any, Optional
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
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

        # Generar URL de carátula
        cover_url = f"/api/cover/{track_id}" if has_embedded_cover else ""
        if not cover_url:
            # Buscar imagen hermana en la carpeta (cover.jpg, folder.jpg o mismo nombre)
            dir_path = os.path.dirname(full_path)
            for img_name in [f"{name_no_ext}.jpg", f"{name_no_ext}.png", "cover.jpg", "folder.jpg"]:
                img_path = os.path.join(dir_path, img_name)
                if os.path.exists(img_path):
                    cover_url = f"/api/cover/{track_id}?file=1"
                    break

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
        official_cover = self.fetch_official_cover(track["title"], track["artist"], track_id)
        if official_cover:
            return official_cover

        return None

    def fetch_official_cover(self, title: str, artist: str, track_id: str) -> Optional[tuple[bytes, str]]:
        """Busca y descarga la carátula oficial en HD 600x600 desde iTunes API si no hay una local."""
        cache_file = os.path.join(self.covers_dir, f"{track_id}.jpg")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "rb") as f:
                    return f.read(), "image/jpeg"
            except Exception:
                pass

        try:
            clean_t = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
            clean_a = re.sub(r"\(.*?\)|\[.*?\]", "", artist).strip()
            if clean_a.lower() in ["desconocido", "unknown", "búsqueda"]:
                clean_a = ""

            query = f"{clean_a} {clean_t}".strip()
            res = requests.get(
                "https://itunes.apple.com/search",
                params={"term": query, "entity": "song", "limit": 1},
                timeout=4,
            )
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    art_url = results[0].get("artworkUrl100", "")
                    if art_url:
                        # Convertir a 600x600 HD
                        hd_url = art_url.replace("100x100bb.jpg", "600x600bb.jpg")
                        img_res = requests.get(hd_url, timeout=5)
                        if img_res.status_code == 200 and len(img_res.content) > 1000:
                            with open(cache_file, "wb") as f:
                                f.write(img_res.content)
                            return img_res.content, "image/jpeg"
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
