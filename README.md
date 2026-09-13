# Arachiz-Music 🎵 Apple Liquid Glass Sound Studio & Player

Reproductor de música de alta fidelidad con diseño **Apple Liquid Glass**, letras sincronizadas estilo Karaoke, consola DJ interactiva con doble deck (DDJ), soporte multidispositivo, descargas en lote de Spotify y YouTube en alta definición (MP3 320kbps / MP4 1080p), y modo offline completo (PWA + IndexedDB).

## ✨ Características Principales
- **Diseño Apple Liquid Glass Puro**: Rejilla de 4px, esquinas redondeadas de 21px, transparencias con desenfoque de 40px y luces ambientales dinámicas.
- **Letras Sincronizadas (Karaoke)**: Integración con LRCLIB y respaldo con transcripción en vivo por IA (Whisper).
- **Consola DJ Interactiva (DDJ)**: Dos decks independientes con jog wheels para scratching, ecualizador de 3 bandas, pitch fader, beat loops, 8 performance pads SFX y crossfader con auto-mix.
- **Descargador Ilimitado**: Soporta playlists completas de Spotify (+1,000 canciones) y YouTube con metadatos y carátulas individuales oficiales en HD.
- **Soporte para +5,000 canciones**: Renderizado progresivo por fragmentos a 60 FPS sin saturar la memoria ni el DOM.
- **Multidispositivo & Modo Offline**: Acceso vía Wi-Fi local desde iPhone y Android mediante PWA e IndexedDB para escuchar música sin internet.

## 🚀 Inicio Rápido
```bash
pip install -r requirements.txt
python backend/server.py
```
Abre en tu navegador: `http://localhost:5555` o desde tu móvil en tu red local.
