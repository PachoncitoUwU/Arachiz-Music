import os
import re
import subprocess
import shutil
from typing import Dict, Any, Optional

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

class AudioStudio:
    """Herramientas de edición ligera de audio: Recorte, Unión con Crossfade y Separación de Stems (Voz/Beat)."""

    def __init__(self, output_dir: str):
        self.output_dir = os.path.abspath(output_dir)
        self.studio_dir = os.path.join(self.output_dir, "Arachiz_Studio")
        os.makedirs(self.studio_dir, exist_ok=True)

    @staticmethod
    def _get_ffmpeg_cmd() -> str:
        cmd = shutil.which("ffmpeg")
        if not cmd:
            # Fallback a static_ffmpeg bin en AppData
            appdata_bin = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Python", "Python311", "Lib", "site-packages", "static_ffmpeg", "bin", "win32", "ffmpeg.EXE")
            if os.path.exists(appdata_bin):
                return appdata_bin
            return "ffmpeg"
        return cmd

    def trim_audio(self, input_path: str, start_sec: float, end_sec: float, title_tag: Optional[str] = None) -> Dict[str, Any]:
        """Recorta un fragmento de audio especificado por segundo inicial y final."""
        if not os.path.exists(input_path):
            return {"success": False, "error": "Archivo original no encontrado"}

        ffmpeg = self._get_ffmpeg_cmd()
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        out_filename = f"{base_name}_recorte_{int(start_sec)}s-{int(end_sec)}s.mp3"
        out_path = os.path.join(self.studio_dir, out_filename)

        duration = max(1.0, end_sec - start_sec)
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start_sec),
            "-i", input_path,
            "-t", str(duration),
            "-acodec", "libmp3lame",
            "-q:a", "2",
            out_path
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return {
                "success": True,
                "output_filename": out_filename,
                "output_path": out_path,
                "duration_seconds": round(duration, 1),
                "message": f"Audio recortado exitosamente: {out_filename}"
            }
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": f"Fallo al recortar audio: {e.stderr}"}

    def merge_with_crossfade(self, track1_path: str, track2_path: str, crossfade_sec: float = 4.0, title: str = "Mashup") -> Dict[str, Any]:
        """Une dos canciones con una transición de crossfade logarítmica profesional."""
        if not os.path.exists(track1_path) or not os.path.exists(track2_path):
            return {"success": False, "error": "Una de las pistas a unir no existe"}

        ffmpeg = self._get_ffmpeg_cmd()
        name1 = os.path.splitext(os.path.basename(track1_path))[0]
        name2 = os.path.splitext(os.path.basename(track2_path))[0]
        out_filename = f"Mashup_{name1[:15]}+{name2[:15]}.mp3"
        out_path = os.path.join(self.studio_dir, out_filename)

        # Filtro acrossfade de FFmpeg
        filter_str = f"[0:a][1:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[aout]"

        cmd = [
            ffmpeg, "-y",
            "-i", track1_path,
            "-i", track2_path,
            "-filter_complex", filter_str,
            "-map", "[aout]",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            out_path
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return {
                "success": True,
                "output_filename": out_filename,
                "output_path": out_path,
                "message": f"Canciones combinadas con éxito con {crossfade_sec}s de crossfade!"
            }
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": f"Error al unir pistas: {e.stderr}"}

    def separate_stems(self, input_path: str, mode: str = "both") -> Dict[str, Any]:
        """
        Separa componentes de audio en Solo Beat (Instrumental) y/o Solo Voz (Acapella).
        Utiliza inversión de fase estéreo (Center Channel Removal) y filtrado espectral con FFmpeg.
        """
        if not os.path.exists(input_path):
            return {"success": False, "error": "Archivo no encontrado"}

        ffmpeg = self._get_ffmpeg_cmd()
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        results = {}

        # 1. Extraer Instrumental / Beat (Cancelación de voz central)
        if mode in ["beat", "both"]:
            beat_filename = f"{base_name}_Solo_Beat_Instrumental.mp3"
            beat_path = os.path.join(self.studio_dir, beat_filename)
            # Filtro: Resta de canales L - R para anular voces en el centro panorámico + refuerzo de graves mono
            filter_beat = "pan=stereo|c0=c0-c1|c1=c1-c0,bass=g=4:f=110"
            cmd_beat = [
                ffmpeg, "-y",
                "-i", input_path,
                "-af", filter_beat,
                "-acodec", "libmp3lame",
                "-q:a", "2",
                beat_path
            ]
            try:
                subprocess.run(cmd_beat, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                results["beat"] = {"filename": beat_filename, "path": beat_path}
            except Exception as e:
                results["beat_error"] = str(e)

        # 2. Extraer Acapella / Solo Voz (Aislamiento de rango vocal y centro)
        if mode in ["vocal", "both"]:
            vocal_filename = f"{base_name}_Solo_Voz_Acapella.mp3"
            vocal_path = os.path.join(self.studio_dir, vocal_filename)
            # Filtro: Suma central + filtro pasabanda de frecuencias vocales (200Hz - 4500Hz)
            filter_vocal = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,highpass=f=200,lowpass=f=4500,volume=1.5"
            cmd_vocal = [
                ffmpeg, "-y",
                "-i", input_path,
                "-af", filter_vocal,
                "-acodec", "libmp3lame",
                "-q:a", "2",
                vocal_path
            ]
            try:
                subprocess.run(cmd_vocal, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                results["vocal"] = {"filename": vocal_filename, "path": vocal_path}
            except Exception as e:
                results["vocal_error"] = str(e)

        return {
            "success": True,
            "stems": results,
            "studio_folder": self.studio_dir,
            "message": "Separación de stems completada exitosamente."
        }
