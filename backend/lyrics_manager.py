import os
import re
import subprocess
import shutil
import requests
from typing import Dict, Any, List, Optional
from mutagen import File as MutagenFile

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

class LyricsManager:
    """Gestiona letras sincronizadas (.lrc) usando LRCLIB, etiquetas locales, calibración de offset y Whisper IA."""

    LRCLIB_BASE_URL = "https://lrclib.net/api"

    @staticmethod
    def parse_lrc(lrc_content: str, offset_seconds: float = 0.0) -> List[Dict[str, Any]]:
        """Convierte texto en formato LRC [mm:ss.xx]Texto en una lista de objetos con segundos y texto con soporte de offset."""
        lines = []
        pattern = re.compile(r"\[(\d{1,2}):(\d{1,2}(?:\.\d{1,3})?)\](.*)")
        
        # Buscar tag [offset:+/-ms] en la cabecera
        header_offset = 0.0
        for l in lrc_content.splitlines()[:5]:
            off_m = re.match(r"\[offset:([+-]?\d+)\]", l.strip(), re.IGNORECASE)
            if off_m:
                header_offset = float(off_m.group(1)) / 1000.0

        total_offset = offset_seconds + header_offset

        for raw_line in lrc_content.splitlines():
            raw_line = raw_line.strip()
            match = pattern.match(raw_line)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                time_sec = round(max(0.0, (minutes * 60 + seconds) + total_offset), 2)
                text = match.group(3).strip()
                if text:
                    lines.append({"time": time_sec, "text": text})

        lines.sort(key=lambda x: x["time"])
        return lines

    @classmethod
    def get_lyrics(cls, title: str, artist: str, filepath: Optional[str] = None, duration: Optional[int] = None, offset: float = 0.0) -> Dict[str, Any]:
        """
        Obtiene la letra sincronizada de la canción:
        1. Archivo local .lrc con offset.
        2. Búsqueda directa en LRCLIB.
        3. Búsqueda por tokens difusos en LRCLIB.
        4. Etiquetas ID3.
        """
        clean_title = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
        clean_artist = re.sub(r"\(.*?\)|\[.*?\]", "", artist).strip()
        if clean_artist.lower() in ["desconocido", "unknown", "búsqueda"]:
            clean_artist = ""

        # Separar primer artista si hay varios separados por comas
        first_artist = clean_artist.split(",")[0].strip() if clean_artist else ""

        # 1. Buscar .lrc local existente
        if filepath and os.path.exists(filepath):
            lrc_path = os.path.splitext(filepath)[0] + ".lrc"
            if os.path.exists(lrc_path):
                try:
                    with open(lrc_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        parsed = cls.parse_lrc(content, offset_seconds=offset)
                        if parsed:
                            return {
                                "source": "local_lrc",
                                "synced": True,
                                "lines": parsed,
                                "raw_lrc": content,
                                "title": title,
                                "artist": artist,
                                "offset": offset,
                            }
                except Exception:
                    pass

        # 2. Consultar LRCLIB con get directo
        try:
            params = {"track_name": clean_title}
            if clean_artist:
                params["artist_name"] = clean_artist
            if duration and duration > 0:
                params["duration"] = duration

            res = requests.get(f"{cls.LRCLIB_BASE_URL}/get", params=params, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if data.get("syncedLyrics"):
                    parsed = cls.parse_lrc(data["syncedLyrics"], offset_seconds=offset)
                    cls._save_lrc_cache(filepath, data["syncedLyrics"])
                    return {
                        "source": "lrclib",
                        "synced": True,
                        "lines": parsed,
                        "raw_lrc": data["syncedLyrics"],
                        "title": data.get("trackName", title),
                        "artist": data.get("artistName", artist),
                    }
        except Exception:
            pass

        # 3. Búsqueda por tokens difusos en LRCLIB (ej: "Blessd Ziploc", "Trueno FRESH")
        search_queries = [
            f"{first_artist} {clean_title}".strip(),
            f"{clean_artist} {clean_title}".strip(),
            clean_title,
        ]

        for q in search_queries:
            if not q or len(q) < 2:
                continue
            try:
                s_res = requests.get(f"{cls.LRCLIB_BASE_URL}/search", params={"q": q}, timeout=4)
                if s_res.status_code == 200:
                    items = s_res.json()
                    for it in items:
                        if it.get("syncedLyrics"):
                            parsed = cls.parse_lrc(it["syncedLyrics"], offset_seconds=offset)
                            cls._save_lrc_cache(filepath, it["syncedLyrics"])
                            return {
                                "source": "lrclib_search",
                                "synced": True,
                                "lines": parsed,
                                "raw_lrc": it["syncedLyrics"],
                                "title": it.get("trackName", title),
                                "artist": it.get("artistName", artist),
                            }
            except Exception:
                pass

        # 4. Etiquetas ID3 locales
        if filepath and os.path.exists(filepath):
            try:
                audio = MutagenFile(filepath)
                if audio and hasattr(audio, "tags") and audio.tags:
                    for k in audio.tags.keys():
                        if k.startswith("USLT") or k.startswith("SYLT") or "\xa9lyr" in k:
                            lyr_text = str(audio.tags[k])
                            parsed = cls.parse_lrc(lyr_text, offset_seconds=offset)
                            return {
                                "source": "id3_embedded",
                                "synced": bool(parsed),
                                "lines": parsed if parsed else [{"time": i * 4.0, "text": l} for i, l in enumerate(lyr_text.splitlines()) if l.strip()],
                                "plain_text": lyr_text,
                                "title": title,
                                "artist": artist,
                            }
            except Exception:
                pass

        return {
            "source": "none",
            "synced": False,
            "lines": [],
            "message": "Letra no encontrada en bases de datos públicas.",
            "can_transcribe_ai": True,
            "title": title,
            "artist": artist,
        }

    @staticmethod
    def _save_lrc_cache(filepath: Optional[str], lrc_content: str):
        if filepath and os.path.exists(filepath):
            try:
                lrc_save_path = os.path.splitext(filepath)[0] + ".lrc"
                with open(lrc_save_path, "w", encoding="utf-8") as f:
                    f.write(lrc_content)
            except Exception:
                pass

    @classmethod
    def apply_offset(cls, filepath: str, offset_seconds: float) -> Dict[str, Any]:
        """Ajusta y persiste el offset de calibración en el archivo .lrc local."""
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Pista no encontrada"}

        lrc_path = os.path.splitext(filepath)[0] + ".lrc"
        if not os.path.exists(lrc_path):
            return {"success": False, "error": "No hay archivo .lrc para esta pista"}

        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                content = f.read()

            parsed = cls.parse_lrc(content, offset_seconds=offset_seconds)
            return {"success": True, "lines": parsed, "offset": offset_seconds}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def transcribe_with_ai(cls, filepath: str) -> Dict[str, Any]:
        """
        Transcribe la voz del audio para canciones que no tienen letra en internet.
        Utiliza Whisper con extracción previa de audio si es video MP4.
        """
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Archivo no encontrado"}

        # Extraer audio temporal a WAV 16kHz si es video MP4 o formato pesado
        temp_wav = None
        ext = os.path.splitext(filepath)[1].lower()
        target_audio = filepath

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            appdata_bin = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Python", "Python311", "Lib", "site-packages", "static_ffmpeg", "bin", "win32", "ffmpeg.EXE")
            if os.path.exists(appdata_bin):
                ffmpeg = appdata_bin
            else:
                ffmpeg = "ffmpeg"

        if ext in [".mp4", ".mkv", ".webm", ".avi"] or True:
            temp_wav = os.path.join(os.path.dirname(filepath), f"_temp_whisper_{os.getpid()}.wav")
            cmd = [
                ffmpeg, "-y",
                "-i", filepath,
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                temp_wav
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                target_audio = temp_wav
            except Exception:
                target_audio = filepath

        try:
            import whisper
            model = whisper.load_model("tiny")
            result = model.transcribe(target_audio, fp16=False)
            segments = result.get("segments", [])
            lines = []
            lrc_lines = []

            for seg in segments:
                start = seg.get("start", 0)
                text = seg.get("text", "").strip()
                if text:
                    lines.append({"time": round(start, 2), "text": text})
                    m = int(start // 60)
                    s = start % 60
                    lrc_lines.append(f"[{m:02d}:{s:05.2f}]{text}")

            raw_lrc = "\n".join(lrc_lines)
            lrc_save_path = os.path.splitext(filepath)[0] + ".lrc"
            with open(lrc_save_path, "w", encoding="utf-8") as f:
                f.write(raw_lrc)

            return {
                "success": True,
                "synced": True,
                "lines": lines,
                "raw_lrc": raw_lrc,
                "model": "whisper-tiny",
            }
        except ImportError:
            return {
                "success": False,
                "error": "El modelo Whisper está terminando de inicializarse. Por favor intenta en unos momentos.",
            }
        except Exception as e:
            return {"success": False, "error": f"Error en transcripción IA: {str(e)}"}
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
