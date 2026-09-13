import re
import random
from typing import List, Dict, Any, Optional

class MoodEngine:
    """Motor de Secuencia Inteligente (Smart Mood Sequence) y Descubrimiento Musical con IA."""

    MOODS = {
        "workout": {
            "name": "⚡ Workout / Alta Energía",
            "keywords": ["gym", "workout", "trap", "reggaeton", "drill", "rap", "rock", "metal", "bass", "remix", "perreo", "alcolirykoz", "trueno", "pirlo", "blessd", "duki", "ysy"],
            "bpm_range": (120, 160),
            "vibe_color": "#0A84FF",
            "adjacent_moods": ["party", "focus"]
        },
        "chill": {
            "name": "☕ Chill / Relax",
            "keywords": ["chill", "lofi", "lo-fi", "acoustic", "r&b", "soul", "indie", "suave", "reggae", "calm", "relax", "sunset", "playa"],
            "bpm_range": (70, 100),
            "vibe_color": "#30D158",
            "adjacent_moods": ["night", "focus"]
        },
        "night": {
            "name": "🌙 Noche / Melancólico",
            "keywords": ["night", "noche", "sad", "slowed", "rain", "melancolia", "desamor", "balada", "dark", "cry", "memories", "luna"],
            "bpm_range": (60, 95),
            "vibe_color": "#5E5CE6",
            "adjacent_moods": ["chill", "focus"]
        },
        "focus": {
            "name": "💻 Focus / Concentración",
            "keywords": ["focus", "study", "instrumental", "ambient", "synthwave", "piano", "beats", "deep", "coding", "flow", "trance"],
            "bpm_range": (85, 115),
            "vibe_color": "#64D2FF",
            "adjacent_moods": ["chill", "night"]
        },
        "party": {
            "name": "🎉 Fiesta / Ritmo Urbano",
            "keywords": ["party", "fiesta", "dance", "disco", "perreo", "reggaeton", "latin", "house", "club", "radio", "hit", "afrobeat", "blessd", "bad bunny", "feid"],
            "bpm_range": (115, 132),
            "vibe_color": "#FF9F0A",
            "adjacent_moods": ["workout", "chill"]
        }
    }

    @classmethod
    def detect_track_mood(cls, track: Dict[str, Any]) -> str:
        """Determina el mood más probable de una canción en función de su título, artista o álbum."""
        text = f"{track.get('title', '')} {track.get('artist', '')} {track.get('album', '')}".lower()
        scores = {mood_key: 0 for mood_key in cls.MOODS}

        for mood_key, mood_data in cls.MOODS.items():
            for kw in mood_data["keywords"]:
                if kw in text:
                    scores[mood_key] += 2

        # Desempate o asignación por defecto
        best_mood = max(scores, key=scores.get)
        if scores[best_mood] == 0:
            # Asignar aleatorio pseudo-estable según hash
            h = hash(text) % len(cls.MOODS)
            return list(cls.MOODS.keys())[h]
        return best_mood

    @classmethod
    def generate_mood_sequence(cls, tracks: List[Dict[str, Any]], target_mood: Optional[str] = None, count: int = 7) -> Dict[str, Any]:
        """
        Genera una secuencia armónica inteligente de 5 a 7 canciones de un mismo mood,
        seguida de una transición al siguiente mood armónico sin saltos bruscos.
        """
        if not tracks:
            return {"sequence": [], "active_mood": "chill", "next_mood": "focus"}

        mood_key = target_mood if target_mood in cls.MOODS else random.choice(list(cls.MOODS.keys()))
        mood_info = cls.MOODS[mood_key]

        # Clasificar todas las canciones
        categorized: Dict[str, List[Dict[str, Any]]] = {m: [] for m in cls.MOODS}
        for t in tracks:
            m = cls.detect_track_mood(t)
            categorized[m].append(t)

        primary_pool = categorized[mood_key]
        if len(primary_pool) < count:
            # Añadir canciones de moods adyacentes si faltan
            for adj in mood_info["adjacent_moods"]:
                for t in categorized[adj]:
                    if t not in primary_pool:
                        primary_pool.append(t)
                    if len(primary_pool) >= count:
                        break
                if len(primary_pool) >= count:
                    break

        # Si aún no alcanza, completar con canciones de la biblioteca
        if len(primary_pool) < count:
            for t in tracks:
                if t not in primary_pool:
                    primary_pool.append(t)
                if len(primary_pool) >= count:
                    break

        # Barajar el pool principal suavemente
        shuffled_primary = list(primary_pool)
        random.shuffle(shuffled_primary)
        sequence = shuffled_primary[:count]

        # Seleccionar pista puente (transición hacia mood adyacente)
        next_mood = random.choice(mood_info["adjacent_moods"])
        bridge_pool = categorized.get(next_mood, [])
        bridge_track = None
        for t in bridge_pool:
            if t not in sequence:
                bridge_track = t
                break

        if bridge_track:
            sequence.append(bridge_track)

        return {
            "active_mood": mood_key,
            "active_mood_name": mood_info["name"],
            "vibe_color": mood_info["vibe_color"],
            "next_mood": next_mood,
            "next_mood_name": cls.MOODS[next_mood]["name"],
            "sequence": sequence,
            "total": len(sequence),
            "description": f"Secuencia de {len(sequence)} canciones calibradas para {mood_info['name']} con modulación suave."
        }

    @classmethod
    def get_discovery_queries(cls, mood_key: str) -> List[str]:
        """Genera sugerencias de búsqueda en internet para descubrir canciones del mood seleccionado."""
        mood_data = cls.MOODS.get(mood_key, cls.MOODS["workout"])
        kw = random.sample(mood_data["keywords"], min(3, len(mood_data["keywords"])))
        return [
            f"top {kw[0]} music playlist 2026",
            f"best {mood_data['name']} songs",
            f"{kw[1]} hits mix",
        ]
