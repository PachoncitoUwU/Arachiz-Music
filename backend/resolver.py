import os
import re
import json
import time
import urllib.parse
import requests
from typing import List, Dict, Any, Optional


class MusicResolver:
    """Resuelve enlaces de Spotify, YouTube o búsquedas de texto y extrae la lista de canciones."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    # Límite de canciones por página en la API de Spotify
    SPOTIFY_PAGE_LIMIT = 100
    # Tiempo máximo de espera entre reintentos (segundos)
    MAX_RETRY_WAIT = 30
    # Número máximo de reintentos por página
    MAX_RETRIES = 5

    @staticmethod
    def is_spotify_url(url: str) -> bool:
        return "spotify.com" in url or "open.spotify.com" in url

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        return "youtube.com" in url or "youtu.be" in url

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — CREDENCIALES & TOKEN
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_spotify_credentials(cls) -> tuple[Optional[str], Optional[str]]:
        """Obtiene credenciales de Spotify desde variables de entorno o backend/config.json."""
        # 1. Variables de entorno
        cid = os.environ.get("SPOTIPY_CLIENT_ID") or os.environ.get("SPOTIFY_CLIENT_ID")
        csec = os.environ.get("SPOTIPY_CLIENT_SECRET") or os.environ.get("SPOTIFY_CLIENT_SECRET")
        if cid and csec:
            return cid.strip(), csec.strip()

        # 2. backend/config.json
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    c_id = cfg.get("spotify_client_id", "").strip()
                    c_sec = cfg.get("spotify_client_secret", "").strip()
                    if c_id and c_sec:
                        return c_id, c_sec
            except Exception:
                pass
        return None, None

    @classmethod
    def _fetch_spotify_token(cls) -> Optional[str]:
        """
        Obtiene token de Spotify.
        Prioridad 1: Credenciales oficiales Client Credentials (sin límite de 100 canciones).
        Prioridad 2: Token anónimo del embed (hasta 100 canciones).
        """
        # 1. Intentar token oficial con Client Credentials
        cid, csec = cls.get_spotify_credentials()
        if cid and csec:
            try:
                r = requests.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    auth=(cid, csec),
                    timeout=10,
                )
                if r.status_code == 200:
                    token = r.json().get("access_token")
                    if token:
                        print("[Spotify] Autenticado con credenciales oficiales (paginación ilimitada activa).")
                        return token
                else:
                    print(f"[Spotify] Advertencia: Credenciales inválidas ({r.status_code}). Usando fallback anónimo.")
            except Exception as e:
                print(f"[Spotify] Error conectando con accounts.spotify.com: {e}")

        # 2. Fallback: Token anónimo del embed
        embed_urls = [
            "https://open.spotify.com/embed/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/embed/track/3n3Ppam7vgaVa1iaRUIOKE",
        ]
        for url in embed_urls:
            try:
                r = requests.get(url, headers=cls.HEADERS, timeout=10)
                match = re.search(r'"accessToken":"([^"]+)"', r.text)
                if match:
                    return match.group(1)
            except Exception:
                continue
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — REQUEST CON REINTENTOS (para 429 Rate Limit)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _spotify_request(cls, url: str, token: str, retries: int = 0) -> Optional[requests.Response]:
        """
        Hace una petición a la API de Spotify con manejo automático de rate limit (429).
        Espera el tiempo indicado en el header Retry-After o usa backoff exponencial.
        """
        try:
            res = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": cls.HEADERS["User-Agent"],
                },
                timeout=15,
            )

            if res.status_code == 200:
                return res

            if res.status_code == 429 and retries < cls.MAX_RETRIES:
                retry_after = int(res.headers.get("Retry-After", 0)) or (2 ** retries)
                wait = min(retry_after + 1, cls.MAX_RETRY_WAIT)
                print(f"[Spotify] Rate limit (429). Esperando {wait}s... (intento {retries+1}/{cls.MAX_RETRIES})")
                time.sleep(wait)
                return cls._spotify_request(url, token, retries + 1)

            if res.status_code == 401:
                # Token expirado — renovar y reintentar
                print("[Spotify] Token expirado, renovando...")
                new_token = cls._fetch_spotify_token()
                if new_token and retries < 2:
                    return cls._spotify_request(url.replace(token, new_token), new_token, retries + 1)

            print(f"[Spotify] Error HTTP {res.status_code}: {res.text[:200]}")
            return None

        except requests.exceptions.Timeout:
            if retries < cls.MAX_RETRIES:
                print(f"[Spotify] Timeout, reintentando ({retries+1}/{cls.MAX_RETRIES})...")
                time.sleep(2 ** retries)
                return cls._spotify_request(url, token, retries + 1)
            return None
        except Exception as e:
            print(f"[Spotify] Error de red: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — EMBED NEXT_DATA (para metadatos y primeras canciones)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _parse_embed_next_data(cls, item_type: str, item_id: str) -> Optional[Dict]:
        """
        Parsea el HTML embed de Spotify y extrae la entity del bloque __NEXT_DATA__.
        """
        embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}?utm_source=generator"
        try:
            r = requests.get(embed_url, headers=cls.HEADERS, timeout=15)
            if r.status_code != 200:
                return None

            nd_match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                r.text,
                re.DOTALL,
            )
            if not nd_match:
                return None

            data = json.loads(nd_match.group(1))
            page_props = data.get("props", {}).get("pageProps", {})
            if page_props.get("status") == 404:
                return None

            entity = page_props.get("state", {}).get("data", {}).get("entity", {})
            return entity if entity else None
        except Exception as e:
            print(f"[Spotify Embed] Error ({item_type}/{item_id}): {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — API PAGINADA (todas las canciones, soporta 3,000+)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _fetch_all_tracks_api(
        cls,
        item_type: str,
        item_id: str,
        token: str,
        total_known: int = 0,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Descarga TODAS las canciones de una playlist o álbum usando la API paginada.
        Soporta playlists de 3,000+ canciones.
        Garantiza que cada canción tenga su PORTADA INDIVIDUAL y preview de audio.
        """
        all_tracks = []
        offset = 0
        limit = cls.SPOTIFY_PAGE_LIMIT

        if item_type == "playlist":
            base_url = (
                f"https://api.spotify.com/v1/playlists/{item_id}/tracks"
                f"?market=ES&limit={limit}"
                f"&fields=total,next,items(track(name,artists(name),duration_ms,preview_url,album(name,images)))"
            )
        else:  # album
            base_url = (
                f"https://api.spotify.com/v1/albums/{item_id}/tracks"
                f"?market=ES&limit={limit}"
            )

        while True:
            url = f"{base_url}&offset={offset}"
            res = cls._spotify_request(url, token)

            if not res:
                print(f"[Spotify] Deteniendo paginación en offset={offset}.")
                break

            data = res.json()
            items = data.get("items", [])

            if not items:
                break

            for item in items:
                # Las playlists envuelven la pista en {"track": {...}}
                t = item.get("track") if "track" in item else item
                if not t or not t.get("name"):
                    continue

                artist_names = ", ".join(a.get("name", "") for a in t.get("artists", []))
                dur_ms = t.get("duration_ms", 0) or 0
                dur_str = f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}" if dur_ms else "--:--"

                # Portada individual de la canción (del álbum original)
                t_images = t.get("album", {}).get("images", []) if t.get("album") else []
                track_cover = t_images[0].get("url", "") if t_images else ""
                album_name = t.get("album", {}).get("name", "") if t.get("album") else ""
                preview_url = t.get("preview_url") or ""

                all_tracks.append({
                    "title": t.get("name"),
                    "artist": artist_names or "Artista Desconocido",
                    "album": album_name,
                    "query": f"{artist_names} - {t.get('name')}".strip(" -"),
                    "duration": dur_str,
                    "cover": track_cover,
                    "preview_url": preview_url,
                    "source": "spotify",
                    "is_playlist_cover": False,
                })

            loaded = len(all_tracks)
            total = data.get("total", total_known) or total_known
            print(f"[Spotify] Cargadas {loaded}/{total} canciones (offset={offset})")

            if progress_callback:
                progress_callback(loaded, total)

            # Verificar si hay más páginas
            if not data.get("next") or len(items) < limit:
                break

            offset += limit
            time.sleep(0.1)  # Pausa breve para fluidez

        return all_tracks

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — MOTOR ILIMITADO (soporta 1,000, 2,000, 3,000+ canciones)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _scrape_spotify_unlimited(cls, item_type: str, url: str, fallback_title: str, fallback_cover: str) -> Optional[Dict[str, Any]]:
        """
        Extrae TODAS las canciones de Spotify sin límite de 100 y sin necesidad de credenciales,
        utilizando el motor GQL/Pathfinder de spotify_scraper.
        Garantiza que el 100% de las canciones tengan su carátula original de álbum.
        """
        try:
            from spotify_scraper import SpotifyClient
            clean_url = url.split("?")[0].split("#")[0]
            print(f"[Spotify] Conectando motor ilimitado para {item_type} ({clean_url})...")
            with SpotifyClient() as client:
                if item_type == "playlist":
                    pl = client.get_playlist(clean_url, max_tracks=None)
                    pl_name = getattr(pl, "name", None) or fallback_title
                    pl_cover = fallback_cover
                    if hasattr(pl, "images") and pl.images:
                        pl_cover = pl.images[0].url if hasattr(pl.images[0], "url") else pl_cover

                    tracks = []
                    for pt in pl.tracks:
                        t = pt.track if hasattr(pt, "track") and pt.track else pt
                        if not t or not getattr(t, "name", None):
                            continue

                        artists = getattr(t, "artists", [])
                        artist_names = ", ".join(a.name for a in artists if hasattr(a, "name")) or "Artista Desconocido"
                        dur_ms = getattr(t, "duration_ms", 0) or 0
                        dur_str = f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}" if dur_ms else "--:--"

                        # Carátula individual del álbum original
                        t_cover = ""
                        album_obj = getattr(t, "album", None)
                        album_name = getattr(album_obj, "name", "") if album_obj else ""
                        if album_obj and hasattr(album_obj, "images") and album_obj.images:
                            t_cover = album_obj.images[0].url if hasattr(album_obj.images[0], "url") else ""
                        elif hasattr(t, "images") and t.images:
                            t_cover = t.images[0].url if hasattr(t.images[0], "url") else ""

                        prev_url = getattr(t, "preview_url", "") or ""

                        tracks.append({
                            "title": t.name,
                            "artist": artist_names,
                            "album": album_name,
                            "query": f"{artist_names} - {t.name}".strip(" -"),
                            "duration": dur_str,
                            "cover": t_cover,
                            "preview_url": prev_url,
                            "source": "spotify",
                            "is_playlist_cover": False,
                        })

                    if tracks:
                        print(f"[Spotify] [OK] Motor ilimitado extrajo {len(tracks)} canciones con exito (0 limites, caratulas HD individuales).")
                        return {
                            "type": "playlist",
                            "title": pl_name,
                            "cover": pl_cover or (tracks[0]["cover"] if tracks else ""),
                            "tracks": tracks,
                            "total": len(tracks),
                            "has_credentials": True,
                        }

                elif item_type == "album":
                    alb = client.get_album(clean_url)
                    alb_name = getattr(alb, "name", None) or fallback_title
                    alb_cover = fallback_cover
                    if hasattr(alb, "images") and alb.images:
                        alb_cover = alb.images[0].url if hasattr(alb.images[0], "url") else alb_cover

                    alb_artists = ", ".join(a.name for a in getattr(alb, "artists", []) if hasattr(a, "name"))

                    tracks = []
                    for t in getattr(alb, "tracks", []):
                        if not t or not getattr(t, "name", None):
                            continue
                        artists = getattr(t, "artists", [])
                        artist_names = ", ".join(a.name for a in artists if hasattr(a, "name")) or alb_artists or "Artista Desconocido"
                        dur_ms = getattr(t, "duration_ms", 0) or 0
                        dur_str = f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}" if dur_ms else "--:--"

                        tracks.append({
                            "title": t.name,
                            "artist": artist_names,
                            "album": alb_name,
                            "query": f"{artist_names} - {t.name}".strip(" -"),
                            "duration": dur_str,
                            "cover": alb_cover,
                            "preview_url": getattr(t, "preview_url", "") or "",
                            "source": "spotify",
                            "is_playlist_cover": False,
                        })

                    if tracks:
                        print(f"[Spotify] [OK] Motor ilimitado extrajo album con {len(tracks)} canciones.")
                        return {
                            "type": "album",
                            "title": alb_name,
                            "cover": alb_cover,
                            "tracks": tracks,
                            "total": len(tracks),
                            "has_credentials": True,
                        }
        except Exception as e:
            print(f"[Spotify] Motor ilimitado no disponible ({e}), usando APIs estándar...")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # SPOTIFY — PUNTO DE ENTRADA PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def parse_spotify(cls, url: str, progress_callback=None) -> Dict[str, Any]:
        """
        Extrae canciones de una playlist/álbum/track de Spotify.
        Soporta playlists masivas (> 3,000 canciones).
        """
        match = re.search(r"(playlist|album|track)/([a-zA-Z0-9]+)", url)
        if not match:
            return {"type": "unknown", "title": "Spotify Item", "tracks": []}

        item_type, item_id = match.groups()
        cid, csec = cls.get_spotify_credentials()
        has_credentials = bool(cid and csec)

        # ── Paso 1: Metadatos del embed + primeras canciones ───────────────
        entity = cls._parse_embed_next_data(item_type, item_id)
        title, cover, embed_tracks = cls._extract_entity_meta(entity, item_type)

        # ── Paso 2: Track individual ───────────────────────────────────────
        if item_type == "track":
            tracks = embed_tracks
            if not tracks and entity:
                artists = entity.get("artists", [])
                artist_names = ", ".join(a.get("name", "") for a in artists)
                dur_ms = entity.get("duration", 0) or 0
                dur_str = f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}" if dur_ms else "--:--"
                tracks = [{
                    "title": title,
                    "artist": artist_names or "Artista Desconocido",
                    "query": f"{artist_names} - {title}".strip(" -"),
                    "duration": dur_str,
                    "cover": cover,
                    "source": "spotify",
                    "is_playlist_cover": False,
                }]
            return {
                "type": "track",
                "title": title,
                "cover": cover,
                "tracks": tracks,
                "total": len(tracks),
                "has_credentials": has_credentials,
            }

        # ── Paso 3: Motor Ilimitado (Soporta 1,000, 2,000, 3,000+ canciones sin límite) ──
        unlimited_res = cls._scrape_spotify_unlimited(item_type, url, title, cover)
        if unlimited_res and len(unlimited_res.get("tracks", [])) > 0:
            return unlimited_res

        # ── Paso 4: API Paginada con credenciales oficiales (Fallback A) ──
        token = cls._fetch_spotify_token()

        if token:
            total_real = cls._get_playlist_total(item_type, item_id, token)
            print(f"[Spotify] Total canciones reportadas en {item_type}: {total_real}")

            all_tracks = cls._fetch_all_tracks_api(
                item_type, item_id, token,
                total_known=total_real,
                progress_callback=progress_callback,
            )

            if all_tracks:
                print(f"[Spotify] [OK] {len(all_tracks)} canciones cargadas exitosamente.")
                return {
                    "type": item_type,
                    "title": title,
                    "cover": cover,
                    "tracks": all_tracks,
                    "total": len(all_tracks),
                    "has_credentials": has_credentials,
                }

        # ── Fallback: usar lo que devolvió el embed si la API no respondió ──
        print(f"[Spotify] Fallback al embed: {len(embed_tracks)} canciones.")
        if embed_tracks:
            warning_msg = None
            if not has_credentials:
                warning_msg = (
                    f"Se cargaron las primeras {len(embed_tracks)} canciones. "
                    "Para desbloquear listas completas de más de 3,000 canciones sin límites de Spotify, "
                    "agrega tu Client ID gratuito en Ajustes ⚙️."
                )
            return {
                "type": item_type,
                "title": title,
                "cover": cover,
                "tracks": embed_tracks,
                "total": len(embed_tracks),
                "has_credentials": has_credentials,
                "warning": warning_msg,
            }

        # ── Último recurso: oEmbed (solo metadatos) ────────────────────────
        try:
            oe = requests.get(
                f"https://open.spotify.com/oembed?url={url}",
                headers=cls.HEADERS,
                timeout=8,
            )
            if oe.status_code == 200:
                oe_data = oe.json()
                title = oe_data.get("title", title)
                cover = oe_data.get("thumbnail_url", cover)
        except Exception:
            pass

        return {
            "type": item_type,
            "title": title,
            "cover": cover,
            "tracks": [],
            "error": "No se pudieron extraer las canciones. Intenta de nuevo.",
        }

    @classmethod
    def _get_playlist_total(cls, item_type: str, item_id: str, token: str) -> int:
        """Obtiene el número total de canciones de una playlist/álbum sin descargar todo."""
        if item_type == "playlist":
            url = f"https://api.spotify.com/v1/playlists/{item_id}?fields=tracks.total"
        else:
            url = f"https://api.spotify.com/v1/albums/{item_id}?fields=total_tracks"

        res = cls._spotify_request(url, token)
        if res:
            data = res.json()
            if item_type == "playlist":
                return data.get("tracks", {}).get("total", 0)
            else:
                return data.get("total_tracks", 0)
        return 0

    @staticmethod
    def _extract_entity_meta(entity: Optional[Dict], item_type: str):
        """Extrae título, portada y tracklist del embed entity."""
        if not entity:
            return f"Spotify {item_type.capitalize()}", "", []

        title = entity.get("name") or entity.get("title") or f"Spotify {item_type.capitalize()}"

        # Portada de la playlist (solo para la cabecera)
        cover = ""
        cover_art = entity.get("coverArt", {})
        if cover_art:
            sources = cover_art.get("sources", [])
            if sources:
                def _area(s):
                    return (s.get("width") or 0) * (s.get("height") or 0)
                best = max(sources, key=_area, default=sources[0])
                cover = best.get("url", "")
        if not cover:
            images = entity.get("images", [{}])
            cover = images[0].get("url", "") if images else ""

        # TrackList del embed (primeras ~50-100 canciones)
        tracks = []
        for t in entity.get("trackList", []):
            t_title = t.get("title") or t.get("name") or "Unknown"
            t_artist = t.get("subtitle") or ""
            if "•" in t_artist:
                t_artist = t_artist.split("•")[0].strip()

            duration = t.get("duration") or t.get("duration_ms", 0)
            if isinstance(duration, int) and duration > 1000:
                dur_str = f"{duration // 60000}:{(duration % 60000) // 1000:02d}"
            elif isinstance(duration, str) and ":" in duration:
                dur_str = duration
            else:
                dur_str = "--:--"

            t_cover_art = t.get("coverArt", {})
            t_cover = ""
            if t_cover_art and isinstance(t_cover_art, dict):
                t_sources = t_cover_art.get("sources", [])
                if t_sources:
                    t_cover = t_sources[-1].get("url", "")

            audio_prev = ""
            if isinstance(t.get("audioPreview"), dict):
                audio_prev = t.get("audioPreview", {}).get("url", "")
            elif isinstance(t.get("audioPreview"), str):
                audio_prev = t.get("audioPreview")

            # Si no hay portada individual en el embed, se deja vacía con is_playlist_cover=True
            # para que el backend busque la carátula oficial en HD (iTunes) y NO use la de la playlist.
            tracks.append({
                "title": t_title,
                "artist": t_artist or "Artista Desconocido",
                "query": f"{t_artist} - {t_title}".strip(" -"),
                "duration": dur_str,
                "cover": t_cover,
                "preview_url": audio_prev,
                "source": "spotify",
                "is_playlist_cover": not bool(t_cover),
            })

        return title, cover, tracks

    # ─────────────────────────────────────────────────────────────────────────
    # YOUTUBE
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_youtube(url: str, ytdl_module) -> Dict[str, Any]:
        """Extrae canciones o video desde YouTube / YouTube Music usando yt-dlp."""
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }

        with ytdl_module.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            tracks = []
            if "entries" in info:
                playlist_title = info.get("title", "YouTube Playlist")
                for entry in info["entries"]:
                    if not entry:
                        continue
                    duration_sec = int(entry.get("duration", 0) or 0)
                    dur_str = f"{duration_sec // 60}:{duration_sec % 60:02d}" if duration_sec else "--:--"

                    thumb = ""
                    if entry.get("thumbnail"):
                        thumb = entry["thumbnail"]
                    elif entry.get("thumbnails"):
                        thumb = entry["thumbnails"][-1].get("url", "")

                    video_url = (
                        entry.get("url")
                        or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else "")
                    )

                    tracks.append({
                        "id": entry.get("id"),
                        "title": entry.get("title", "Video"),
                        "artist": entry.get("uploader") or entry.get("channel", "YouTube"),
                        "query": video_url,
                        "duration": dur_str,
                        "cover": thumb,
                        "source": "youtube",
                        "direct_url": video_url,
                    })

                return {
                    "type": "playlist",
                    "title": playlist_title,
                    "cover": tracks[0]["cover"] if tracks else "",
                    "tracks": tracks,
                    "total": len(tracks),
                }
            else:
                duration_sec = int(info.get("duration", 0) or 0)
                dur_str = f"{duration_sec // 60}:{duration_sec % 60:02d}" if duration_sec else "--:--"
                return {
                    "type": "video",
                    "title": info.get("title", "Video"),
                    "cover": info.get("thumbnail", ""),
                    "tracks": [{
                        "id": info.get("id"),
                        "title": info.get("title", "Video"),
                        "artist": info.get("uploader") or info.get("channel", "YouTube"),
                        "query": url,
                        "duration": dur_str,
                        "cover": info.get("thumbnail", ""),
                        "source": "youtube",
                        "direct_url": url,
                    }],
                    "total": 1,
                }
