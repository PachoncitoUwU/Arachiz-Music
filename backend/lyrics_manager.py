import os
import re
import subprocess
import shutil
import requests
import urllib.parse
from html import unescape
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple
from mutagen import File as MutagenFile

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

class LyricsManager:
    """
    Motor inteligente de letras sincronizadas (.lrc) multi-fuente:
    1. Caché local .lrc con soporte de offset dinámico.
    2. LRCLIB (letras sincronizadas [mm:ss.xx] oficiales).
    3. Scraper web (Letras.com, Genius, LRCLIB plain) para letras oficiales en texto plano.
    4. Sincronización IA Whisper: Alineación de texto oficial con marcas de tiempo de audio.
    5. Transcripción Autónoma con IA Whisper: Generación de letra + sincronización completa si no existe en internet.
    """

    LRCLIB_BASE_URL = "https://lrclib.net/api"

    @staticmethod
    def clean_slug(text: str) -> str:
        """Limpia cadenas para slugs web (letras.com, etc.)."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"\(.*?\)|\[.*?\]", "", text).strip()
        # Normalizar acentos y diacríticos
        text = re.sub(r"[áàäâ]", "a", text)
        text = re.sub(r"[éèëê]", "e", text)
        text = re.sub(r"[íìïî]", "i", text)
        text = re.sub(r"[óòöô]", "o", text)
        text = re.sub(r"[úùüû]", "u", text)
        text = re.sub(r"[ñ]", "n", text)
        text = re.sub(r"[^a-z0-9\s-]", "", text)
        text = re.sub(r"\s+", "-", text)
        return text.strip("-")

    @staticmethod
    def extract_lyrics_from_html(html_text: str) -> Optional[str]:
        """Extrae el contenido de letra limpia desde el HTML de Letras.com."""
        if not html_text:
            return None
        m = re.search(r'<div[^>]*class="[^"]*(?:lyric-original|lyric-cnt)[^"]*"[^>]*>(.*?)</div>\s*</div>', html_text, re.DOTALL | re.IGNORECASE)
        if not m:
            m = re.search(r'<div[^>]*class="[^"]*(?:lyric-original|lyric-cnt)[^"]*"[^>]*>(.*?)</div>', html_text, re.DOTALL | re.IGNORECASE)
        if m:
            content = m.group(1)
            content = re.sub(r'<p[^>]*>', '', content, flags=re.IGNORECASE)
            content = re.sub(r'</p>', '\n\n', content, flags=re.IGNORECASE)
            content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
            content = re.sub(r'<[^>]+>', '', content)
            content = unescape(content).strip()
            lines = [line.strip() for line in content.splitlines()]
            clean_lines = []
            for l in lines:
                if l:
                    clean_lines.append(l)
                elif clean_lines and clean_lines[-1] != "":
                    clean_lines.append("")
            return "\n".join(clean_lines)
        return None

    @classmethod
    def search_letras_com(cls, title: str, artist: str) -> Tuple[Optional[str], Optional[str]]:
        """Busca y extrae la letra oficial de una canción en letras.com."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
        }

        first_artist = artist.split(",")[0].split("&")[0].split("feat")[0].strip() if artist else ""
        artist_slug = cls.clean_slug(first_artist)
        title_slug = cls.clean_slug(title)

        # 1. Acceso directo por URL canónica
        if artist_slug and title_slug:
            direct_url = f"https://www.letras.com/{artist_slug}/{title_slug}/"
            try:
                r = requests.get(direct_url, headers=headers, timeout=5)
                if r.status_code == 200:
                    lyrics = cls.extract_lyrics_from_html(r.text)
                    if lyrics and len(lyrics) > 20:
                        return lyrics, direct_url
            except Exception:
                pass

        # 2. Búsqueda vía API interna de Letras.com
        if first_artist or title:
            try:
                q = f"{first_artist} {title}".strip()
                s_url = f"https://m.letras.com/api/search/{urllib.parse.quote(q)}"
                r = requests.get(s_url, headers=headers, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    for it in data.get("results", data.get("songs", [])):
                        url_path = it.get("url") or it.get("path") or it.get("dns")
                        if url_path:
                            song_url = f"https://www.letras.com{url_path}" if url_path.startswith("/") else url_path
                            r2 = requests.get(song_url, headers=headers, timeout=5)
                            if r2.status_code == 200:
                                lyrics = cls.extract_lyrics_from_html(r2.text)
                                if lyrics and len(lyrics) > 20:
                                    return lyrics, song_url
            except Exception:
                pass

        # 3. DuckDuckGo HTML fallback
        if first_artist or title:
            try:
                q = f"site:letras.com {first_artist} {title} letra"
                ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
                r = requests.get(ddg_url, headers=headers, timeout=5)
                if r.status_code == 200:
                    matches = re.findall(r'(https?://(?:www\.)?letras\.com/[a-z0-9-]+/[a-z0-9-]+/)', r.text)
                    for m_url in matches[:2]:
                        r2 = requests.get(m_url, headers=headers, timeout=5)
                        if r2.status_code == 200:
                            lyrics = cls.extract_lyrics_from_html(r2.text)
                            if lyrics and len(lyrics) > 20:
                                return lyrics, m_url
            except Exception:
                pass

        return None, None

    @classmethod
    def search_web_lyrics(cls, title: str, artist: str) -> Dict[str, Any]:
        """Busca letras en texto plano a través de múltiples fuentes (Letras.com, LRCLIB plain, etc.)."""
        # 1. Letras.com
        lyrics, url = cls.search_letras_com(title, artist)
        if lyrics:
            return {
                "found": True,
                "source": "letras.com",
                "plain_text": lyrics,
                "url": url,
            }

        # 2. LRCLIB plainLyrics
        clean_title = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
        clean_artist = re.sub(r"\(.*?\)|\[.*?\]", "", artist).strip()
        first_artist = clean_artist.split(",")[0].strip() if clean_artist else ""

        try:
            params = {"track_name": clean_title}
            if first_artist:
                params["artist_name"] = first_artist
            res = requests.get(f"{cls.LRCLIB_BASE_URL}/get", params=params, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if data.get("plainLyrics"):
                    return {
                        "found": True,
                        "source": "lrclib_plain",
                        "plain_text": data["plainLyrics"],
                        "url": "https://lrclib.net",
                    }
        except Exception:
            pass

        return {"found": False, "source": "none", "plain_text": None, "url": None}

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
        Obtiene la letra de la canción siguiendo la jerarquía multi-fuente:
        1. Archivo local .lrc ya sincronizado.
        2. LRCLIB (sincronizada directa).
        3. LRCLIB (búsqueda difusa sincronizada).
        4. Letras.com / Web (letra en texto plano disponible para auto-sincronización IA).
        5. ID3 local.
        6. Si no existe en ningún lado, ofrece transcripción y generación total con Whisper IA.
        """
        clean_title = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
        clean_artist = re.sub(r"\(.*?\)|\[.*?\]", "", artist).strip()
        if clean_artist.lower() in ["desconocido", "unknown", "búsqueda"]:
            clean_artist = ""

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

        # 2. Consultar LRCLIB con get directo (Sincronizado)
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

        # 3. Búsqueda por tokens difusos en LRCLIB
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
                            # Validar similitud del resultado fuzzy contra el título solicitado
                            returned_title = cls._clean_text_for_match(it.get("trackName", ""))
                            requested_title = cls._clean_text_for_match(clean_title)
                            title_similarity = SequenceMatcher(None, requested_title, returned_title).ratio()
                            
                            returned_artist = cls._clean_text_for_match(it.get("artistName", ""))
                            requested_artist = cls._clean_text_for_match(first_artist)
                            artist_similarity = SequenceMatcher(None, requested_artist, returned_artist).ratio() if requested_artist else 1.0
                            
                            confidence = "high" if (title_similarity > 0.6 and artist_similarity > 0.4) else "low"
                            
                            parsed = cls.parse_lrc(it["syncedLyrics"], offset_seconds=offset)
                            cls._save_lrc_cache(filepath, it["syncedLyrics"])
                            return {
                                "source": "lrclib_search",
                                "synced": True,
                                "lines": parsed,
                                "raw_lrc": it["syncedLyrics"],
                                "title": it.get("trackName", title),
                                "artist": it.get("artistName", artist),
                                "confidence": confidence,
                                "matched_title": it.get("trackName", ""),
                                "matched_artist": it.get("artistName", ""),
                            }
            except Exception:
                pass

        # 4. Búsqueda Web de Texto Plano (Letras.com / Genius)
        web_res = cls.search_web_lyrics(title, artist)
        if web_res.get("found") and web_res.get("plain_text"):
            plain_lines = [l.strip() for l in web_res["plain_text"].splitlines() if l.strip()]
            return {
                "source": web_res["source"],
                "synced": False,
                "has_plain_text": True,
                "can_align_ai": True,
                "plain_text": web_res["plain_text"],
                "url": web_res.get("url"),
                "lines": [{"time": i * 4.0, "text": l} for i, l in enumerate(plain_lines)],
                "message": f"Letra oficial encontrada en {web_res['source']}. Puedes sincronizarla automáticamente con IA.",
                "title": title,
                "artist": artist,
            }

        # 5. Etiquetas ID3 locales
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
                                "has_plain_text": True,
                                "can_align_ai": True,
                                "lines": parsed if parsed else [{"time": i * 4.0, "text": l} for i, l in enumerate(lyr_text.splitlines()) if l.strip()],
                                "plain_text": lyr_text,
                                "title": title,
                                "artist": artist,
                            }
            except Exception:
                pass

        # 6. No encontrada en internet -> Generar y sincronizar completamente desde el audio con Whisper IA
        return {
            "source": "none",
            "synced": False,
            "has_plain_text": False,
            "lines": [],
            "message": "Letra no encontrada en internet. Puedes generarla y sincronizarla automáticamente con Whisper IA.",
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

    @staticmethod
    def _clean_text_for_match(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return text.strip()

    @classmethod
    def align_lyrics_with_whisper(cls, official_plain_text: str, whisper_segments: List[Dict[str, Any]], total_duration: float = 0.0) -> Tuple[List[Dict[str, Any]], str]:
        """
        Alinea versos oficiales obtenidos de Letras.com/Genius con las marcas de tiempo extraídas del audio por Whisper IA.
        """
        official_lines = [l.strip() for l in official_plain_text.splitlines() if l.strip() and not re.match(r"^\[.*?\]$", l.strip())]

        if not official_lines:
            lines = []
            lrc_lines = []
            for seg in whisper_segments:
                st = round(seg.get("start", 0), 2)
                txt = seg.get("text", "").strip()
                if txt:
                    lines.append({"time": st, "text": txt})
                    m = int(st // 60)
                    s = st % 60
                    lrc_lines.append(f"[{m:02d}:{s:05.2f}]{txt}")
            return lines, "\n".join(lrc_lines)

        if not whisper_segments:
            lines = []
            lrc_lines = []
            interval = (total_duration / len(official_lines)) if total_duration > 10 else 3.5
            for i, line in enumerate(official_lines):
                t = round(i * interval, 2)
                lines.append({"time": t, "text": line})
                m = int(t // 60)
                s = t % 60
                lrc_lines.append(f"[{m:02d}:{s:05.2f}]{line}")
            return lines, "\n".join(lrc_lines)

        matched_lines = []
        lrc_lines = []
        current_seg_idx = 0
        num_segs = len(whisper_segments)

        for line in official_lines:
            clean_line = cls._clean_text_for_match(line)
            best_score = 0.0
            best_time = None
            best_seg_idx = current_seg_idx

            search_window = whisper_segments[max(0, current_seg_idx - 1): min(num_segs, current_seg_idx + 6)]

            for offset, seg in enumerate(search_window):
                seg_text = cls._clean_text_for_match(seg.get("text", ""))
                ratio = SequenceMatcher(None, clean_line, seg_text).ratio()
                if clean_line in seg_text or seg_text in clean_line:
                    ratio = max(ratio, 0.75)
                if ratio > best_score:
                    best_score = ratio
                    best_time = seg.get("start", 0)
                    best_seg_idx = max(0, current_seg_idx - 1) + offset

            if best_score >= 0.38 and best_time is not None:
                time_val = round(best_time, 2)
                current_seg_idx = best_seg_idx + 1
            else:
                if matched_lines:
                    time_val = round(matched_lines[-1]["time"] + 2.8, 2)
                else:
                    time_val = round(whisper_segments[0].get("start", 0), 2) if whisper_segments else 0.0

            matched_lines.append({"time": time_val, "text": line})
            m = int(time_val // 60)
            s = time_val % 60
            lrc_lines.append(f"[{m:02d}:{s:05.2f}]{line}")

        return matched_lines, "\n".join(lrc_lines)

    @classmethod
    def smart_sync_with_ai(cls, filepath: str, title: str = "", artist: str = "", duration: float = 0.0) -> Dict[str, Any]:
        """
        Flujo de sincronización y generación inteligente:
        1. Si la canción está en Letras.com o la web -> La descarga y usa Whisper IA para alinearla al audio.
        2. Si la canción NO está en ninguna página de letras -> Whisper IA transcribe la voz del audio y genera la letra sincronizada.
        3. Guarda el archivo .lrc resultante en el almacenamiento local.
        """
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Archivo de audio no encontrado"}

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
            # 1. Buscar letra oficial en la web (Letras.com, Genius)
            web_lyrics = cls.search_web_lyrics(title, artist)
            has_official_text = web_lyrics.get("found") and web_lyrics.get("plain_text")
            plain_text = web_lyrics.get("plain_text") if has_official_text else None
            source_used = web_lyrics.get("source", "whisper_ai")

            # 2. Ejecutar Whisper para obtener marcas de tiempo del audio
            import whisper
            model = whisper.load_model("tiny")
            result = model.transcribe(target_audio, fp16=False)
            segments = result.get("segments", [])

            if has_official_text and plain_text:
                # Caso A: Letra encontrada en Letras.com -> Alinear texto oficial con timestamps de Whisper
                lines, raw_lrc = cls.align_lyrics_with_whisper(plain_text, segments, total_duration=duration)
                final_source = f"{source_used} + Whisper IA Alignment"
            else:
                # Caso B: Letra no existe en ninguna página -> Transcripción completa con Whisper IA
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
                final_source = "Whisper IA Autonomous Speech-To-Text"

            # 3. Guardar .lrc persistente
            lrc_save_path = os.path.splitext(filepath)[0] + ".lrc"
            with open(lrc_save_path, "w", encoding="utf-8") as f:
                f.write(raw_lrc)

            return {
                "success": True,
                "synced": True,
                "lines": lines,
                "raw_lrc": raw_lrc,
                "source": final_source,
                "model": "whisper-tiny",
                "matched_from_web": has_official_text,
            }
        except ImportError:
            return {
                "success": False,
                "error": "El motor Whisper IA está inicializándose. Por favor intenta en unos instantes.",
            }
        except Exception as e:
            return {"success": False, "error": f"Error en sincronización IA: {str(e)}"}
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass

    @classmethod
    def transcribe_with_ai(cls, filepath: str) -> Dict[str, Any]:
        """Alias de compatibilidad hacia smart_sync_with_ai."""
        return cls.smart_sync_with_ai(filepath)

    @classmethod
    def save_manual_lyrics(cls, filepath: str, text: str) -> Dict[str, Any]:
        """
        Guarda una letra proporcionada manualmente por el usuario.
        Si el texto tiene formato LRC ([mm:ss.xx]...) lo guarda directo.
        Si es texto plano, lo guarda con timestamps estimados.
        """
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Archivo de audio no encontrado"}

        if not text or not text.strip():
            return {"success": False, "error": "El texto de la letra está vacío"}

        lrc_path = os.path.splitext(filepath)[0] + ".lrc"

        # Detectar si ya es formato LRC
        lrc_pattern = re.compile(r"\[\d{1,2}:\d{1,2}(?:\.\d{1,3})?\]")
        is_lrc_format = bool(lrc_pattern.search(text))

        if is_lrc_format:
            # Guardar directamente como LRC
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(text.strip())
            parsed = cls.parse_lrc(text)
            return {
                "success": True,
                "synced": True,
                "lines": parsed,
                "raw_lrc": text.strip(),
                "source": "manual_lrc",
                "message": "Letra LRC guardada exitosamente.",
            }
        else:
            # Texto plano: guardar con timestamps estimados (~3.5s por línea)
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
            lrc_lines = []
            parsed = []
            for i, line in enumerate(lines):
                t = round(i * 3.5, 2)
                m = int(t // 60)
                s = t % 60
                lrc_lines.append(f"[{m:02d}:{s:05.2f}]{line}")
                parsed.append({"time": t, "text": line})

            raw_lrc = "\n".join(lrc_lines)
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(raw_lrc)

            return {
                "success": True,
                "synced": True,
                "lines": parsed,
                "raw_lrc": raw_lrc,
                "source": "manual_plain",
                "message": "Letra guardada con timestamps estimados. Usa 'Sincronizar con IA' para alinearla mejor.",
                "can_sync_ai": True,
            }

    @classmethod
    def sync_user_text_with_ai(cls, filepath: str, user_text: str, title: str = "", artist: str = "", duration: float = 0.0) -> Dict[str, Any]:
        """
        Sincroniza texto proporcionado por el usuario (no buscado en internet)
        con las marcas de tiempo del audio usando Whisper IA.
        """
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Archivo de audio no encontrado"}

        if not user_text or not user_text.strip():
            return {"success": False, "error": "El texto de la letra está vacío"}

        # Extraer audio temporal a WAV 16kHz
        temp_wav = None
        target_audio = filepath

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            appdata_bin = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Python", "Python311", "Lib", "site-packages", "static_ffmpeg", "bin", "win32", "ffmpeg.EXE")
            if os.path.exists(appdata_bin):
                ffmpeg = appdata_bin
            else:
                ffmpeg = "ffmpeg"

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

            # Alinear el texto del usuario con los timestamps de Whisper
            lines, raw_lrc = cls.align_lyrics_with_whisper(user_text, segments, total_duration=duration)

            # Guardar .lrc persistente
            lrc_save_path = os.path.splitext(filepath)[0] + ".lrc"
            with open(lrc_save_path, "w", encoding="utf-8") as f:
                f.write(raw_lrc)

            return {
                "success": True,
                "synced": True,
                "lines": lines,
                "raw_lrc": raw_lrc,
                "source": "user_text + Whisper IA Alignment",
                "model": "whisper-tiny",
                "message": "Letra del usuario sincronizada con el audio exitosamente.",
            }
        except ImportError:
            return {
                "success": False,
                "error": "El motor Whisper IA no está disponible. La letra se guardó como texto plano.",
            }
        except Exception as e:
            return {"success": False, "error": f"Error en sincronización IA: {str(e)}"}
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass

    @classmethod
    def delete_lyrics(cls, filepath: str) -> Dict[str, Any]:
        """Borra el archivo .lrc local de una canción para permitir reemplazarlo."""
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "Archivo de audio no encontrado"}

        lrc_path = os.path.splitext(filepath)[0] + ".lrc"
        if os.path.exists(lrc_path):
            try:
                os.remove(lrc_path)
                return {"success": True, "message": "Letra eliminada. Puedes escribir una nueva o buscar en internet."}
            except Exception as e:
                return {"success": False, "error": f"No se pudo eliminar el archivo: {str(e)}"}
        else:
            return {"success": True, "message": "No había letra guardada para esta canción."}
