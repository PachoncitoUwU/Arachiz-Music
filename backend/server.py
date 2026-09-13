import os
import sys
import json
import asyncio
import socket
import yt_dlp
import subprocess
import requests
import time
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Asegurar que el directorio de backend esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resolver import MusicResolver
from downloader import PelotaDownloader
from library_manager import LibraryManager
from lyrics_manager import LyricsManager
from mood_engine import MoodEngine
from audio_studio import AudioStudio
from checklist_manager import ChecklistManager
from profiles_manager import ProfilesManager

app = FastAPI(title="Arachiz Music API", version="3.1")


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(data: dict) -> dict:
    cfg = load_config()
    cfg.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


_initial_cfg = load_config()
_initial_dir = _initial_cfg.get("output_directory")
downloader = PelotaDownloader(output_base_dir=_initial_dir) if _initial_dir else PelotaDownloader()
library_manager = LibraryManager(downloader.output_base_dir)
audio_studio = AudioStudio(downloader.output_base_dir)

# ── WebSocket ─────────────────────────────────────────────────────────────────
active_connections: List[WebSocket] = []


async def broadcast_ws(message: dict):
    dead = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            dead.append(connection)
    for d in dead:
        try:
            active_connections.remove(d)
        except ValueError:
            pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        try:
            active_connections.remove(websocket)
        except ValueError:
            pass


# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url_or_query: str


class TrackDownloadItem(BaseModel):
    title: str
    artist: str
    query: str
    duration: Optional[str] = "--:--"
    cover: Optional[str] = ""
    source: Optional[str] = "unknown"
    direct_url: Optional[str] = None
    preview_url: Optional[str] = None
    is_playlist_cover: Optional[bool] = False


class BatchDownloadRequest(BaseModel):
    playlist_name: str
    format: str = "mp3"
    quality: str = "balanced"
    genre: Optional[str] = ""
    video_mode: Optional[str] = "official"
    tracks: List[TrackDownloadItem]
    custom_output_dir: Optional[str] = None


class SingleDownloadRequest(BaseModel):
    track: TrackDownloadItem
    playlist_name: str = "Descargas"
    format: str = "mp3"
    quality: str = "balanced"
    genre: Optional[str] = ""
    video_mode: Optional[str] = "official"
    custom_output_dir: Optional[str] = None


class OpenFolderRequest(BaseModel):
    folder_path: Optional[str] = None


class SettingsRequest(BaseModel):
    output_directory: Optional[str] = None
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None
    default_format: Optional[str] = None
    default_quality: Optional[str] = None


class TestSpotifyRequest(BaseModel):
    client_id: str
    client_secret: str


class TrimAudioRequest(BaseModel):
    track_id: str
    start_sec: float
    end_sec: float


class MergeAudioRequest(BaseModel):
    track1_id: str
    track2_id: str
    crossfade_sec: float = 4.0


class StemsAudioRequest(BaseModel):
    track_id: str
    mode: str = "both"  # "beat", "vocal", "both"


class ChecklistToggleRequest(BaseModel):
    id: str


class ChecklistAddRequest(BaseModel):
    title: str
    category: Optional[str] = "✨ Mis Nuevas Ideas"
    detail: Optional[str] = ""


class TranscribeRequest(BaseModel):
    track_id: str


class OffsetLyricsRequest(BaseModel):
    track_id: str
    offset: float


class ProfileCreateRequest(BaseModel):
    name: str
    icon: Optional[str] = "fa-user"


class ProfileSaveRequest(BaseModel):
    favorites: Optional[List[str]] = None
    playlists: Optional[Dict[str, List[str]]] = None
    history: Optional[List[Dict[str, Any]]] = None
    lyrics_offsets: Optional[Dict[str, float]] = None
    offline_cached: Optional[List[str]] = None



# ── Rutas de Configuración & Red ──────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    """Devuelve la configuración actual incluyendo credenciales y carpeta."""
    cfg = load_config()
    cid, csec = MusicResolver.get_spotify_credentials()
    has_creds = bool(cid and csec)
    masked_cid = f"{cid[:4]}...{cid[-4:]}" if (cid and len(cid) >= 8) else ("Configurado" if cid else "")

    return {
        "app_name": "Arachiz Music",
        "output_directory": downloader.output_base_dir,
        "version": "3.0",
        "has_spotify_credentials": has_creds,
        "spotify_client_id_preview": masked_cid,
        "default_format": cfg.get("default_format", "mp3"),
        "default_quality": cfg.get("default_quality", "balanced"),
    }


@app.get("/api/network-info")
def get_network_info():
    """Devuelve la IP local de Wi-Fi para conectar celulares iPhone y Samsung."""
    local_ip = get_local_ip()
    port = 5555
    return {
        "local_ip": local_ip,
        "port": port,
        "mobile_url": f"http://{local_ip}:{port}",
        "instructions": "Abre este enlace en el navegador de tu celular (Safari en iPhone o Chrome en Samsung/Android) en la misma red Wi-Fi y selecciona 'Agregar a pantalla de inicio' para usar Arachiz Music como aplicación nativa."
    }


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    """Guarda la configuración general y credenciales de Spotify."""
    global downloader, library_manager, audio_studio
    updates = {}
    if req.output_directory and req.output_directory.strip():
        new_dir = req.output_directory.strip()
        try:
            os.makedirs(new_dir, exist_ok=True)
            downloader = PelotaDownloader(output_base_dir=new_dir)
            library_manager.set_base_dir(new_dir)
            audio_studio = AudioStudio(new_dir)
            updates["output_directory"] = new_dir
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo acceder a la carpeta: {e}")

    if req.spotify_client_id is not None:
        updates["spotify_client_id"] = req.spotify_client_id.strip()
    if req.spotify_client_secret is not None:
        updates["spotify_client_secret"] = req.spotify_client_secret.strip()
    if req.default_format is not None:
        updates["default_format"] = req.default_format.strip()
    if req.default_quality is not None:
        updates["default_quality"] = req.default_quality.strip()

    save_config(updates)
    return {"status": "ok", "config": get_config()}


@app.post("/api/test-spotify")
def test_spotify_credentials(req: TestSpotifyRequest):
    """Verifica si las credenciales de Spotify Client ID y Secret son válidas."""
    cid = req.client_id.strip()
    csec = req.client_secret.strip()
    if not cid or not csec:
        raise HTTPException(status_code=400, detail="Por favor ingresa tanto el Client ID como el Client Secret.")

    try:
        import requests as rq
        r = rq.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(cid, csec),
            timeout=8,
        )
        if r.status_code == 200 and r.json().get("access_token"):
            return {
                "success": True,
                "message": "¡Credenciales verificadas exitosamente! Soporte para 3,000+ canciones activado.",
            }
        else:
            detail = r.json().get("error_description", f"Error HTTP {r.status_code}")
            return {
                "success": False,
                "message": f"Spotify rechazó las credenciales: {detail}",
            }
    except Exception as e:
        return {"success": False, "message": f"Error al verificar credenciales: {str(e)}"}


@app.post("/api/set-output-dir")
def set_output_dir(body: dict):
    global downloader, library_manager, audio_studio
    new_dir = body.get("directory", "").strip()
    if not new_dir:
        raise HTTPException(status_code=400, detail="Directorio vacío")
    try:
        os.makedirs(new_dir, exist_ok=True)
        downloader = PelotaDownloader(output_base_dir=new_dir)
        library_manager.set_base_dir(new_dir)
        audio_studio = AudioStudio(new_dir)
        save_config({"output_directory": new_dir})
        return {"status": "ok", "output_directory": downloader.output_base_dir}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo crear la carpeta: {e}")


# ── Rutas de Biblioteca & Streaming (HTTP 206 Byte-Range) ─────────────────────

@app.get("/api/library")
def get_library():
    """Escanea y devuelve el catálogo completo de música local."""
    return library_manager.scan_library()


@app.get("/api/stream/{track_id}")
def stream_audio(track_id: str, request: Request):
    """Transmite audio local con soporte Range para seeking inmediato."""
    range_header = request.headers.get("Range")
    return library_manager.stream_file(track_id, range_header=range_header)


@app.get("/api/cover/{track_id}")
def get_cover(track_id: str):
    """Sirve la carátula oficial extraída de la pista o carpeta."""
    res = library_manager.extract_cover_bytes(track_id)
    if not res:
        raise HTTPException(status_code=404, detail="Carátula no encontrada")
    data, mime = res
    return Response(content=data, media_type=mime)


class UpdateCoverRequest(BaseModel):
    track_id: str
    cover_url: str
    video_url: Optional[str] = None


@app.post("/api/track/cover")
def update_track_cover(req: UpdateCoverRequest):
    """Descarga o asigna una nueva carátula permanente a la canción y la incrusta en MP3."""
    track = library_manager.get_track_by_id(req.track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Canción no encontrada")

    filepath = track.get("filepath")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Archivo de audio no encontrado")

    img_data = None
    if req.cover_url.startswith("http"):
        try:
            r = requests.get(req.cover_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code == 200 and len(r.content) > 500:
                img_data = r.content
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo descargar la imagen: {e}")
    elif req.cover_url.startswith("data:image"):
        try:
            import base64
            _, b64_data = req.cover_url.split(",", 1)
            img_data = base64.b64decode(b64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Imagen base64 inválida: {e}")

    if not img_data:
        raise HTTPException(status_code=400, detail="Formato o URL de imagen inválido")

    # Guardar cover.jpg en la carpeta de la canción
    track_dir = os.path.dirname(filepath)
    name_no_ext = os.path.splitext(os.path.basename(filepath))[0]
    cover_path = os.path.join(track_dir, f"{name_no_ext}.jpg")
    try:
        with open(cover_path, "wb") as f:
            f.write(img_data)
    except Exception as e:
        print(f"[Cover] Error guardando archivo cover: {e}")

    # Incrustar en ID3 si es MP3
    if filepath.lower().endswith(".mp3"):
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC
            try:
                id3 = ID3(filepath)
            except Exception:
                audio = MP3(filepath)
                audio.add_tags()
                id3 = ID3(filepath)
            id3.delall("APIC")
            id3.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=img_data
            ))
            id3.save(v2_version=3)
        except Exception as e:
            print(f"[Cover] Error incrustando ID3 cover: {e}")

    # Actualizar metadata en caché
    ts = int(time.time())
    new_cover_url = f"/api/cover/{req.track_id}?t={ts}"
    track["cover_url"] = new_cover_url
    return {"success": True, "cover_url": new_cover_url, "message": "Carátula actualizada permanentemente"}



# ── Rutas de Letras Sincronizadas & Transcripción IA ─────────────────────────

@app.get("/api/lyrics")
def get_lyrics(title: str, artist: str = "", track_id: Optional[str] = None):
    """Busca letras sincronizadas en LRCLIB y caché local .lrc."""
    filepath = None
    duration = None
    if track_id:
        track = library_manager.get_track_by_id(track_id)
        if track:
            filepath = track.get("filepath")
            duration = track.get("duration_seconds")
            if not title:
                title = track.get("title", "")
            if not artist:
                artist = track.get("artist", "")

    return LyricsManager.get_lyrics(title=title, artist=artist, filepath=filepath, duration=duration)


@app.post("/api/lyrics/offset")
def set_lyrics_offset(req: OffsetLyricsRequest):
    """Calibra y ajusta el desfase de tiempo (+/- segundos) de las letras de una canción."""
    track = library_manager.get_track_by_id(req.track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Canción no encontrada")
    return LyricsManager.apply_offset(track["filepath"], req.offset)


@app.post("/api/lyrics/transcribe")
@app.post("/api/lyrics/auto-sync")
def transcribe_or_sync_lyrics(req: TranscribeRequest):
    """
    Sincronización multi-fuente con IA:
    1. Si la letra está en Letras.com/web, la descarga y usa Whisper IA para alinearla al audio.
    2. Si no existe en ninguna página, Whisper IA transcribe la voz y la sincroniza automáticamente.
    """
    track = library_manager.get_track_by_id(req.track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Canción no encontrada")
    return LyricsManager.smart_sync_with_ai(
        filepath=track["filepath"],
        title=track.get("title", ""),
        artist=track.get("artist", ""),
        duration=track.get("duration_seconds", 0.0)
    )


@app.get("/api/video-info")
async def get_video_info(title: str, artist: str = "", track_id: Optional[str] = None):
    """Obtiene el video oficial HD de YouTube para reproducirlo en lugar de la carátula estática."""
    if track_id:
        track = library_manager.get_track_by_id(track_id)
        if track and track.get("format") == "mp4":
            return {
                "is_local_video": True,
                "stream_url": f"/api/stream/{track_id}",
                "title": track.get("title"),
                "artist": track.get("artist")
            }

    clean_q = f"{artist} {title} official music video".strip()

    def _find():
        ydl_opts = {"quiet": True, "extract_flat": True, "no_warnings": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{clean_q}", download=False)
                entries = info.get("entries", []) if info else []
                if entries and entries[0]:
                    vid = entries[0].get("id")
                    return {
                        "is_local_video": False,
                        "video_id": vid,
                        "embed_url": f"https://www.youtube-nocookie.com/embed/{vid}?autoplay=1&enablejsapi=1&modestbranding=1",
                        "title": entries[0].get("title"),
                    }
        except Exception:
            pass
        return {"is_local_video": False, "video_id": None}

    return await asyncio.to_thread(_find)


# ── Rutas de Perfiles Multidispositivo & Modo Offline ────────────────────────

@app.get("/api/profiles")
def get_profiles():
    """Lista los perfiles de dispositivos configurados."""
    return ProfilesManager.get_profiles()


@app.post("/api/profiles/create")
def create_profile(req: ProfileCreateRequest):
    """Crea un nuevo perfil para un celular o computadora."""
    return ProfilesManager.create_profile(req.name, req.icon or "fa-user")


@app.get("/api/profile/{profile_id}")
def get_profile_data(profile_id: str):
    """Obtiene favoritos, listas y canciones guardadas para este dispositivo."""
    return ProfilesManager.get_profile_data(profile_id)


@app.post("/api/profile/{profile_id}")
def save_profile_data(profile_id: str, req: ProfileSaveRequest):
    """Guarda y sincroniza los datos del dispositivo de forma persistente."""
    current = ProfilesManager.get_profile_data(profile_id)
    if req.favorites is not None:
        current["favorites"] = req.favorites
    if req.playlists is not None:
        current["playlists"] = req.playlists
    if req.history is not None:
        current["history"] = req.history
    if req.lyrics_offsets is not None:
        current["lyrics_offsets"] = req.lyrics_offsets
    if req.offline_cached is not None:
        current["offline_cached"] = req.offline_cached
    return ProfilesManager.save_profile_data(profile_id, current)



# ── Rutas de IA Mood Studio & Descubrimiento Musical ─────────────────────────

@app.get("/api/mood/sequence")
def get_mood_sequence(mood: Optional[str] = None, count: int = 7):
    """Genera una secuencia armónica inteligente de 5 a 7 canciones del mismo mood."""
    lib = library_manager.scan_library()
    tracks = lib.get("tracks", [])
    return MoodEngine.generate_mood_sequence(tracks=tracks, target_mood=mood, count=count)


@app.get("/api/mood/discover")
async def discover_music(mood: str = "workout", query: Optional[str] = None):
    """Descubre nuevas canciones afines al mood desde internet con carátulas y previews."""
    search_term = query.strip() if query else None
    if not search_term:
        queries = MoodEngine.get_discovery_queries(mood)
        search_term = queries[0]

    try:
        # Buscar en YouTube Music / YouTube vía yt-dlp de forma segura
        def _search():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "default_search": f"ytsearch8:{search_term}",
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch8:{search_term}", download=False)
                entries = info.get("entries", []) if info else []
                results = []
                for e in entries:
                    if e:
                        dur_s = e.get("duration") or 0
                        m = int(dur_s // 60)
                        s = int(dur_s % 60)
                        dur_str = f"{m}:{s:02d}" if dur_s > 0 else "--:--"
                        results.append({
                            "title": e.get("title", "Desconocido"),
                            "artist": e.get("uploader", e.get("channel", "YouTube")),
                            "query": e.get("url") or e.get("id"),
                            "duration": dur_str,
                            "cover": (e.get("thumbnails") or [{}])[-1].get("url", ""),
                            "source": "youtube",
                            "direct_url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id')}"
                        })
                return results

        items = await asyncio.to_thread(_search)
        return {"query": search_term, "mood": mood, "tracks": items}
    except Exception as e:
        return {"query": search_term, "mood": mood, "tracks": [], "error": str(e)}


# ── Rutas de Estudio de Audio (Recorte, Unión & Stems) ────────────────────────

@app.post("/api/audio/trim")
def trim_audio(req: TrimAudioRequest):
    """Recorta un fragmento de una canción."""
    track = library_manager.get_track_by_id(req.track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    res = audio_studio.trim_audio(track["filepath"], req.start_sec, req.end_sec)
    library_manager.scan_library()  # Actualizar catálogo
    return res


@app.post("/api/audio/merge")
def merge_audio(req: MergeAudioRequest):
    """Une dos pistas con crossfade logarítmico."""
    track1 = library_manager.get_track_by_id(req.track1_id)
    track2 = library_manager.get_track_by_id(req.track2_id)
    if not track1 or not track2:
        raise HTTPException(status_code=404, detail="Una de las pistas no fue encontrada")
    res = audio_studio.merge_with_crossfade(track1["filepath"], track2["filepath"], req.crossfade_sec)
    library_manager.scan_library()
    return res


@app.post("/api/audio/stems")
def separate_stems(req: StemsAudioRequest):
    """Separa pistas en Solo Voz (Acapella) o Solo Beat (Instrumental)."""
    track = library_manager.get_track_by_id(req.track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    res = audio_studio.separate_stems(track["filepath"], mode=req.mode)
    library_manager.scan_library()
    return res


# ── Rutas de Checklist Interactivo ───────────────────────────────────────────

@app.get("/api/checklist")
def get_checklist():
    """Devuelve los ítems del checklist de Arachiz Music."""
    return ChecklistManager.get_items()


@app.post("/api/checklist/toggle")
def toggle_checklist(req: ChecklistToggleRequest):
    """Marca o desmarca un ítem del checklist."""
    return ChecklistManager.toggle_item(req.id)


@app.post("/api/checklist/add")
def add_checklist_item(req: ChecklistAddRequest):
    """Agrega una nueva idea o requerimiento al checklist."""
    return ChecklistManager.add_item(req.title, req.category or "✨ Mis Nuevas Ideas", req.detail or "")


# ── Rutas de Descarga y Análisis Existentes ───────────────────────────────────

@app.post("/api/analyze")
async def analyze_url(req: AnalyzeRequest):
    """Analiza una URL de Spotify o YouTube y extrae todas las canciones disponibles."""
    url = req.url_or_query.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Por favor ingresa un link o búsqueda")

    try:
        if MusicResolver.is_spotify_url(url):
            loop = asyncio.get_event_loop()

            def ws_progress(loaded: int, total: int):
                asyncio.run_coroutine_threadsafe(
                    broadcast_ws({
                        "event": "analyze_progress",
                        "loaded": loaded,
                        "total": total,
                        "message": f"Cargando canciones... {loaded}/{total}",
                    }),
                    loop,
                )

            await broadcast_ws({
                "event": "analyze_started",
                "message": "Analizando playlist de Spotify...",
            })

            data = await asyncio.to_thread(
                MusicResolver.parse_spotify, url, ws_progress
            )

            if not data.get("tracks"):
                raise HTTPException(
                    status_code=422,
                    detail=data.get("error", "No se pudieron extraer las canciones de Spotify."),
                )

            await broadcast_ws({
                "event": "analyze_done",
                "total": len(data.get("tracks", [])),
            })

            return data

        elif MusicResolver.is_youtube_url(url):
            data = await asyncio.to_thread(MusicResolver.parse_youtube, url, yt_dlp)
            return data
        else:
            return {
                "type": "search",
                "title": "Búsqueda Manual",
                "cover": "",
                "tracks": [{
                    "title": url,
                    "artist": "Búsqueda",
                    "query": url,
                    "duration": "--:--",
                    "cover": "",
                    "source": "manual",
                }],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al analizar el enlace: {str(e)}")


@app.post("/api/download")
async def start_download(req: BatchDownloadRequest):
    """Inicia la descarga de un lote de canciones de forma asíncrona."""
    dl_instance = _get_downloader(req.custom_output_dir)
    asyncio.create_task(run_batch_download(req, dl_instance))
    return {"status": "started", "total_tracks": len(req.tracks)}


@app.post("/api/download-single")
async def download_single(req: SingleDownloadRequest):
    """Descarga una sola canción de forma asíncrona con progreso via WebSocket."""
    dl_instance = _get_downloader(req.custom_output_dir)

    async def _run():
        track_dict = req.track.dict()
        loop = asyncio.get_event_loop()

        await broadcast_ws({
            "event": "single_started",
            "track": track_dict,
        })

        def progress_callback(data):
            asyncio.run_coroutine_threadsafe(
                broadcast_ws({
                    "event": "single_progress",
                    "track_title": req.track.title,
                    "progress": data,
                }),
                loop,
            )

        result = await asyncio.to_thread(
            dl_instance.download_track,
            track_info=track_dict,
            playlist_name=req.playlist_name,
            format_type=req.format,
            quality_mode=req.quality,
            genre_tag=req.genre or "",
            video_mode=getattr(req, "video_mode", "official") or "official",
            progress_hook=progress_callback,
        )

        library_manager.scan_library()

        await broadcast_ws({
            "event": "single_finished",
            "track_title": req.track.title,
            "result": result,
        })

    asyncio.create_task(_run())
    return {"status": "started", "track": req.track.title}


async def run_batch_download(req: BatchDownloadRequest, dl_instance: PelotaDownloader):
    total = len(req.tracks)
    loop = asyncio.get_event_loop()

    await broadcast_ws({
        "event": "batch_started",
        "total": total,
        "playlist": req.playlist_name,
    })

    for index, track in enumerate(req.tracks):
        track_dict = track.dict()

        await broadcast_ws({
            "event": "track_started",
            "index": index,
            "track": track_dict,
        })

        def progress_callback(data, _idx=index):
            asyncio.run_coroutine_threadsafe(
                broadcast_ws({
                    "event": "track_progress",
                    "index": _idx,
                    "progress": data,
                }),
                loop,
            )

        result = await asyncio.to_thread(
            dl_instance.download_track,
            track_info=track_dict,
            playlist_name=req.playlist_name,
            format_type=req.format,
            quality_mode=req.quality,
            genre_tag=req.genre or "",
            video_mode=getattr(req, "video_mode", "official") or "official",
            progress_hook=progress_callback,
        )

        await broadcast_ws({
            "event": "track_finished",
            "index": index,
            "result": result,
        })

    library_manager.scan_library()

    final_folder = os.path.join(
        dl_instance.output_base_dir,
        dl_instance.clean_filename(req.playlist_name),
    )
    await broadcast_ws({
        "event": "batch_completed",
        "playlist": req.playlist_name,
        "folder": final_folder,
    })


@app.post("/api/open-folder")
def open_folder(req: Optional[OpenFolderRequest] = None):
    """Abre la carpeta en el Explorador de Archivos de Windows de forma nativa."""
    folder_path = req.folder_path if req else None
    target = folder_path if folder_path and os.path.exists(folder_path) else downloader.output_base_dir
    target = os.path.normpath(os.path.abspath(target))
    os.makedirs(target, exist_ok=True)
    try:
        os.startfile(target)
    except Exception as e:
        print(f"[Explorer] os.startfile fallback: {e}")
        try:
            subprocess.Popen(["explorer", target])
        except Exception:
            pass
    return {"status": "opened", "path": target}


def _get_downloader(custom_dir: Optional[str]) -> PelotaDownloader:
    if custom_dir and os.path.exists(custom_dir):
        return PelotaDownloader(output_base_dir=custom_dir)
    return downloader


# ── Frontend Estático ─────────────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5555, reload=False)
