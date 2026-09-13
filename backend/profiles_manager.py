import os
import json
from typing import List, Dict, Any

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "profiles")
os.makedirs(PROFILES_DIR, exist_ok=True)

DEFAULT_PROFILES = [
    {"id": "default", "name": "Principal", "icon": "fa-user"},
    {"id": "iphone", "name": "Mi iPhone", "icon": "fa-mobile-screen"},
    {"id": "samsung", "name": "Mi Samsung", "icon": "fa-mobile-screen-button"},
]

class ProfilesManager:
    @classmethod
    def get_profiles(cls) -> List[Dict[str, Any]]:
        index_file = os.path.join(PROFILES_DIR, "index.json")
        if os.path.exists(index_file):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        cls.save_profiles(DEFAULT_PROFILES)
        return DEFAULT_PROFILES

    @classmethod
    def save_profiles(cls, profiles: List[Dict[str, Any]]):
        index_file = os.path.join(PROFILES_DIR, "index.json")
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)

    @classmethod
    def get_profile_data(cls, profile_id: str) -> Dict[str, Any]:
        pfile = os.path.join(PROFILES_DIR, f"{profile_id}.json")
        if os.path.exists(pfile):
            try:
                with open(pfile, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Estructura por defecto
        initial = {
            "id": profile_id,
            "favorites": [],
            "playlists": {},
            "history": [],
            "lyrics_offsets": {},
            "offline_cached": []
        }
        cls.save_profile_data(profile_id, initial)
        return initial

    @classmethod
    def save_profile_data(cls, profile_id: str, data: Dict[str, Any]):
        pfile = os.path.join(PROFILES_DIR, f"{profile_id}.json")
        with open(pfile, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data

    @classmethod
    def create_profile(cls, name: str, icon: str = "fa-user") -> Dict[str, Any]:
        profiles = cls.get_profiles()
        new_id = f"p_{len(profiles)+1}_{abs(hash(name))%10000}"
        new_entry = {"id": new_id, "name": name, "icon": icon}
        profiles.append(new_entry)
        cls.save_profiles(profiles)
        cls.get_profile_data(new_id)
        return new_entry
