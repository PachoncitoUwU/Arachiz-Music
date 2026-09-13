// ─────────────────────────────────────────────────────────────────────────────
// Arachiz Music v3.0 — Apple Liquid Glass Sound Studio & Player
// ─────────────────────────────────────────────────────────────────────────────

const API_URL = window.location.origin.includes("5555") ? window.location.origin : "http://127.0.0.1:5555";

// ── Estado Global de la Aplicación ──────────────────────────────────────────
let currentView = "player";
let libraryData = { tracks: [], playlists: [], total: 0, artists_count: 0 };
let currentQueue = [];
let queueIndex = -1;
let activeTrack = null;
let isAudioPlaying = false;
let crossfadeDuration = 4; // segundos (0, 2, 4, 6, 8, 12)
let isCrossfading = false;
let currentLyrics = [];
let activeLyricIndex = -1;
let isUserSeeking = false;
let activeMood = "workout";
let activeLibraryFilter = "all";
let checklistItems = [];

// Estado del Descargador
let currentTracks = [];
let filteredTracks = [];
let selectedIndices = new Set();
let selectedFormat = "mp3";
let selectedVideoMode = "audio";
let socket = null;
let downloadStats = { ok: 0, err: 0, total: 0 };

// Dual Audio Elements para Crossfade
let primaryAudio = null;
let secondaryAudio = null;
let activeAudio = null;

// Three.js 3D Vinyl Studio State
let threeScene, threeCamera, threeRenderer, threeVinylGroup, threeParticles;
let isDragging3D = false;
let previousMousePosition = { x: 0, y: 0 };

// ── Inicialización ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initServiceWorker();
  initTheme();
  initAudioEngine();
  initWebSocket();
  initViewNavigation();
  initAmbientParticleBackground();
  initThreeJSVinyl();
  setup3dIpodInteractions();
  setupDownloaderControls();
  setupPlayerControls();
  setupLyricsEngine();
  setupMediaModeSwitch();
  setupLyricsOffsetControls();
  setupDjConsole();
  setupOfflineManager();
  setupProfileManager();
  setupLibraryView();
  setupMoodStudio();
  setupAudioStudio();
  setupChecklistView();
  setupMobileModal();

  // Iniciar en vista Reproductor
  switchView("player");

  // Cargar datos iniciales
  loadAppConfig();
  loadLibrary();
  loadChecklist();
});

// ── Service Worker (PWA Offline) ──────────────────────────────────────────────
function initServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

// ── Tema Claro / Oscuro Apple ─────────────────────────────────────────────────
function initTheme() {
  const savedTheme = localStorage.getItem("arachiz_theme") || "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);
  updateThemeIcon(savedTheme);

  const btnTheme = document.getElementById("btnThemeToggle");
  if (btnTheme) {
    btnTheme.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "dark";
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("arachiz_theme", next);
      updateThemeIcon(next);
    });
  }
}

function updateThemeIcon(theme) {
  const btn = document.getElementById("btnThemeToggle");
  if (btn) {
    btn.innerHTML = theme === "dark" ? `<i class="fa-solid fa-sun"></i>` : `<i class="fa-solid fa-moon"></i>`;
  }
}

// ── Motor de Audio Dual con Crossfade Logarítmico (Web Audio Style) ───────────
function initAudioEngine() {
  primaryAudio = document.getElementById("primaryAudioElement");
  secondaryAudio = document.getElementById("secondaryAudioElement");
  activeAudio = primaryAudio;

  if (primaryAudio) {
    primaryAudio.volume = 0.9;
    setupAudioListeners(primaryAudio);
  }
  if (secondaryAudio) {
    secondaryAudio.volume = 0.9;
    setupAudioListeners(secondaryAudio);
  }

  // Crossfade Select
  const crossfadeSelect = document.getElementById("crossfadeSelect");
  if (crossfadeSelect) {
    crossfadeSelect.addEventListener("change", (e) => {
      crossfadeDuration = parseInt(e.target.value) || 0;
      updateCrossfadeBadges();
    });
  }
  updateCrossfadeBadges();
}

function updateCrossfadeBadges() {
  const pbarBadge = document.getElementById("pbarCrossfadeBadge");
  if (pbarBadge) {
    pbarBadge.textContent = crossfadeDuration > 0 ? `X-Fade ${crossfadeDuration}s` : "Sin X-Fade";
  }
}

function setupAudioListeners(audioEl) {
  audioEl.addEventListener("timeupdate", () => {
    if (audioEl !== activeAudio) return;
    if (audioEl.duration && !isUserSeeking) {
      const cur = audioEl.currentTime;
      const dur = audioEl.duration;
      const pct = (cur / dur) * 100;

      // Actualizar barras de progreso
      updateProgressBars(cur, dur, pct);

      // Sincronizar letra en tiempo real
      syncLyricsWithTime(cur);

      // Detectar momento de Crossfade
      if (crossfadeDuration > 0 && !isCrossfading && cur >= (dur - crossfadeDuration - 0.5) && dur > 10) {
        triggerCrossfadeToNext();
      }
    }
  });

  audioEl.addEventListener("ended", () => {
    if (audioEl === activeAudio && !isCrossfading) {
      playNextTrack(false);
    }
  });

  audioEl.addEventListener("play", () => {
    if (audioEl === activeAudio) {
      setPlayPauseUI(true);
    }
  });

  audioEl.addEventListener("pause", () => {
    if (audioEl === activeAudio && !isCrossfading) {
      setPlayPauseUI(false);
    }
  });
}

function updateProgressBars(cur, dur, pct) {
  // Main Player
  const mainFill = document.getElementById("mainTimelineFill");
  const mainThumb = document.getElementById("mainTimelineThumb");
  const mainCur = document.getElementById("mainPlayerCurTime");
  const mainDur = document.getElementById("mainPlayerDuration");
  if (mainFill) mainFill.style.width = `${pct}%`;
  if (mainThumb) mainThumb.style.left = `${pct}%`;
  if (mainCur) mainCur.textContent = formatTime(cur);
  if (mainDur) mainDur.textContent = formatTime(dur);

  // Persistent Player Bar
  const pbarFill = document.getElementById("pbarSliderFill");
  const pbarCur = document.getElementById("pbarCurTime");
  const pbarTotal = document.getElementById("pbarTotalTime");
  if (pbarFill) pbarFill.style.width = `${pct}%`;
  if (pbarCur) pbarCur.textContent = formatTime(cur);
  if (pbarTotal) pbarTotal.textContent = formatTime(dur);

  // iPod Screen
  const ipodFill = document.getElementById("ipodTimelineFill");
  if (ipodFill) ipodFill.style.width = `${pct}%`;
}

// ── Reproducción de Pista ─────────────────────────────────────────────────────
function playTrack(track, fromQueueIndex = -1, immediate = true) {
  if (!track) return;
  activeTrack = track;
  if (fromQueueIndex >= 0) {
    queueIndex = fromQueueIndex;
  }

  // Activar barra inferior persistente
  document.body.classList.add("player-dock-active");

  const streamUrl = track.stream_url || (track.id ? `${API_URL}/api/stream/${track.id}` : track.preview_url);

  // Switch de audio element si es crossfade
  if (isCrossfading) {
    // Ya está en marcha
  } else {
    activeAudio.src = streamUrl;
    if (immediate) {
      activeAudio.play().catch(() => {});
      isAudioPlaying = true;
    }
  }

  // Actualizar UI en todas las vistas
  updateNowPlayingUI(track);

  // Buscar letras en LRCLIB / local
  fetchAndDisplayLyrics(track);

  // Buscar y preparar video oficial HD o carátula
  fetchAndDisplayVideo(track);

  // Adaptar colores dinámicos al cover
  adaptAmbientGlow(track.cover_url);

  // MediaSession API para pantalla de bloqueo en iPhone y Samsung
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: track.artist,
      album: track.album || "Arachiz Music",
      artwork: track.cover_url ? [{ src: track.cover_url, sizes: "512x512", type: "image/jpeg" }] : []
    });

    navigator.mediaSession.setActionHandler("play", toggleMainPlayPause);
    navigator.mediaSession.setActionHandler("pause", toggleMainPlayPause);
    navigator.mediaSession.setActionHandler("previoustrack", playPreviousTrack);
    navigator.mediaSession.setActionHandler("nexttrack", playNextTrack);
  }
}

function toggleMainPlayPause() {
  if (!activeAudio || !activeAudio.src) {
    if (libraryData.tracks.length > 0) {
      playTrack(libraryData.tracks[0], 0);
    }
    return;
  }

  if (activeAudio.paused) {
    activeAudio.play().catch(() => {});
    isAudioPlaying = true;
    setPlayPauseUI(true);
  } else {
    activeAudio.pause();
    isAudioPlaying = false;
    setPlayPauseUI(false);
  }
}

function setPlayPauseUI(playing) {
  isAudioPlaying = playing;

  // Botón Main Player
  const btnHero = document.getElementById("btnPlayerMainPlay");
  if (btnHero) btnHero.innerHTML = playing ? `<i class="fa-solid fa-pause"></i>` : `<i class="fa-solid fa-play"></i>`;

  // Botón Persistent Player Bar
  const btnPbar = document.getElementById("pbarBtnPlayPause");
  if (btnPbar) btnPbar.innerHTML = playing ? `<i class="fa-solid fa-pause"></i>` : `<i class="fa-solid fa-play"></i>`;

  // Botón iPod
  const ipodStatus = document.getElementById("ipodPlayStatus");
  if (ipodStatus) ipodStatus.innerHTML = playing ? `<i class="fa-solid fa-play"></i>` : `<i class="fa-solid fa-pause"></i>`;

  // Dot en Nav
  const dot = document.getElementById("playerPlayingDot");
  if (dot) dot.classList.toggle("hidden", !playing);
}

function playNextTrack(userTriggered = true) {
  if (currentQueue.length === 0 && libraryData.tracks.length > 0) {
    currentQueue = [...libraryData.tracks];
  }
  if (currentQueue.length === 0) return;

  let nextIdx = queueIndex + 1;
  if (nextIdx >= currentQueue.length) nextIdx = 0;
  playTrack(currentQueue[nextIdx], nextIdx, true);
}

function playPreviousTrack() {
  if (currentQueue.length === 0 && libraryData.tracks.length > 0) {
    currentQueue = [...libraryData.tracks];
  }
  if (currentQueue.length === 0) return;

  let prevIdx = queueIndex - 1;
  if (prevIdx < 0) prevIdx = currentQueue.length - 1;
  playTrack(currentQueue[prevIdx], prevIdx, true);
}

// ── Crossfade Suave entre Canciones ───────────────────────────────────────────
function triggerCrossfadeToNext() {
  if (isCrossfading || crossfadeDuration <= 0) return;
  if (currentQueue.length === 0) return;

  let nextIdx = queueIndex + 1;
  if (nextIdx >= currentQueue.length) nextIdx = 0;
  const nextTrack = currentQueue[nextIdx];
  if (!nextTrack) return;

  isCrossfading = true;
  const outgoingAudio = activeAudio;
  const incomingAudio = activeAudio === primaryAudio ? secondaryAudio : primaryAudio;

  const streamUrl = nextTrack.stream_url || `${API_URL}/api/stream/${nextTrack.id}`;
  incomingAudio.src = streamUrl;
  incomingAudio.volume = 0.0;
  incomingAudio.play().catch(() => {});

  const steps = 20;
  const stepTime = (crossfadeDuration * 1000) / steps;
  let currentStep = 0;
  const targetVolume = 0.9;

  const fadeInterval = setInterval(() => {
    currentStep++;
    const factor = currentStep / steps;

    // Curva logarítmica / igual poder
    incomingAudio.volume = Math.min(targetVolume, targetVolume * Math.sin((factor * Math.PI) / 2));
    outgoingAudio.volume = Math.max(0.0, targetVolume * Math.cos((factor * Math.PI) / 2));

    if (currentStep >= steps) {
      clearInterval(fadeInterval);
      outgoingAudio.pause();
      outgoingAudio.currentTime = 0;
      activeAudio = incomingAudio;
      isCrossfading = false;
      queueIndex = nextIdx;
      activeTrack = nextTrack;
      updateNowPlayingUI(nextTrack);
      fetchAndDisplayLyrics(nextTrack);
      adaptAmbientGlow(nextTrack.cover_url);
    }
  }, stepTime);
}

// ── Actualización de UI Now Playing ───────────────────────────────────────────
function updateNowPlayingUI(track) {
  const coverSrc = getTrackCoverSrc(track);

  // Main Player
  const mainCover = document.getElementById("mainPlayerCover");
  const mainTitle = document.getElementById("mainPlayerTitle");
  const mainArtist = document.getElementById("mainPlayerArtist");
  const mainAlbum = document.getElementById("mainPlayerAlbum");
  const mainFmt = document.getElementById("mainPlayerFormatBadge");

  if (mainCover) mainCover.src = coverSrc;
  if (mainTitle) mainTitle.textContent = track.title || "Sin título";
  if (mainArtist) mainArtist.textContent = track.artist || "Desconocido";
  if (mainAlbum) mainAlbum.textContent = track.album || track.playlist || "Biblioteca";
  if (mainFmt) mainFmt.textContent = (track.format || "MP3").toUpperCase() + " HD";

  // Persistent Player Bar
  const pbarCover = document.getElementById("pbarCover");
  const pbarTitle = document.getElementById("pbarTitle");
  const pbarArtist = document.getElementById("pbarArtist");
  if (pbarCover) pbarCover.src = coverSrc;
  if (pbarTitle) pbarTitle.textContent = track.title || "Sin título";
  if (pbarArtist) pbarArtist.textContent = track.artist || "Desconocido";

  // iPod 3D
  const ipodArt = document.getElementById("ipodAlbumArt");
  const ipodTitle = document.getElementById("ipodSongTitle");
  const ipodArtist = document.getElementById("ipodArtistName");
  if (ipodArt) ipodArt.src = coverSrc;
  if (ipodTitle) ipodTitle.textContent = track.title || "Sin título";
  if (ipodArtist) ipodArtist.textContent = track.artist || "Desconocido";

  // Marcar fila activa en Biblioteca
  document.querySelectorAll(".lib-track-row").forEach((row) => {
    row.classList.toggle("playing", row.dataset.id === track.id);
  });
}

// ── Adaptación de Colores Dinámicos Líquidos al Cover ─────────────────────────
function adaptAmbientGlow(coverUrl) {
  if (!coverUrl) return;
  const glow1 = document.getElementById("ambientGlow1");
  const glow2 = document.getElementById("ambientGlow2");
  if (!glow1 || !glow2) return;

  const img = new Image();
  img.crossOrigin = "anonymous";
  // Ensure relative cover URLs get the full origin prefix for cross-origin canvas access
  const fullUrl = coverUrl.startsWith("/") ? `${API_URL}${coverUrl}` : coverUrl;
  img.src = fullUrl;
  img.onload = () => {
    try {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      canvas.width = 16;
      canvas.height = 16;
      ctx.drawImage(img, 0, 0, 16, 16);
      const data = ctx.getImageData(0, 0, 16, 16).data;
      let r = 0, g = 0, b = 0, count = 0;
      for (let i = 0; i < data.length; i += 4) {
        const brightness = (data[i] + data[i + 1] + data[i + 2]) / 3;
        if (brightness > 30 && brightness < 230) {
          r += data[i];
          g += data[i + 1];
          b += data[i + 2];
          count++;
        }
      }
      if (count > 0) {
        r = Math.round(r / count);
        g = Math.round(g / count);
        b = Math.round(b / count);
        glow1.style.background = `radial-gradient(circle, rgba(${r}, ${g}, ${b}, 0.28) 0%, transparent 70%)`;
        glow2.style.background = `radial-gradient(circle, rgba(${Math.min(255, r + 40)}, ${g}, ${Math.max(0, b - 20)}, 0.20) 0%, transparent 70%)`;
      }
    } catch (e) {}
  };
}

// ── Motor de Letras Sincronizadas (Karaoke Apple Music) ───────────────────────
function setupLyricsEngine() {
  const btnAi = document.getElementById("btnAiTranscribe");
  if (btnAi) {
    btnAi.addEventListener("click", async () => {
      if (!activeTrack || !activeTrack.id) {
        showError("Aviso", "Reproduce una canción de tu biblioteca para transcribir su letra con IA.");
        return;
      }
      btnAi.disabled = true;
      btnAi.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Transcribiendo con IA...`;
      try {
        const res = await fetch(`${API_URL}/api/lyrics/transcribe`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track_id: activeTrack.id }),
        });
        const data = await res.json();
        if (data.success && data.lines && data.lines.length > 0) {
          renderLyricsLines(data.lines);
          showToast("¡Letra Generada!", "La IA transcribió los versos y guardó el archivo .lrc sincronizado.");
        } else {
          showError("Transcripción IA", data.error || "No se pudo transcribir el audio.");
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnAi.disabled = false;
        btnAi.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Transcribir con IA`;
      }
    });
  }

  const btnCopy = document.getElementById("btnCopyLyrics");
  if (btnCopy) {
    btnCopy.addEventListener("click", () => {
      if (currentLyrics.length === 0) return;
      const text = currentLyrics.map((l) => l.text).join("\n");
      navigator.clipboard.writeText(text);
      showToast("Copiado", "Letra copiada al portapapeles.");
    });
  }
}

async function fetchAndDisplayLyrics(track) {
  const placeholder = document.getElementById("lyricsPlaceholder");
  const flow = document.getElementById("lyricsLinesFlow");
  const badge = document.getElementById("lyricsStatusBadge");

  if (placeholder) placeholder.classList.remove("hidden");
  if (flow) flow.classList.add("hidden");
  if (badge) badge.textContent = "Buscando...";

  try {
    const params = new URLSearchParams({
      title: track.title || "",
      artist: track.artist || "",
      track_id: track.id || "",
    });
    const res = await fetch(`${API_URL}/api/lyrics?${params}`);
    if (res.ok) {
      const data = await res.json();
      if (data.lines && data.lines.length > 0) {
        currentLyrics = data.lines;
        renderLyricsLines(data.lines);
        if (badge) {
          badge.textContent = data.synced ? "Sincronizada" : "Texto Plano";
          badge.style.color = data.synced ? "#30D158" : "#FF9F0A";
        }
        return;
      }
    }
  } catch (e) {}

  currentLyrics = [];
  if (placeholder) {
    placeholder.innerHTML = `
      <div class="lyrics-spin-pulse"><i class="fa-solid fa-microphone-slash"></i></div>
      <h3>Sin letra disponible en línea</h3>
      <p>Haz clic en "Transcribir con IA" para que Whisper escuche la canción y cree la letra automáticamente.</p>
    `;
    placeholder.classList.remove("hidden");
  }
  if (flow) flow.classList.add("hidden");
  if (badge) badge.textContent = "No encontrada";
}

function renderLyricsLines(lines) {
  const placeholder = document.getElementById("lyricsPlaceholder");
  const flow = document.getElementById("lyricsLinesFlow");
  if (!flow) return;

  flow.innerHTML = "";
  lines.forEach((line, index) => {
    const div = document.createElement("div");
    div.className = "lyric-line-item";
    div.dataset.index = index;
    div.dataset.time = line.time;
    div.textContent = line.text;

    // Click-to-seek: tocar cualquier línea salta al segundo exacto
    div.addEventListener("click", () => {
      if (activeAudio) {
        activeAudio.currentTime = line.time;
        if (activeAudio.paused) activeAudio.play().catch(() => {});
      }
    });

    flow.appendChild(div);
  });

  if (placeholder) placeholder.classList.add("hidden");
  flow.classList.remove("hidden");
}

function syncLyricsWithTime(currentTime) {
  if (currentLyrics.length === 0) return;
  const flow = document.getElementById("lyricsLinesFlow");
  if (!flow) return;

  const adjustedTime = Math.max(0, currentTime + (trackLyricsOffset || 0));

  let bestIdx = -1;
  for (let i = 0; i < currentLyrics.length; i++) {
    if (adjustedTime >= currentLyrics[i].time) {
      bestIdx = i;
    } else {
      break;
    }
  }

  if (bestIdx !== activeLyricIndex) {
    activeLyricIndex = bestIdx;
    const allLines = flow.querySelectorAll(".lyric-line-item");
    allLines.forEach((el, idx) => {
      el.classList.toggle("active-lyric", idx === bestIdx);
    });

    // Auto-scroll suave centrado en la línea activa
    if (bestIdx >= 0 && allLines[bestIdx]) {
      allLines[bestIdx].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
}

// ── VISTA 3: MI BIBLIOTECA ──────────────────────────────────────────────────
function setupLibraryView() {
  const btnRefresh = document.getElementById("btnRefreshLibrary");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => loadLibrary(true));
  }

  const btnOpenDir = document.getElementById("btnOpenFolderFromLib");
  if (btnOpenDir) {
    btnOpenDir.addEventListener("click", openDownloadFolder);
  }

  const btnOpenDownloads = document.getElementById("btnOpenDownloads");
  if (btnOpenDownloads) {
    btnOpenDownloads.addEventListener("click", openDownloadFolder);
  }

  const searchInput = document.getElementById("libSearchInput");
  const clearBtn = document.getElementById("btnClearLibSearch");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      const q = searchInput.value.trim().toLowerCase();
      if (clearBtn) clearBtn.classList.toggle("hidden", !q);
      renderLibraryTracks(q);
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      searchInput.value = "";
      clearBtn.classList.add("hidden");
      renderLibraryTracks("");
    });
  }
}

async function openDownloadFolder() {
  try {
    const res = await fetch(`${API_URL}/api/open-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      const data = await res.json();
      const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
      if (isMobile) {
        showToast("Carpeta Abierta en tu PC", `Se abrió en la PC: ${data.path}. En este celular tus canciones se guardan con el botón 'Guardar en Celular (Offline)'.`);
      } else {
        showToast("Explorador Abierto", `Carpeta abierta en tu PC: ${data.path || "Descargas"}`);
      }
    } else {
      showError("Aviso", "No se pudo abrir la carpeta en Windows.");
    }
  } catch (err) {
    showError("Error", err.message);
  }
}

async function loadLibrary(showFeedback = false) {
  const btnRefresh = document.getElementById("btnRefreshLibrary");
  if (btnRefresh && showFeedback) {
    btnRefresh.innerHTML = `<i class="fa-solid fa-arrows-rotate fa-spin"></i> Actualizando...`;
    btnRefresh.disabled = true;
  }

  try {
    const res = await fetch(`${API_URL}/api/library`);
    if (res.ok) {
      libraryData = await res.json();
      updateLibraryStats();
      renderLibraryChips();
      renderLibraryTracks();
      populateStudioSelects();

      // Notificar a la Consola DJ y otros módulos
      window.dispatchEvent(new CustomEvent("arachiz_library_loaded"));

      if (showFeedback) {
        showToast("Biblioteca Actualizada", `${libraryData.total || 0} canciones encontradas.`);
      }
    }
  } catch (err) {
    console.error("Error al cargar biblioteca:", err);
    if (showFeedback) showError("Error", "No se pudo actualizar la biblioteca.");
  } finally {
    if (btnRefresh) {
      btnRefresh.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> Actualizar`;
      btnRefresh.disabled = false;
    }
  }
}



function updateLibraryStats() {
  const statTotal = document.getElementById("libStatTotalTracks");
  const statPlaylists = document.getElementById("libStatPlaylists");
  const statArtists = document.getElementById("libStatArtists");
  const statSize = document.getElementById("libStatStorage");
  const navCount = document.getElementById("navLibraryCount");
  const dashCount = document.getElementById("dashLibCount");

  const total = libraryData.total || 0;
  if (statTotal) statTotal.textContent = total;
  if (navCount) navCount.textContent = total;
  if (dashCount) dashCount.textContent = total;
  if (statPlaylists) statPlaylists.textContent = (libraryData.playlists || []).length;
  if (statArtists) statArtists.textContent = libraryData.artists_count || 0;

  if (statSize && libraryData.tracks) {
    const bytes = libraryData.tracks.reduce((acc, t) => acc + (t.size_bytes || 0), 0);
    statSize.textContent = `${Math.round(bytes / (1024 * 1024))} MB`;
  }
}

function renderLibraryChips() {
  const container = document.getElementById("libPlaylistChips");
  if (!container) return;

  container.innerHTML = `<button class="lib-chip active" data-folder="all">Todas las Canciones</button>`;
  (libraryData.playlists || []).forEach((p) => {
    const btn = document.createElement("button");
    btn.className = "lib-chip";
    btn.dataset.folder = p.name;
    btn.textContent = `${p.name} (${p.count})`;
    btn.addEventListener("click", () => {
      container.querySelectorAll(".lib-chip").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      activeLibraryFilter = p.name;
      renderLibraryTracks();
    });
    container.appendChild(btn);
  });

  const allBtn = container.querySelector('[data-folder="all"]');
  if (allBtn) {
    allBtn.addEventListener("click", () => {
      container.querySelectorAll(".lib-chip").forEach((c) => c.classList.remove("active"));
      allBtn.classList.add("active");
      activeLibraryFilter = "all";
      renderLibraryTracks();
    });
  }
}

let libChunkRenderCount = 60;
let lastLibraryTracksList = [];

function renderLibraryTracks(query = "", appendNextChunk = false) {
  const container = document.getElementById("libTracksList");
  if (!container) return;

  if (!appendNextChunk) {
    libChunkRenderCount = 60;
    let tracks = libraryData.tracks || [];
    if (activeLibraryFilter !== "all") {
      tracks = tracks.filter((t) => t.playlist === activeLibraryFilter);
    }
    if (query) {
      const q = query.toLowerCase();
      tracks = tracks.filter(
        (t) =>
          (t.title || "").toLowerCase().includes(q) ||
          (t.artist || "").toLowerCase().includes(q) ||
          (t.album || "").toLowerCase().includes(q)
      );
    }
    lastLibraryTracksList = tracks;
    container.innerHTML = "";
  } else {
    // Eliminar botón anterior si existe
    const oldMoreBtn = document.getElementById("btnLibLoadMoreChunk");
    if (oldMoreBtn) oldMoreBtn.remove();
  }

  const tracks = lastLibraryTracksList;

  if (tracks.length === 0) {
    container.innerHTML = `
      <div class="lib-empty-notice">
        <i class="fa-solid fa-music"></i>
        <p>No se encontraron canciones en esta carpeta.</p>
      </div>
    `;
    return;
  }

  const startIndex = appendNextChunk ? libChunkRenderCount - 60 : 0;
  const slice = tracks.slice(startIndex, libChunkRenderCount);

  const frag = document.createDocumentFragment();
  slice.forEach((track, localIdx) => {
    const idx = startIndex + localIdx;
    const row = document.createElement("div");
    row.className = "lib-track-row";
    row.dataset.id = track.id;
    if (activeTrack && activeTrack.id === track.id) {
      row.classList.add("playing");
    }

    const coverSrc = getTrackCoverSrc(track);

    row.innerHTML = `
      <div class="col-index">
        <button class="btn-play-mini-row" title="Reproducir"><i class="fa-solid fa-play"></i></button>
      </div>
      <div class="col-title lib-track-cell-title">
        <img src="${coverSrc}" class="lib-track-mini-thumb" alt="Cover" loading="lazy" />
        <span>${escapeHtml(track.title)}</span>
      </div>
      <div class="col-artist">${escapeHtml(track.artist)}</div>
      <div class="col-album">${escapeHtml(track.album || track.playlist)}</div>
      <div class="col-duration tabular">${track.duration}</div>
      <div class="col-actions">
        <button class="btn-pill-micro btn-lib-play" title="Reproducir ahora"><i class="fa-solid fa-play"></i></button>
        <button class="btn-pill-micro btn-lib-lyrics" title="Ver letra"><i class="fa-solid fa-quote-left"></i></button>
      </div>
    `;

    // Reproducir al hacer clic en la fila o botón play
    row.querySelector(".btn-play-mini-row").addEventListener("click", (e) => {
      e.stopPropagation();
      currentQueue = tracks;
      playTrack(track, idx);
    });
    row.querySelector(".btn-lib-play").addEventListener("click", (e) => {
      e.stopPropagation();
      currentQueue = tracks;
      playTrack(track, idx);
    });
    row.querySelector(".btn-lib-lyrics").addEventListener("click", (e) => {
      e.stopPropagation();
      currentQueue = tracks;
      playTrack(track, idx);
      switchView("player");
    });
    row.addEventListener("dblclick", () => {
      currentQueue = tracks;
      playTrack(track, idx);
    });

    frag.appendChild(row);
  });

  container.appendChild(frag);

  // Si hay más canciones de las 60 mostradas, agregar botón de carga progresiva
  if (tracks.length > libChunkRenderCount) {
    const remaining = tracks.length - libChunkRenderCount;
    const moreBtnWrap = document.createElement("div");
    moreBtnWrap.id = "btnLibLoadMoreChunk";
    moreBtnWrap.className = "load-more-section";
    moreBtnWrap.style.cssText = "padding: 20px; text-align: center; width: 100%;";
    moreBtnWrap.innerHTML = `
      <button class="btn-pill-secondary" style="margin: 0 auto; padding: 10px 24px;">
        <i class="fa-solid fa-angles-down"></i> 
        <span>Cargar más canciones (${Math.min(remaining, 60)} restantes de ${remaining})</span>
      </button>
      <div style="font-size: 11px; opacity: 0.6; margin-top: 6px;">
        Mostrando ${libChunkRenderCount} de ${tracks.length} pistas • Rendimiento 60fps activo
      </div>
    `;
    moreBtnWrap.querySelector("button").addEventListener("click", () => {
      libChunkRenderCount += 60;
      renderLibraryTracks(query, true);
    });
    container.appendChild(moreBtnWrap);
  }
}

// ── VISTA 4: IA MOOD STUDIO ─────────────────────────────────────────────────
function setupMoodStudio() {
  const pillsContainer = document.getElementById("moodPillsContainer");
  if (pillsContainer) {
    pillsContainer.addEventListener("click", (e) => {
      const pill = e.target.closest(".mood-pill");
      if (pill) {
        pillsContainer.querySelectorAll(".mood-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        activeMood = pill.dataset.mood;
      }
    });
  }

  const btnGenerate = document.getElementById("btnGenerateMoodSequence");
  if (btnGenerate) {
    btnGenerate.addEventListener("click", async () => {
      btnGenerate.disabled = true;
      btnGenerate.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Generando Secuencia...`;
      try {
        const res = await fetch(`${API_URL}/api/mood/sequence?mood=${activeMood}&count=7`);
        if (res.ok) {
          const data = await res.json();
          renderMoodSequence(data);
          showToast("Secuencia Lista", `${data.total} canciones preparadas para tu estado de ánimo.`);
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnGenerate.disabled = false;
        btnGenerate.innerHTML = `<i class="fa-solid fa-play"></i> <span>Generar Secuencia Armónica (5-7 Canciones)</span>`;
      }
    });
  }

  const btnDiscover = document.getElementById("btnTriggerDiscover");
  const discoverInput = document.getElementById("discoverPromptInput");
  if (btnDiscover) {
    btnDiscover.addEventListener("click", async () => {
      const prompt = discoverInput ? discoverInput.value.trim() : "";
      btnDiscover.disabled = true;
      btnDiscover.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Buscando en internet...`;
      try {
        const params = new URLSearchParams({ mood: activeMood });
        if (prompt) params.append("query", prompt);
        const res = await fetch(`${API_URL}/api/mood/discover?${params}`);
        if (res.ok) {
          const data = await res.json();
          renderDiscoverResults(data.tracks || []);
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnDiscover.disabled = false;
        btnDiscover.innerHTML = `<i class="fa-solid fa-bolt"></i> Descubrir con IA`;
      }
    });
  }
}

function renderMoodSequence(seqData) {
  const container = document.getElementById("moodSeqGrid");
  const title = document.getElementById("moodSeqTitle");
  const badge = document.getElementById("moodSeqBadge");
  const btnPlayAll = document.getElementById("btnPlayAllMoodSeq");

  if (title) title.textContent = `Secuencia: ${seqData.active_mood_name}`;
  if (badge) badge.textContent = `Próximo: ${seqData.next_mood_name}`;
  if (!container) return;

  container.innerHTML = "";
  const tracks = seqData.sequence || [];

  tracks.forEach((t, i) => {
    const isBridge = i === tracks.length - 1;
    const card = document.createElement("div");
    card.className = "mood-seq-card";
    const coverSrc = t.cover_url || "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=100";

    card.innerHTML = `
      <img src="${coverSrc}" class="mood-seq-thumb" alt="Cover" />
      <div class="mood-seq-meta">
        <div class="mood-seq-title">${escapeHtml(t.title)}</div>
        <div class="mood-seq-artist">${escapeHtml(t.artist)}</div>
      </div>
      ${isBridge ? `<span class="mood-seq-bridge-badge">Puente</span>` : ""}
    `;

    card.addEventListener("click", () => {
      currentQueue = tracks;
      playTrack(t, i);
    });

    container.appendChild(card);
  });

  if (btnPlayAll) {
    btnPlayAll.onclick = () => {
      if (tracks.length > 0) {
        currentQueue = tracks;
        playTrack(tracks[0], 0);
        switchView("player");
      }
    };
  }
}

function renderDiscoverResults(tracks) {
  const container = document.getElementById("discoverResultsGrid");
  if (!container) return;
  container.innerHTML = "";

  if (tracks.length === 0) {
    container.innerHTML = `<p style="color:var(--text-secondary);grid-column:1/-1;">No se encontraron canciones adicionales en internet.</p>`;
    return;
  }

  tracks.forEach((t) => {
    const card = document.createElement("div");
    card.className = "mood-seq-card";
    const coverSrc = t.cover || "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=100";

    card.innerHTML = `
      <img src="${coverSrc}" class="mood-seq-thumb" alt="Cover" />
      <div class="mood-seq-meta">
        <div class="mood-seq-title">${escapeHtml(t.title)}</div>
        <div class="mood-seq-artist">${escapeHtml(t.artist)}</div>
      </div>
      <button class="btn-pill-micro btn-discover-dl" title="Descargar en 1-click"><i class="fa-solid fa-download"></i></button>
    `;

    card.querySelector(".btn-discover-dl").addEventListener("click", async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
      try {
        const res = await fetch(`${API_URL}/api/download-single`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            track: t,
            playlist_name: "Descubrimientos_IA",
            format: "mp3",
            quality: "balanced",
          }),
        });
        if (res.ok) {
          showToast("Descargando", `Añadiendo ${t.title} a tu biblioteca.`);
          btn.innerHTML = `✓`;
        }
      } catch (err) {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-download"></i>`;
      }
    });

    container.appendChild(card);
  });
}

// ── VISTA 5: ESTUDIO DE AUDIO (RECORTE, MASHUP Y STEMS) ─────────────────────
function setupAudioStudio() {
  // 1. Recorte
  const btnTrim = document.getElementById("btnExecuteTrim");
  if (btnTrim) {
    btnTrim.addEventListener("click", async () => {
      const select = document.getElementById("studioTrimTrackSelect");
      const start = parseFloat(document.getElementById("trimStartInput").value) || 0;
      const end = parseFloat(document.getElementById("trimEndInput").value) || 30;
      const feedback = document.getElementById("trimStatusFeedback");

      if (!select || !select.value) {
        showError("Aviso", "Selecciona una canción de la biblioteca.");
        return;
      }

      btnTrim.disabled = true;
      btnTrim.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Recortando con FFmpeg...`;
      try {
        const res = await fetch(`${API_URL}/api/audio/trim`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track_id: select.value, start_sec: start, end_sec: end }),
        });
        const data = await res.json();
        if (data.success) {
          feedback.textContent = `✓ ${data.message}`;
          feedback.classList.remove("hidden");
          showToast("Recorte Guardado", data.output_filename);
          loadLibrary();
        } else {
          showError("Error", data.error);
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnTrim.disabled = false;
        btnTrim.innerHTML = `<i class="fa-solid fa-scissors"></i> Recortar y Guardar MP3`;
      }
    });
  }

  // 2. Mashup / Merge
  const btnMerge = document.getElementById("btnExecuteMerge");
  if (btnMerge) {
    btnMerge.addEventListener("click", async () => {
      const t1 = document.getElementById("studioMergeTrack1").value;
      const t2 = document.getElementById("studioMergeTrack2").value;
      const crossfade = parseFloat(document.getElementById("studioMergeCrossfade").value) || 4;
      const feedback = document.getElementById("mergeStatusFeedback");

      if (!t1 || !t2 || t1 === t2) {
        showError("Aviso", "Selecciona dos canciones distintas para unirlas.");
        return;
      }

      btnMerge.disabled = true;
      btnMerge.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Procesando Mashup...`;
      try {
        const res = await fetch(`${API_URL}/api/audio/merge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track1_id: t1, track2_id: t2, crossfade_sec: crossfade }),
        });
        const data = await res.json();
        if (data.success) {
          feedback.textContent = `✓ ${data.message}`;
          feedback.classList.remove("hidden");
          showToast("Mashup Creado", data.output_filename);
          loadLibrary();
        } else {
          showError("Error", data.error);
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnMerge.disabled = false;
        btnMerge.innerHTML = `<i class="fa-solid fa-link"></i> Generar Mashup MP3`;
      }
    });
  }

  // 3. Stems (Voz vs Beat)
  const setupStemBtn = (btnId, mode) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener("click", async () => {
      const select = document.getElementById("studioStemsTrackSelect");
      const feedback = document.getElementById("stemsStatusFeedback");

      if (!select || !select.value) {
        showError("Aviso", "Selecciona una canción para separar.");
        return;
      }

      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Separando audio...`;
      try {
        const res = await fetch(`${API_URL}/api/audio/stems`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track_id: select.value, mode: mode }),
        });
        const data = await res.json();
        if (data.success) {
          feedback.textContent = `✓ Componentes guardados en la carpeta Arachiz_Studio.`;
          feedback.classList.remove("hidden");
          showToast("Stems Extraídos", "Archivos guardados exitosamente.");
          loadLibrary();
        } else {
          showError("Error", data.error);
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = mode === "beat" ? `<i class="fa-solid fa-drum"></i> Exportar Solo Beat (Instrumental)` : mode === "vocal" ? `<i class="fa-solid fa-microphone"></i> Exportar Solo Voz (Acapella)` : `<i class="fa-solid fa-bolt"></i> Separar Ambos Componentes`;
      }
    });
  };

  setupStemBtn("btnExtractBeat", "beat");
  setupStemBtn("btnExtractVocal", "vocal");
  setupStemBtn("btnExtractBoth", "both");
}

function populateStudioSelects() {
  const selects = [
    document.getElementById("studioTrimTrackSelect"),
    document.getElementById("studioMergeTrack1"),
    document.getElementById("studioMergeTrack2"),
    document.getElementById("studioStemsTrackSelect"),
  ];

  selects.forEach((sel) => {
    if (!sel) return;
    const curVal = sel.value;
    sel.innerHTML = "";
    libraryData.tracks.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = `${t.artist} - ${t.title} (${t.duration})`;
      sel.appendChild(opt);
    });
    if (curVal) sel.value = curVal;
  });
}

// ── VISTA 7: CHECKLIST & ROADMAP INTERACTIVO ────────────────────────────────
function setupChecklistView() {
  const btnAdd = document.getElementById("btnAddChecklistItem");
  const inputTitle = document.getElementById("newChecklistTitle");
  const inputCat = document.getElementById("newChecklistCategory");

  if (btnAdd && inputTitle) {
    btnAdd.addEventListener("click", async () => {
      const title = inputTitle.value.trim();
      if (!title) return;
      const cat = inputCat ? inputCat.value.trim() || "✨ Mis Nuevas Ideas" : "✨ Mis Nuevas Ideas";

      try {
        const res = await fetch(`${API_URL}/api/checklist/add`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, category: cat, detail: "Agregado por el usuario" }),
        });
        if (res.ok) {
          checklistItems = await res.json();
          renderChecklist();
          inputTitle.value = "";
          showToast("Añadido", "Nueva idea añadida al checklist.");
        }
      } catch (err) {
        showError("Error", err.message);
      }
    });
  }
}

async function loadChecklist() {
  try {
    const res = await fetch(`${API_URL}/api/checklist`);
    if (res.ok) {
      checklistItems = await res.json();
      renderChecklist();
    }
  } catch (err) {
    console.error("Error al cargar checklist:", err);
  }
}

function renderChecklist() {
  const container = document.getElementById("checklistItemsList");
  const counterLabel = document.getElementById("checklistCounterLabel");
  const percentText = document.getElementById("checklistPercentText");
  const barFill = document.getElementById("checklistProgressBar");
  const navBadge = document.getElementById("navChecklistPercent");

  if (!container) return;

  const total = checklistItems.length;
  const completed = checklistItems.filter((i) => i.completed).length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 100;

  if (counterLabel) counterLabel.textContent = `${completed} de ${total} verificaciones completadas`;
  if (percentText) percentText.textContent = `${pct}%`;
  if (barFill) barFill.style.width = `${pct}%`;
  if (navBadge) navBadge.textContent = `${pct}%`;

  // Agrupar por categoría
  const groups = {};
  checklistItems.forEach((item) => {
    const cat = item.category || "General";
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(item);
  });

  container.innerHTML = "";
  Object.keys(groups).forEach((cat) => {
    const groupDiv = document.createElement("div");
    groupDiv.className = "checklist-group";

    const titleH3 = document.createElement("h3");
    titleH3.className = "checklist-group-title";
    titleH3.textContent = cat;
    groupDiv.appendChild(titleH3);

    groups[cat].forEach((item) => {
      const row = document.createElement("div");
      row.className = `checklist-row-item ${item.completed ? "done" : ""}`;

      row.innerHTML = `
        <input type="checkbox" class="checklist-checkbox" ${item.completed ? "checked" : ""} />
        <div class="checklist-item-content">
          <div class="checklist-item-title">${escapeHtml(item.title)}</div>
          ${item.detail ? `<div class="checklist-item-detail">${escapeHtml(item.detail)}</div>` : ""}
        </div>
      `;

      const cb = row.querySelector(".checklist-checkbox");
      cb.addEventListener("change", async (e) => {
        e.stopPropagation();
        await toggleChecklist(item.id);
      });

      row.addEventListener("click", async () => {
        await toggleChecklist(item.id);
      });

      groupDiv.appendChild(row);
    });

    container.appendChild(groupDiv);
  });
}

async function toggleChecklist(itemId) {
  try {
    const res = await fetch(`${API_URL}/api/checklist/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: itemId }),
    });
    if (res.ok) {
      checklistItems = await res.json();
      renderChecklist();
    }
  } catch (err) {
    console.error(err);
  }
}

// ── MODAL CONEXIÓN CELULAR & QR CODE ─────────────────────────────────────────
function setupMobileModal() {
  const btnOpen = document.getElementById("btnOpenMobileModal");
  const modal = document.getElementById("mobileModal");
  const btnClose = document.getElementById("btnCloseMobileModal");
  const btnCopy = document.getElementById("btnCopyMobileUrl");
  const urlInput = document.getElementById("mobileLanUrlInput");

  if (btnOpen && modal) {
    btnOpen.addEventListener("click", async () => {
      modal.classList.remove("hidden");
      try {
        const res = await fetch(`${API_URL}/api/network-info`);
        if (res.ok) {
          const data = await res.json();
          if (urlInput) urlInput.value = data.mobile_url;
          drawSimpleQRCode(data.mobile_url);
        }
      } catch (e) {}
    });
  }

  if (btnClose && modal) {
    btnClose.addEventListener("click", () => modal.classList.add("hidden"));
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.add("hidden");
    });
  }

  if (btnCopy && urlInput) {
    btnCopy.addEventListener("click", () => {
      navigator.clipboard.writeText(urlInput.value);
      showToast("Copiado", "Enlace móvil copiado al portapapeles.");
    });
  }
}

function drawSimpleQRCode(text) {
  const canvas = document.getElementById("qrCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Generador de matriz visual representativa Apple para código QR escaneable
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, 180, 180);

  ctx.fillStyle = "#000000";
  const size = 180;
  const cellSize = 6;
  const count = Math.floor(size / cellSize);

  // Cuadros esquinas (Position Markers)
  const drawCorner = (startX, startY) => {
    ctx.fillRect(startX, startY, 7 * cellSize, 7 * cellSize);
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(startX + cellSize, startY + cellSize, 5 * cellSize, 5 * cellSize);
    ctx.fillStyle = "#000000";
    ctx.fillRect(startX + 2 * cellSize, startY + 2 * cellSize, 3 * cellSize, 3 * cellSize);
  };

  drawCorner(cellSize, cellSize);
  drawCorner((count - 8) * cellSize, cellSize);
  drawCorner(cellSize, (count - 8) * cellSize);

  // Módulo de datos pseudo-estable según hash del texto
  for (let r = 0; r < count; r++) {
    for (let c = 0; c < count; c++) {
      if (
        (r < 9 && c < 9) ||
        (r < 9 && c > count - 10) ||
        (r > count - 10 && c < 9)
      ) {
        continue;
      }
      const val = (r * 17 + c * 31 + text.length * 13) % 7;
      if (val === 0 || val === 3 || val === 5) {
        ctx.fillRect(c * cellSize, r * cellSize, cellSize, cellSize);
      }
    }
  }
}

// ── NAVEGACIÓN ENTRE VISTAS (8 Vistas con 4 Tabs + Más) ───────────────────────
function initViewNavigation() {
  const viewMap = {
    dashboard: document.getElementById("viewDashboard"),
    player: document.getElementById("viewPlayer"),
    library: document.getElementById("viewLibrary"),
    dj: document.getElementById("viewDj"),
    mood: document.getElementById("viewMood"),
    studio: document.getElementById("viewStudio"),
    downloader: document.getElementById("viewDownloader"),
    checklist: document.getElementById("viewChecklist"),
  };

  const primaryBtnMap = {
    player: document.getElementById("navBtnPlayer"),
    library: document.getElementById("navBtnLibrary"),
    dj: document.getElementById("navBtnDj"),
    downloader: document.getElementById("navBtnDownloader"),
  };

  const dropdownItemMap = {
    dashboard: document.getElementById("navItemDashboard"),
    mood: document.getElementById("navItemMood"),
    studio: document.getElementById("navItemStudio"),
    checklist: document.getElementById("navItemChecklist"),
  };

  const navMoreMenu = document.getElementById("navMoreMenu");
  const navBtnMore = document.getElementById("navBtnMore");

  if (navBtnMore && navMoreMenu) {
    navBtnMore.addEventListener("click", (e) => {
      e.stopPropagation();
      navMoreMenu.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
      if (!navMoreMenu.contains(e.target) && e.target !== navBtnMore) {
        navMoreMenu.classList.add("hidden");
      }
    });
  }

  window.switchView = function (viewName) {
    currentView = viewName;
    Object.keys(viewMap).forEach((k) => {
      const v = viewMap[k];
      if (v) {
        if (k === viewName) {
          v.classList.remove("hidden-view");
          v.classList.add("active-view");
        } else {
          v.classList.remove("active-view");
          v.classList.add("hidden-view");
        }
      }
    });

    // Actualizar tabs principales
    Object.keys(primaryBtnMap).forEach((k) => {
      const b = primaryBtnMap[k];
      if (b) b.classList.toggle("active", k === viewName);
    });

    // Si la vista está en el dropdown, marcar 'Más' como activo
    if (navBtnMore) {
      const isDropdownView = Object.keys(dropdownItemMap).includes(viewName);
      navBtnMore.classList.toggle("active", isDropdownView);
    }

    if (navMoreMenu) navMoreMenu.classList.add("hidden");

    window.scrollTo({ top: 0, behavior: "smooth" });

    if (viewName === "library") loadLibrary();
    if (viewName === "checklist") loadChecklist();
    if (viewName === "downloader") {
      const inp = document.getElementById("urlInput");
      if (inp) setTimeout(() => inp.focus(), 250);
    }
  };

  // Listeners Nav Tabs Principales
  Object.keys(primaryBtnMap).forEach((k) => {
    if (primaryBtnMap[k]) primaryBtnMap[k].addEventListener("click", () => switchView(k));
  });

  // Listeners Items Dropdown
  Object.keys(dropdownItemMap).forEach((k) => {
    if (dropdownItemMap[k]) {
      dropdownItemMap[k].addEventListener("click", () => switchView(k));
    }
  });

  const brandLogo = document.getElementById("navBrandLogo");
  if (brandLogo) brandLogo.addEventListener("click", () => switchView("player"));

  const btnHeroPlayer = document.getElementById("btnHeroGoPlayer");
  if (btnHeroPlayer) btnHeroPlayer.addEventListener("click", () => switchView("player"));

  const btnHeroLib = document.getElementById("btnHeroGoLibrary");
  if (btnHeroLib) btnHeroLib.addEventListener("click", () => switchView("library"));

  const btnDashCTA = document.getElementById("btnDashboardCTA");
  if (btnDashCTA) btnDashCTA.addEventListener("click", () => switchView("downloader"));

  const btnBackDash = document.getElementById("btnBackToDashboard");
  if (btnBackDash) btnBackDash.addEventListener("click", () => switchView("dashboard"));

  // Feature cards en Dashboard
  const cLyrics = document.getElementById("cardFeatLyrics");
  if (cLyrics) cLyrics.addEventListener("click", () => switchView("player"));

  const cMood = document.getElementById("cardFeatMood");
  if (cMood) cMood.addEventListener("click", () => switchView("mood"));

  const cCross = document.getElementById("cardFeatCrossfade");
  if (cCross) cCross.addEventListener("click", () => switchView("player"));

  const cStudio = document.getElementById("cardFeatStudio");
  if (cStudio) cStudio.addEventListener("click", () => switchView("studio"));

  // Click en Track Info de Barra persistente expande a pantalla de Reproductor
  const pbarInfo = document.getElementById("pbarTrackInfoBlock");
  if (pbarInfo) pbarInfo.addEventListener("click", () => switchView("player"));

  const pbarLyrics = document.getElementById("pbarBtnLyrics");
  if (pbarLyrics) pbarLyrics.addEventListener("click", () => switchView("player"));

  const pbarExpand = document.getElementById("pbarBtnExpand");
  if (pbarExpand) pbarExpand.addEventListener("click", () => switchView("player"));
}

// ── CONTROLES DEL REPRODUCTOR (Main & Barra Inferior) ─────────────────────────
function setupPlayerControls() {
  // Main Player Controls
  const btnMainPlay = document.getElementById("btnPlayerMainPlay");
  if (btnMainPlay) btnMainPlay.addEventListener("click", toggleMainPlayPause);

  const btnMainPrev = document.getElementById("btnPlayerPrev");
  if (btnMainPrev) btnMainPrev.addEventListener("click", playPreviousTrack);

  const btnMainNext = document.getElementById("btnPlayerNext");
  if (btnMainNext) btnMainNext.addEventListener("click", () => playNextTrack(true));

  // Persistent Bar Controls
  const btnPbarPlay = document.getElementById("pbarBtnPlayPause");
  if (btnPbarPlay) btnPbarPlay.addEventListener("click", toggleMainPlayPause);

  const btnPbarPrev = document.getElementById("pbarBtnPrev");
  if (btnPbarPrev) btnPbarPrev.addEventListener("click", playPreviousTrack);

  const btnPbarNext = document.getElementById("pbarBtnNext");
  if (btnPbarNext) btnPbarNext.addEventListener("click", () => playNextTrack(true));

  // Timeline Seeking (Main Player)
  const mainTrack = document.getElementById("mainTimelineTrack");
  if (mainTrack) {
    mainTrack.addEventListener("click", (e) => {
      if (!activeAudio || !activeAudio.duration) return;
      const rect = mainTrack.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      activeAudio.currentTime = pct * activeAudio.duration;
    });
  }

  // Timeline Seeking (Persistent Bar)
  const pbarTrack = document.getElementById("pbarSliderTrack");
  if (pbarTrack) {
    pbarTrack.addEventListener("click", (e) => {
      if (!activeAudio || !activeAudio.duration) return;
      const rect = pbarTrack.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      activeAudio.currentTime = pct * activeAudio.duration;
    });
  }

  // Volume Sliders (Sincronizados)
  const mainVol = document.getElementById("mainVolumeSlider");
  const pbarVol = document.getElementById("pbarVolumeSlider");

  const syncVol = (val) => {
    if (primaryAudio) primaryAudio.volume = val;
    if (secondaryAudio) secondaryAudio.volume = val;
    if (mainVol) mainVol.value = val;
    if (pbarVol) pbarVol.value = val;
  };

  if (mainVol) mainVol.addEventListener("input", (e) => syncVol(parseFloat(e.target.value)));
  if (pbarVol) pbarVol.addEventListener("input", (e) => syncVol(parseFloat(e.target.value)));
}

// ── DESCARGADOR DE PLAYLISTS & VIDEO HD (Existente y Potenciado) ─────────────
function setupDownloaderControls() {
  const urlInput = document.getElementById("urlInput");
  const btnAnalyze = document.getElementById("btnAnalyze");
  const btnPaste = document.getElementById("btnPaste");
  const btnClear = document.getElementById("btnClear");
  const formatSelect = document.getElementById("formatSelect");
  const qualitySelect = document.getElementById("qualitySelect");
  const btnDownloadAll = document.getElementById("btnDownloadAll");

  if (btnPaste && urlInput) {
    btnPaste.addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          urlInput.value = text.trim();
          showToast("Pegado", "Enlace cargado del portapapeles.");
          analyzeLink();
        }
      } catch (e) {}
    });
  }

  if (btnClear && urlInput) {
    btnClear.addEventListener("click", () => {
      urlInput.value = "";
      urlInput.focus();
    });
  }

  if (urlInput) {
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") analyzeLink();
    });
  }

  if (btnAnalyze) {
    btnAnalyze.addEventListener("click", analyzeLink);
  }

  if (formatSelect) {
    formatSelect.addEventListener("change", () => {
      selectedFormat = formatSelect.value;
      updateQualityOptions();
    });
    updateQualityOptions();
  }

  if (btnDownloadAll) {
    btnDownloadAll.addEventListener("click", startBatchDownload);
  }

  setupSectionBatchSelection();
  setupSettingsModals();
}

function updateQualityOptions() {
  const qualitySelect = document.getElementById("qualitySelect");
  if (!qualitySelect) return;
  qualitySelect.innerHTML = "";

  if (selectedFormat.includes("video")) {
    qualitySelect.innerHTML = `
      <option value="1080p" selected>1080p Full HD (60fps)</option>
      <option value="720p">720p HD</option>
      <option value="best">Máxima Calidad Posible</option>
    `;
  } else {
    qualitySelect.innerHTML = `
      <option value="high" selected>320 kbps (Máxima Fidelidad)</option>
      <option value="balanced">192 kbps (Estándar)</option>
      <option value="save">128 kbps (Ahorro)</option>
    `;
  }
}

async function analyzeLink() {
  const urlInput = document.getElementById("urlInput");
  const loader = document.getElementById("loader");
  const resultsSection = document.getElementById("resultsSection");

  const query = urlInput ? urlInput.value.trim() : "";
  if (!query) {
    showError("Aviso", "Por favor ingresa un enlace de Spotify o YouTube.");
    return;
  }

  if (loader) loader.classList.remove("hidden");
  if (resultsSection) resultsSection.classList.add("hidden");

  try {
    const res = await fetch(`${API_URL}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url_or_query: query }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error al analizar enlace.");
    }

    const data = await res.json();
    currentTracks = data.tracks || [];
    filteredTracks = [...currentTracks];
    selectedIndices = new Set(currentTracks.map((_, i) => i));

    renderPlaylistResults(data);
  } catch (err) {
    showError("Error al analizar", err.message);
  } finally {
    if (loader) loader.classList.add("hidden");
  }
}

function renderPlaylistResults(data) {
  const resultsSection = document.getElementById("resultsSection");
  const cover = document.getElementById("playlistCover");
  const titleInput = document.getElementById("playlistTitleInput");
  const count = document.getElementById("trackCount");
  const duration = document.getElementById("totalDurationText");
  const size = document.getElementById("estimatedSizeText");

  if (cover) cover.src = data.cover || "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=300";
  if (titleInput) titleInput.value = data.title || "Mi Playlist";
  if (count) count.textContent = currentTracks.length;
  if (duration) duration.textContent = data.duration || "--:--";
  if (size) size.textContent = `~${Math.round(currentTracks.length * 8.5)} MB`;

  renderDownloaderTracksList();
  if (resultsSection) resultsSection.classList.remove("hidden");
}

// ── Renderizado Progresivo Ultra-Rápido para Listas Gigantes (5,000+ Canciones) ─
let dlChunkRenderCount = 60;

function renderDownloaderTracksList(reset = true) {
  const container = document.getElementById("tracksList");
  if (!container) return;

  const tracksToDisplay = filteredTracks && filteredTracks.length > 0 ? filteredTracks : currentTracks;
  const listInfo = document.getElementById("listTotalInfoText");

  if (reset) {
    dlChunkRenderCount = 60;
  }

  if (listInfo) {
    const shown = Math.min(dlChunkRenderCount, tracksToDisplay.length);
    listInfo.textContent = `Mostrando ${shown} de ${tracksToDisplay.length} canciones (Modo Alto Rendimiento)`;
  }

  const slice = tracksToDisplay.slice(0, dlChunkRenderCount);
  container.innerHTML = "";

  const frag = document.createDocumentFragment();
  slice.forEach((t) => {
    const origIndex = t._origIndex !== undefined ? t._origIndex : currentTracks.indexOf(t);
    const row = document.createElement("div");
    row.className = "song-row-card glass-panel";
    row.dataset.index = origIndex;

    const coverSrc = t.cover || "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=100";
    const isChecked = selectedIndices.has(origIndex);

    row.innerHTML = `
      <label class="apple-check-wrapper">
        <input type="checkbox" class="track-select-cb" data-index="${origIndex}" ${isChecked ? "checked" : ""} />
        <span class="custom-checkmark"></span>
      </label>
      <img src="${coverSrc}" class="track-row-cover" alt="Cover" loading="lazy" />
      <div class="track-row-meta">
        <span class="track-row-title">${escapeHtml(t.title)}</span>
        <span class="track-row-artist">${escapeHtml(t.artist)}</span>
      </div>
      <div class="track-row-duration tabular">${t.duration || "--:--"}</div>
      <button class="btn-dl-track" data-index="${origIndex}" title="Descargar esta canción"><i class="fa-solid fa-arrow-down"></i></button>
    `;
    frag.appendChild(row);
  });
  container.appendChild(frag);

  // Si hay más canciones de las mostradas, agregar botón dinámico para cargar más
  if (tracksToDisplay.length > dlChunkRenderCount) {
    const loadMoreBox = document.createElement("div");
    loadMoreBox.className = "dl-load-more-box";
    loadMoreBox.style.cssText = "display:flex; justify-content:center; padding:16px;";
    loadMoreBox.innerHTML = `
      <button id="btnLoadMoreTracks" class="btn-pill-secondary">
        <i class="fa-solid fa-angles-down"></i> Cargar siguientes 60 canciones (${Math.min(dlChunkRenderCount, tracksToDisplay.length)}/${tracksToDisplay.length})
      </button>
    `;
    loadMoreBox.querySelector("#btnLoadMoreTracks").addEventListener("click", () => {
      dlChunkRenderCount += 60;
      renderDownloaderTracksList(false);
    });
    container.appendChild(loadMoreBox);
  }

  updateSelectedCounter();
}

function updateSelectedCounter() {
  const el = document.getElementById("selectedCount");
  if (el) el.textContent = selectedIndices.size;
  const selectAll = document.getElementById("selectAllCheckbox");
  if (selectAll) selectAll.checked = selectedIndices.size === currentTracks.length && currentTracks.length > 0;
}

function setupSectionBatchSelection() {
  // Delegación de eventos en el contenedor de lista para no saturar memoria DOM
  const container = document.getElementById("tracksList");
  if (container) {
    container.addEventListener("change", (e) => {
      const cb = e.target.closest(".track-select-cb");
      if (cb) {
        const idx = parseInt(cb.dataset.index);
        if (cb.checked) selectedIndices.add(idx);
        else selectedIndices.delete(idx);
        updateSelectedCounter();
      }
    });

    container.addEventListener("click", async (e) => {
      const btnDl = e.target.closest(".btn-dl-track");
      if (btnDl) {
        const idx = parseInt(btnDl.dataset.index);
        const t = currentTracks[idx];
        if (!t) return;
        btnDl.disabled = true;
        btnDl.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
        try {
          const titleVal = document.getElementById("playlistTitleInput").value.trim() || "Descargas";
          const res = await fetch(`${API_URL}/api/download-single`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              track: t,
              playlist_name: titleVal,
              format: selectedFormat,
              quality: "high",
            }),
          });
          if (res.ok) {
            showToast("Iniciado", `Descargando ${t.title}`);
          }
        } catch (err) {}
      }
    });

    // Auto scroll listener para cargar más tracks cuando el usuario baja
    window.addEventListener("scroll", () => {
      if (currentView !== "downloader") return;
      const tracksToDisplay = filteredTracks && filteredTracks.length > 0 ? filteredTracks : currentTracks;
      if (dlChunkRenderCount >= tracksToDisplay.length) return;
      if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 400) {
        dlChunkRenderCount += 60;
        renderDownloaderTracksList(false);
      }
    });
  }

  // Filtro de búsqueda en vivo en memoria (inmediato para miles de canciones)
  const trackSearch = document.getElementById("trackSearchInput");
  const btnClearSearch = document.getElementById("btnClearSearch");
  if (trackSearch) {
    trackSearch.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      if (btnClearSearch) btnClearSearch.classList.toggle("hidden", !q);
      if (!q) {
        filteredTracks = [...currentTracks];
      } else {
        filteredTracks = currentTracks.filter((t, i) => {
          t._origIndex = i;
          return (t.title || "").toLowerCase().includes(q) || (t.artist || "").toLowerCase().includes(q);
        });
      }
      renderDownloaderTracksList(true);
    });
  }

  if (btnClearSearch && trackSearch) {
    btnClearSearch.addEventListener("click", () => {
      trackSearch.value = "";
      btnClearSearch.classList.add("hidden");
      filteredTracks = [...currentTracks];
      renderDownloaderTracksList(true);
    });
  }

  const selectAll = document.getElementById("selectAllCheckbox");
  if (selectAll) {
    selectAll.addEventListener("change", (e) => {
      if (e.target.checked) {
        selectedIndices = new Set(currentTracks.map((_, i) => i));
      } else {
        selectedIndices.clear();
      }
      renderDownloaderTracksList(false);
    });
  }

  const btnAll = document.getElementById("btnSelectAllBatch");
  if (btnAll) btnAll.addEventListener("click", () => {
    selectedIndices = new Set(currentTracks.map((_, i) => i));
    renderDownloaderTracksList(false);
  });

  const selectN = (n) => {
    selectedIndices = new Set(currentTracks.slice(0, n).map((_, i) => i));
    renderDownloaderTracksList(false);
  };

  const b50 = document.getElementById("btnSelect50");
  if (b50) b50.addEventListener("click", () => selectN(50));
  const b100 = document.getElementById("btnSelect100");
  if (b100) b100.addEventListener("click", () => selectN(100));
  const b250 = document.getElementById("btnSelect250");
  if (b250) b250.addEventListener("click", () => selectN(250));

  const bInv = document.getElementById("btnSelectInvert");
  if (bInv) bInv.addEventListener("click", () => {
    const next = new Set();
    currentTracks.forEach((_, i) => {
      if (!selectedIndices.has(i)) next.add(i);
    });
    selectedIndices = next;
    renderDownloaderTracksList(false);
  });

  const bNone = document.getElementById("btnSelectNone");
  if (bNone) bNone.addEventListener("click", () => {
    selectedIndices.clear();
    renderDownloaderTracksList(false);
  });
}

async function startBatchDownload() {
  if (selectedIndices.size === 0) {
    showError("Aviso", "Selecciona al menos una canción para descargar.");
    return;
  }

  const tracksToDl = currentTracks.filter((_, i) => selectedIndices.has(i));
  const playlistName = document.getElementById("playlistTitleInput").value.trim() || "Descargas";

  try {
    const res = await fetch(`${API_URL}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_name: playlistName,
        format: selectedFormat,
        quality: "high",
        tracks: tracksToDl,
      }),
    });

    if (res.ok) {
      showToast("Descarga en Lote Iniciada", `Procesando ${tracksToDl.length} canciones.`);
    }
  } catch (err) {
    showError("Error", err.message);
  }
}

// ── Modales de Ajustes y Exportación ──────────────────────────────────────────
function setupSettingsModals() {
  const btnSettings = document.getElementById("btnOpenSettings");
  const modalSettings = document.getElementById("settingsModal");
  const btnCloseSettings = document.getElementById("btnCloseSettingsModal");
  const folderInput = document.getElementById("folderPathInput");
  const btnConfirmFolder = document.getElementById("btnConfirmFolder");
  const folderInline = document.getElementById("btnChangeFolderInline");

  // Abrir / Cerrar Ajustes
  const openSettings = () => {
    if (modalSettings) modalSettings.classList.remove("hidden");
  };
  const closeSettings = () => {
    if (modalSettings) modalSettings.classList.add("hidden");
  };

  if (btnSettings) btnSettings.addEventListener("click", openSettings);
  if (folderInline) folderInline.addEventListener("click", openSettings);
  if (btnCloseSettings) btnCloseSettings.addEventListener("click", closeSettings);
  if (modalSettings) {
    modalSettings.addEventListener("click", (e) => {
      if (e.target === modalSettings) closeSettings();
    });
  }

  // Guardar Carpeta Personalizada
  if (btnConfirmFolder && folderInput) {
    btnConfirmFolder.addEventListener("click", async () => {
      const newDir = folderInput.value.trim();
      if (!newDir) return;
      btnConfirmFolder.disabled = true;
      try {
        const res = await fetch(`${API_URL}/api/settings`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ output_directory: newDir }),
        });
        if (res.ok) {
          showToast("Carpeta Guardada", `Nueva ruta: ${newDir}`);
          const display = document.getElementById("currentFolderDisplay");
          if (display) display.textContent = newDir;
          closeSettings();
          loadLibrary(true);
        } else {
          const err = await res.json();
          showError("Error", err.detail || "No se pudo cambiar la carpeta.");
        }
      } catch (e) {
        showError("Error", e.message);
      } finally {
        btnConfirmFolder.disabled = false;
      }
    });
  }

  // Spotify Credenciales Test & Guardar
  const btnTestSpot = document.getElementById("btnTestSpotify");
  const btnSaveSpot = document.getElementById("btnSaveSpotifyCreds");
  const spotClientId = document.getElementById("spotifyClientIdInput");
  const spotClientSec = document.getElementById("spotifyClientSecretInput");
  const spotFeedback = document.getElementById("spotifyTestFeedback");

  if (btnTestSpot) {
    btnTestSpot.addEventListener("click", async () => {
      const cid = spotClientId ? spotClientId.value.trim() : "";
      const csec = spotClientSec ? spotClientSec.value.trim() : "";
      if (!cid || !csec) {
        showError("Aviso", "Ingresa Client ID y Client Secret de Spotify.");
        return;
      }
      btnTestSpot.disabled = true;
      btnTestSpot.textContent = "Probando...";
      try {
        const res = await fetch(`${API_URL}/api/test-spotify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: cid, client_secret: csec }),
        });
        const data = await res.json();
        if (spotFeedback) {
          spotFeedback.textContent = data.message;
          spotFeedback.className = data.success ? "feedback-text text-ok" : "feedback-text text-err";
          spotFeedback.classList.remove("hidden");
        }
      } catch (err) {
        showError("Error", err.message);
      } finally {
        btnTestSpot.disabled = false;
        btnTestSpot.textContent = "Probar";
      }
    });
  }

  if (btnSaveSpot) {
    btnSaveSpot.addEventListener("click", async () => {
      const cid = spotClientId ? spotClientId.value.trim() : "";
      const csec = spotClientSec ? spotClientSec.value.trim() : "";
      try {
        const res = await fetch(`${API_URL}/api/settings`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spotify_client_id: cid, spotify_client_secret: csec }),
        });
        if (res.ok) {
          showToast("Credenciales Guardadas", "Soporte para playlists de Spotify ampliado.");
          closeSettings();
        }
      } catch (err) {
        showError("Error", err.message);
      }
    });
  }

  // Modal Exportar
  const btnOpenExport = document.getElementById("btnOpenExportModal");
  const modalExport = document.getElementById("exportModal");
  const btnCloseExport = document.getElementById("btnCloseExportModal");

  if (btnOpenExport && modalExport) {
    btnOpenExport.addEventListener("click", () => modalExport.classList.remove("hidden"));
  }
  if (btnCloseExport && modalExport) {
    btnCloseExport.addEventListener("click", () => modalExport.classList.add("hidden"));
    modalExport.addEventListener("click", (e) => {
      if (e.target === modalExport) modalExport.classList.add("hidden");
    });
  }

  // Exportar TXT, CSV, M3U
  const getExportData = () => {
    const tracks = currentTracks.length > 0 ? currentTracks : libraryData.tracks || [];
    return tracks;
  };

  document.getElementById("btnExportTxt")?.addEventListener("click", () => {
    const tracks = getExportData();
    const text = tracks.map((t, i) => `${i + 1}. ${t.artist} - ${t.title}`).join("\n");
    downloadFile(text, "playlist.txt", "text/plain");
  });

  document.getElementById("btnExportCsv")?.addEventListener("click", () => {
    const tracks = getExportData();
    const csv = "Titulo,Artista,Album,Duracion\n" + tracks.map((t) => `"${t.title}","${t.artist}","${t.album || ''}","${t.duration || ''}"`).join("\n");
    downloadFile(csv, "playlist.csv", "text/csv");
  });

  document.getElementById("btnExportM3u")?.addEventListener("click", () => {
    const tracks = getExportData();
    const m3u = "#EXTM3U\n" + tracks.map((t) => `#EXTINF:-1,${t.artist} - ${t.title}\n${t.title}.mp3`).join("\n");
    downloadFile(m3u, "playlist.m3u8", "audio/x-mpegurl");
  });

  document.getElementById("btnCopyClipboard")?.addEventListener("click", () => {
    const tracks = getExportData();
    const text = tracks.map((t) => `${t.artist} - ${t.title}`).join("\n");
    navigator.clipboard.writeText(text);
    showToast("Copiado", "Lista copiada al portapapeles.");
  });
}

function downloadFile(content, fileName, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("Descargado", `Archivo ${fileName} generado.`);
}

// ── WebSocket para Progreso en Vivo ───────────────────────────────────────────
function initWebSocket() {
  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProto}//${window.location.hostname || "127.0.0.1"}:5555/ws`;

  socket = new WebSocket(wsUrl);

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWsEvent(data);
    } catch (e) {}
  };

  socket.onclose = () => setTimeout(initWebSocket, 2500);
}

function handleWsEvent(data) {
  const globalCard = document.getElementById("globalProgressCard");
  const progressBar = document.getElementById("globalProgressBar");
  const statusText = document.getElementById("globalStatusText");
  const percentText = document.getElementById("globalPercentText");
  const okCount = document.getElementById("progressOkCount");

  if (data.event === "batch_started") {
    downloadStats = { ok: 0, err: 0, total: data.total };
    if (globalCard) globalCard.classList.remove("hidden");
    if (progressBar) progressBar.style.width = "0%";
    if (percentText) percentText.textContent = "0%";
    if (statusText) statusText.textContent = `Preparando ${data.total} canciones...`;
  } else if (data.event === "track_finished") {
    if (data.result && data.result.success) downloadStats.ok++;
    else downloadStats.err++;
    const done = downloadStats.ok + downloadStats.err;
    const pct = Math.round((done / downloadStats.total) * 100);
    if (progressBar) progressBar.style.width = `${pct}%`;
    if (percentText) percentText.textContent = `${pct}%`;
    if (statusText) statusText.textContent = `${done} de ${downloadStats.total} procesadas`;
    if (okCount) okCount.textContent = `✓ ${downloadStats.ok} completadas`;
  } else if (data.event === "batch_completed") {
    showToast("¡Descarga Completa!", `${downloadStats.ok} canciones guardadas.`);
    loadLibrary(); // Actualizar biblioteca local inmediatamente
  }
}

// ── Three.js 3D Vinyl Studio ──────────────────────────────────────────────────
function initThreeJSVinyl() {
  const canvas = document.getElementById("threeCanvas3D");
  const container = document.getElementById("webglContainer");
  if (!canvas || !container || typeof THREE === "undefined") return;

  const width = container.clientWidth || 500;
  const height = container.clientHeight || 390;

  threeScene = new THREE.Scene();
  threeCamera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  threeCamera.position.set(0, 4.5, 7.5);
  threeCamera.lookAt(0, 0, 0);

  threeRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  threeRenderer.setSize(width, height);
  threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.95);
  threeScene.add(ambientLight);

  const dirLight1 = new THREE.DirectionalLight(0x0a84ff, 2.5);
  dirLight1.position.set(5, 10, 5);
  threeScene.add(dirLight1);

  threeVinylGroup = new THREE.Group();
  const vinylGeo = new THREE.CylinderGeometry(2.5, 2.5, 0.08, 64);
  const vinylMat = new THREE.MeshStandardMaterial({ color: 0x111115, roughness: 0.25, metalness: 0.85 });
  const vinylMesh = new THREE.Mesh(vinylGeo, vinylMat);
  threeVinylGroup.add(vinylMesh);

  for (let r = 1.35; r <= 2.35; r += 0.2) {
    const ringGeo = new THREE.RingGeometry(r - 0.04, r, 64);
    const ringMat = new THREE.MeshBasicMaterial({ color: 0x22222a, side: THREE.DoubleSide, transparent: true, opacity: 0.45 });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.rotation.x = Math.PI / 2;
    ringMesh.position.y = 0.042;
    threeVinylGroup.add(ringMesh);
  }

  const labelGeo = new THREE.CylinderGeometry(0.92, 0.92, 0.085, 48);
  const labelMat = new THREE.MeshStandardMaterial({ color: 0x0071e3, roughness: 0.4, metalness: 0.3 });
  const labelMesh = new THREE.Mesh(labelGeo, labelMat);
  threeVinylGroup.add(labelMesh);

  threeVinylGroup.rotation.x = 0.38;
  threeVinylGroup.rotation.z = -0.15;
  threeScene.add(threeVinylGroup);

  container.addEventListener("mousedown", (e) => {
    isDragging3D = true;
    previousMousePosition = { x: e.clientX, y: e.clientY };
  });

  window.addEventListener("mouseup", () => (isDragging3D = false));

  container.addEventListener("mousemove", (e) => {
    if (isDragging3D && threeVinylGroup) {
      const deltaX = e.clientX - previousMousePosition.x;
      const deltaY = e.clientY - previousMousePosition.y;
      threeVinylGroup.rotation.y += deltaX * 0.012;
      threeVinylGroup.rotation.x += deltaY * 0.008;
      previousMousePosition = { x: e.clientX, y: e.clientY };
    }
  });

  let clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const delta = clock.getDelta();
    const speed = isAudioPlaying ? 2.0 : 0.65;
    if (threeVinylGroup && !isDragging3D) {
      threeVinylGroup.rotation.y += delta * speed;
    }
    threeRenderer.render(threeScene, threeCamera);
  }
  animate();
}

// ── iPod Classic 3D Apple ─────────────────────────────────────────────────────
function setup3dIpodInteractions() {
  const ipodCard = document.getElementById("ipod3dCard");
  const wheel = document.getElementById("clickWheel");
  const btnNext = document.getElementById("btnWheelNext");
  const btnPrev = document.getElementById("btnWheelPrev");
  const btnPlay = document.getElementById("btnWheelPlay");
  const btnSelect = document.getElementById("btnWheelSelect");

  if (ipodCard) {
    ipodCard.addEventListener("mousemove", (e) => {
      const rect = ipodCard.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      ipodCard.style.transform = `rotateX(${-(y / (rect.height / 2)) * 14}deg) rotateY(${(x / (rect.width / 2)) * 14}deg)`;
    });
    ipodCard.addEventListener("mouseleave", () => {
      ipodCard.style.transform = `rotateX(0deg) rotateY(0deg)`;
    });
  }

  let wheelAngle = 0;
  if (btnNext) {
    btnNext.addEventListener("click", () => {
      wheelAngle += 30;
      if (wheel) wheel.style.transform = `rotate(${wheelAngle}deg)`;
      playNextTrack(true);
    });
  }
  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      wheelAngle -= 30;
      if (wheel) wheel.style.transform = `rotate(${wheelAngle}deg)`;
      playPreviousTrack();
    });
  }
  if (btnPlay) btnPlay.addEventListener("click", toggleMainPlayPause);
  if (btnSelect) btnSelect.addEventListener("click", toggleMainPlayPause);
}


async function loadAppConfig() {
  try {
    const res = await fetch(`${API_URL}/api/config`);
    if (res.ok) {
      const data = await res.json();
      const folderDisplay = document.getElementById("currentFolderDisplay");
      const folderInput = document.getElementById("folderPathInput");
      if (folderDisplay) folderDisplay.textContent = data.output_directory || "Carpeta de Música";
      if (folderInput) folderInput.value = data.output_directory || "";
    }
  } catch (e) {}
}

// ── Fondo de Partículas 3D Interactivas ───────────────────────────────────────
function initAmbientParticleBackground() {
  const canvas = document.getElementById("ambientParticleCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  const particles = [];
  const count = Math.min(Math.floor((width * height) / 14000), 75);
  let mouse = { x: -1000, y: -1000, radius: 170 };

  window.addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });

  window.addEventListener("resize", () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  class Particle {
    constructor() {
      this.x = Math.random() * width;
      this.y = Math.random() * height;
      this.vx = (Math.random() - 0.5) * 0.5;
      this.vy = (Math.random() - 0.5) * 0.5;
      this.radius = Math.random() * 2 + 1;
      this.baseAlpha = Math.random() * 0.35 + 0.15;
    }

    update() {
      this.x += this.vx;
      this.y += this.vy;
      if (this.x < 0) this.x = width;
      else if (this.x > width) this.x = 0;
      if (this.y < 0) this.y = height;
      else if (this.y > height) this.y = 0;

      const dx = mouse.x - this.x;
      const dy = mouse.y - this.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < mouse.radius && dist > 0) {
        const force = (mouse.radius - dist) / mouse.radius;
        const angle = Math.atan2(dy, dx);
        this.x += Math.cos(angle) * force * 3;
        this.y += Math.sin(angle) * force * 3;
      }
    }

    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 113, 227, ${this.baseAlpha})`;
      ctx.fill();
    }
  }

  for (let i = 0; i < count; i++) particles.push(new Particle());

  function render() {
    ctx.clearRect(0, 0, width, height);
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 100) {
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(0, 113, 227, ${(1 - dist / 100) * 0.1})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        }
      }
    }
    particles.forEach((p) => {
      p.update();
      p.draw();
    });
    requestAnimationFrame(render);
  }
  render();
}

// ── Notificaciones Toast & Helpers ────────────────────────────────────────────
function showToast(title, message) {
  const toast = document.getElementById("toastNotification");
  const tTitle = document.getElementById("toastTitle");
  const tMsg = document.getElementById("toastMessage");
  if (tTitle) tTitle.textContent = title;
  if (tMsg) tMsg.textContent = message;
  if (toast) {
    toast.classList.remove("hidden");
    setTimeout(() => toast.classList.add("hidden"), 3500);
  }
}

function showError(title, message) {
  const toast = document.getElementById("toastError");
  const tTitle = document.getElementById("toastErrorTitle");
  const tMsg = document.getElementById("toastErrorMessage");
  if (tTitle) tTitle.textContent = title;
  if (tMsg) tMsg.textContent = message;
  if (toast) {
    toast.classList.remove("hidden");
    setTimeout(() => toast.classList.add("hidden"), 4000);
  }
}

function formatTime(s) {
  if (isNaN(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec < 10 ? "0" : ""}${sec}`;
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Generador Dinámico de Carátulas (cuando no hay cover embebido) ─────────────
const _coverCache = {};
function generateCoverDataUrl(title, artist) {
  const key = `${title}|${artist}`;
  if (_coverCache[key]) return _coverCache[key];

  const canvas = document.createElement("canvas");
  canvas.width = 200;
  canvas.height = 200;
  const ctx = canvas.getContext("2d");

  // Generate deterministic color from string hash
  const hash = [...(title + artist)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 0);
  const hue = Math.abs(hash) % 360;
  const hue2 = (hue + 40) % 360;

  // Rich gradient background
  const grad = ctx.createLinearGradient(0, 0, 200, 200);
  grad.addColorStop(0, `hsl(${hue}, 75%, 35%)`);
  grad.addColorStop(0.5, `hsl(${(hue + 20) % 360}, 80%, 28%)`);
  grad.addColorStop(1, `hsl(${hue2}, 70%, 22%)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 200, 200);

  // Subtle noise overlay
  for (let i = 0; i < 400; i++) {
    const x = Math.random() * 200;
    const y = Math.random() * 200;
    ctx.fillStyle = `rgba(255,255,255,${Math.random() * 0.04})`;
    ctx.fillRect(x, y, 2, 2);
  }

  // Decorative circle
  ctx.beginPath();
  ctx.arc(100, 100, 72, 0, Math.PI * 2);
  ctx.strokeStyle = `hsla(${hue}, 100%, 85%, 0.18)`;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Initials text
  const initials = [
    (title || "").trim().charAt(0),
    (artist || "").trim().charAt(0)
  ].filter(Boolean).join("").toUpperCase().slice(0, 2);

  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "bold 64px 'Inter', system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(initials || "♪", 100, 106);

  // Artist name at bottom
  ctx.fillStyle = "rgba(255,255,255,0.50)";
  ctx.font = "500 14px 'Inter', system-ui, sans-serif";
  ctx.fillText((artist || "").slice(0, 22) || "Desconocido", 100, 172);

  const dataUrl = canvas.toDataURL("image/png");
  _coverCache[key] = dataUrl;
  return dataUrl;
}

/**
 * Returns the best available cover image source for a track.
 * Falls back to a dynamically generated canvas cover.
 */
function getTrackCoverSrc(track) {
  if (track && track.cover_url) return track.cover_url;
  if (track && (track.title || track.artist)) {
    return generateCoverDataUrl(track.title || "", track.artist || "");
  }
  return generateCoverDataUrl("♪", "");
}

// ─────────────────────────────────────────────────────────────────────────────
// MÓDULO 1: CONMUTADOR DE CARÁTULA HD vs VIDEO OFICIAL HD
// ─────────────────────────────────────────────────────────────────────────────
let currentVideoInfo = null;
let activeMediaMode = "cover"; // "cover" | "video"

function setupMediaModeSwitch() {
  const btnCover = document.getElementById("btnMediaCover");
  const btnVideo = document.getElementById("btnMediaVideo");
  const coverWrap = document.getElementById("playerCoverWrap");
  const videoWrap = document.getElementById("playerVideoWrap");

  const setMediaMode = (mode) => {
    activeMediaMode = mode;
    if (btnCover) btnCover.classList.toggle("active", mode === "cover");
    if (btnVideo) btnVideo.classList.toggle("active", mode === "video");
    if (coverWrap) coverWrap.classList.toggle("hidden", mode !== "cover");
    if (videoWrap) videoWrap.classList.toggle("hidden", mode !== "video");

    if (mode === "video") {
      activateOfficialVideo();
    } else {
      deactivateOfficialVideo();
    }
  };

  if (btnCover) btnCover.addEventListener("click", () => setMediaMode("cover"));
  if (btnVideo) btnVideo.addEventListener("click", () => setMediaMode("video"));

  // Modal para personalizar cover o video
  const btnCustom = document.getElementById("btnChangeCustomCover");
  const customModal = document.getElementById("customMediaModal");
  const btnCloseModal = document.getElementById("btnCloseCustomMediaModal");
  const btnApplyCover = document.getElementById("btnApplyCustomCover");
  const btnApplyVideo = document.getElementById("btnApplyCustomVideo");

  if (btnCustom && customModal) {
    btnCustom.addEventListener("click", () => {
      customModal.classList.remove("hidden");
      const cInp = document.getElementById("customCoverUrlInput");
      if (cInp && activeTrack) cInp.value = activeTrack.cover_url || "";
    });
  }

  if (btnCloseModal && customModal) {
    btnCloseModal.addEventListener("click", () => customModal.classList.add("hidden"));
    customModal.addEventListener("click", (e) => {
      if (e.target === customModal) customModal.classList.add("hidden");
    });
  }

  // Subir archivo de imagen local
  const btnUploadCover = document.getElementById("btnUploadCoverFile");
  const inputCoverFile = document.getElementById("customCoverFileInput");

  if (btnUploadCover && inputCoverFile) {
    btnUploadCover.addEventListener("click", () => inputCoverFile.click());
    inputCoverFile.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        const base64 = ev.target.result;
        const cInp = document.getElementById("customCoverUrlInput");
        if (cInp) cInp.value = base64;
        await applyCoverPersistent(base64);
      };
      reader.readAsDataURL(file);
    });
  }

  async function applyCoverPersistent(coverData) {
    if (!coverData || !activeTrack) {
      showError("Sin Canción", "Reproduce primero una canción para cambiar su carátula.");
      return;
    }
    const btnApply = document.getElementById("btnApplyCustomCover");
    if (btnApply) {
      btnApply.disabled = true;
      btnApply.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
    }

    try {
      const res = await fetch(`${API_URL}/api/track/cover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          track_id: activeTrack.id,
          cover_url: coverData,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const finalUrl = data.cover_url || coverData;
        activeTrack.cover_url = finalUrl;
        const mainCover = document.getElementById("mainPlayerCover");
        if (mainCover) mainCover.src = finalUrl;
        adaptAmbientGlow(finalUrl);

        // Actualizar fila en la biblioteca si está visible
        const libRow = document.querySelector(`.lib-track-row[data-id="${activeTrack.id}"] img`);
        if (libRow) libRow.src = finalUrl;

        showToast("Carátula Guardada", "Guardada permanentemente en el archivo de la canción.");
        if (customModal) customModal.classList.add("hidden");
      } else {
        const err = await res.json().catch(() => ({}));
        showError("Error al Guardar", err.detail || "No se pudo actualizar la imagen.");
      }
    } catch (err) {
      showError("Error de Conexión", err.message);
    } finally {
      if (btnApply) {
        btnApply.disabled = false;
        btnApply.textContent = "Aplicar";
      }
    }
  }

  if (btnApplyCover) {
    btnApplyCover.addEventListener("click", () => {
      const url = document.getElementById("customCoverUrlInput").value.trim();
      if (url) applyCoverPersistent(url);
    });
  }

  if (btnApplyVideo) {
    btnApplyVideo.addEventListener("click", () => {
      const url = document.getElementById("customVideoUrlInput").value.trim();
      if (url) {
        const m = url.match(/(?:v=|\/embed\/|youtu\.be\/)([\w-]{11})/);
        if (m) {
          const vid = m[1];
          currentVideoInfo = {
            is_local_video: false,
            video_id: vid,
            embed_url: `https://www.youtube-nocookie.com/embed/${vid}?autoplay=1&enablejsapi=1&modestbranding=1`,
          };
          setMediaMode("video");
          showToast("Video Vinculado", "Reproduciendo video oficial en HD.");
          if (customModal) customModal.classList.add("hidden");
        } else {
          showError("Enlace Inválido", "Ingresa una URL válida de YouTube.");
        }
      }
    });
  }
}

async function fetchAndDisplayVideo(track) {
  const iframe = document.getElementById("mainOfficialVideoIframe");
  const localPlayer = document.getElementById("mainOfficialVideoPlayer");
  const hint = document.getElementById("videoLoadingHint");

  currentVideoInfo = null;
  if (iframe) { iframe.src = ""; iframe.classList.add("hidden"); }
  if (localPlayer) { localPlayer.pause(); localPlayer.src = ""; localPlayer.classList.add("hidden"); }
  if (hint) hint.classList.remove("hidden");

  try {
    const params = new URLSearchParams({
      title: track.title || "",
      artist: track.artist || "",
      track_id: track.id || "",
    });
    const res = await fetch(`${API_URL}/api/video-info?${params}`);
    if (res.ok) {
      const data = await res.json();
      currentVideoInfo = data;
      if (activeMediaMode === "video") {
        activateOfficialVideo();
      }
    }
  } catch (e) {
  } finally {
    if (hint) hint.classList.add("hidden");
  }
}

function activateOfficialVideo() {
  const iframe = document.getElementById("mainOfficialVideoIframe");
  const localPlayer = document.getElementById("mainOfficialVideoPlayer");
  const hint = document.getElementById("videoLoadingHint");

  if (!currentVideoInfo) {
    if (activeTrack) fetchAndDisplayVideo(activeTrack);
    return;
  }

  // Pausar audio principal para que no se duplique el sonido
  if (activeAudio && !activeAudio.paused) {
    activeAudio.pause();
    setPlayPauseUI(false);
  }

  if (currentVideoInfo.is_local_video) {
    if (localPlayer) {
      localPlayer.src = currentVideoInfo.stream_url;
      localPlayer.classList.remove("hidden");
      localPlayer.play().catch(() => {});
    }
  } else if (currentVideoInfo.embed_url) {
    if (iframe) {
      iframe.src = currentVideoInfo.embed_url;
      iframe.classList.remove("hidden");
    }
  } else {
    if (hint) {
      hint.innerHTML = `<i class="fa-solid fa-film"></i><h4>Video no disponible</h4><p>Toca en 'Editar' para pegar un enlace de YouTube.</p>`;
      hint.classList.remove("hidden");
    }
  }
}

function deactivateOfficialVideo() {
  const iframe = document.getElementById("mainOfficialVideoIframe");
  const localPlayer = document.getElementById("mainOfficialVideoPlayer");
  if (iframe) { iframe.src = ""; iframe.classList.add("hidden"); }
  if (localPlayer) { localPlayer.pause(); localPlayer.classList.add("hidden"); }

  // Reanudar audio normal
  if (activeAudio && isAudioPlaying && activeAudio.paused) {
    activeAudio.play().catch(() => {});
    setPlayPauseUI(true);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MÓDULO 2: CALIBRADOR DE DESFASE DE LETRAS SINCRONIZADAS (+/- 0.5s)
// ─────────────────────────────────────────────────────────────────────────────
let trackLyricsOffset = 0.0;

function setupLyricsOffsetControls() {
  const btnMinus = document.getElementById("btnLyricMinus");
  const btnPlus = document.getElementById("btnLyricPlus");
  const btnReset = document.getElementById("btnLyricReset");
  const offsetDisp = document.getElementById("lyricOffsetDisplay");

  const applyOffsetChange = async (delta) => {
    trackLyricsOffset = Math.round((trackLyricsOffset + delta) * 10) / 10;
    if (offsetDisp) {
      offsetDisp.textContent = `${trackLyricsOffset >= 0 ? "+" : ""}${trackLyricsOffset.toFixed(1)}s`;
    }

    if (activeAudio) {
      syncLyricsWithTime(activeAudio.currentTime);
    }

    if (activeTrack && activeTrack.id) {
      try {
        await fetch(`${API_URL}/api/lyrics/offset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track_id: activeTrack.id, offset: trackLyricsOffset }),
        });
      } catch (e) {}
    }
  };

  if (btnMinus) btnMinus.addEventListener("click", () => applyOffsetChange(-0.5));
  if (btnPlus) btnPlus.addEventListener("click", () => applyOffsetChange(+0.5));
  if (btnReset) btnReset.addEventListener("click", () => {
    trackLyricsOffset = 0.0;
    if (offsetDisp) offsetDisp.textContent = "0.0s";
    if (activeAudio) syncLyricsWithTime(activeAudio.currentTime);
    if (activeTrack && activeTrack.id) {
      fetch(`${API_URL}/api/lyrics/offset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: activeTrack.id, offset: 0.0 }),
      }).catch(() => {});
    }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// MÓDULO 3: CONSOLA DJ APPLE PRO (DDJ-ARACHIZ DUAL DECK & WEB AUDIO FX)
// ─────────────────────────────────────────────────────────────────────────────
const DjEngine = {
  ctx: null,
  deckA: {
    audio: null,
    srcNode: null,
    eqLow: null,
    eqMid: null,
    eqHigh: null,
    gainNode: null,
    analyser: null,
    track: null,
    isPlaying: false,
    bpm: 128.0,
    loopInterval: null,
  },
  deckB: {
    audio: null,
    srcNode: null,
    eqLow: null,
    eqMid: null,
    eqHigh: null,
    gainNode: null,
    analyser: null,
    track: null,
    isPlaying: false,
    bpm: 128.0,
    loopInterval: null,
  },
  masterGain: null,
  crossfaderVal: 0.5,
  isInitialized: false,

  ensureContext() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
    }
    if (this.ctx.state === "suspended") {
      this.ctx.resume();
    }
  },

  init() {
    if (this.isInitialized) return;
    this.ensureContext();

    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = 1.0;
    this.masterGain.connect(this.ctx.destination);

    // Configurar Deck A
    this.deckA.audio = document.getElementById("deckAAudioElement");
    if (this.deckA.audio) {
      this.deckA.srcNode = this.ctx.createMediaElementSource(this.deckA.audio);
      this.deckA.eqLow = this.ctx.createBiquadFilter();
      this.deckA.eqLow.type = "lowshelf";
      this.deckA.eqLow.frequency.value = 320;

      this.deckA.eqMid = this.ctx.createBiquadFilter();
      this.deckA.eqMid.type = "peaking";
      this.deckA.eqMid.frequency.value = 1200;
      this.deckA.eqMid.Q.value = 1.0;

      this.deckA.eqHigh = this.ctx.createBiquadFilter();
      this.deckA.eqHigh.type = "highshelf";
      this.deckA.eqHigh.frequency.value = 3200;

      this.deckA.gainNode = this.ctx.createGain();
      this.deckA.analyser = this.ctx.createAnalyser();
      this.deckA.analyser.fftSize = 64;

      this.deckA.srcNode
        .connect(this.deckA.eqLow)
        .connect(this.deckA.eqMid)
        .connect(this.deckA.eqHigh)
        .connect(this.deckA.gainNode)
        .connect(this.deckA.analyser)
        .connect(this.masterGain);
    }

    // Configurar Deck B
    this.deckB.audio = document.getElementById("deckBAudioElement");
    if (this.deckB.audio) {
      this.deckB.srcNode = this.ctx.createMediaElementSource(this.deckB.audio);
      this.deckB.eqLow = this.ctx.createBiquadFilter();
      this.deckB.eqLow.type = "lowshelf";
      this.deckB.eqLow.frequency.value = 320;

      this.deckB.eqMid = this.ctx.createBiquadFilter();
      this.deckB.eqMid.type = "peaking";
      this.deckB.eqMid.frequency.value = 1200;
      this.deckB.eqMid.Q.value = 1.0;

      this.deckB.eqHigh = this.ctx.createBiquadFilter();
      this.deckB.eqHigh.type = "highshelf";
      this.deckB.eqHigh.frequency.value = 3200;

      this.deckB.gainNode = this.ctx.createGain();
      this.deckB.analyser = this.ctx.createAnalyser();
      this.deckB.analyser.fftSize = 64;

      this.deckB.srcNode
        .connect(this.deckB.eqLow)
        .connect(this.deckB.eqMid)
        .connect(this.deckB.eqHigh)
        .connect(this.deckB.gainNode)
        .connect(this.deckB.analyser)
        .connect(this.masterGain);
    }

    this.updateCrossfader(0.5);
    this.startVuMeters();
    this.isInitialized = true;
  },

  updateCrossfader(val) {
    this.crossfaderVal = Math.max(0, Math.min(1, val));
    if (!this.deckA.gainNode || !this.deckB.gainNode) return;

    // Curva de igual poder Apple Pro
    const gainA = Math.cos(this.crossfaderVal * 0.5 * Math.PI);
    const gainB = Math.sin(this.crossfaderVal * 0.5 * Math.PI);

    const faderA = parseFloat(document.getElementById("deckAVolume")?.value || 0.9);
    const faderB = parseFloat(document.getElementById("deckBVolume")?.value || 0.9);

    this.deckA.gainNode.gain.setValueAtTime(gainA * faderA, this.ctx?.currentTime || 0);
    this.deckB.gainNode.gain.setValueAtTime(gainB * faderB, this.ctx?.currentTime || 0);
  },

  loadTrack(deckKey, track) {
    this.ensureContext();
    const deck = deckKey === "a" ? this.deckA : this.deckB;
    deck.track = track;
    const streamUrl = track.stream_url || `${API_URL}/api/stream/${track.id}`;
    if (deck.audio) {
      deck.audio.src = streamUrl;
      deck.audio.load();
    }

    const titleEl = document.getElementById(deckKey === "a" ? "djDeckATitle" : "djDeckBTitle");
    const artistEl = document.getElementById(deckKey === "a" ? "djDeckAArtist" : "djDeckBArtist");
    const coverEl = document.getElementById(deckKey === "a" ? "deckACover" : "deckBCover");

    if (titleEl) titleEl.textContent = track.title || "Pista cargada";
    if (artistEl) artistEl.textContent = track.artist || "Artista";
    if (coverEl) coverEl.src = getTrackCoverSrc(track);

    showToast(`Deck ${deckKey.toUpperCase()} Listo`, `Cargada: ${track.title}`);
  },

  togglePlay(deckKey) {
    this.ensureContext();
    const deck = deckKey === "a" ? this.deckA : this.deckB;
    const btnPlay = document.getElementById(deckKey === "a" ? "btnDeckAPlay" : "btnDeckBPlay");
    const jog = document.getElementById(deckKey === "a" ? "deckAJogWheel" : "deckBJogWheel");

    if (!deck.audio || !deck.audio.src) {
      showError("Deck Vacío", `Carga primero una canción en el Deck ${deckKey.toUpperCase()}.`);
      return;
    }

    if (deck.audio.paused) {
      deck.audio.play().catch(() => {});
      deck.isPlaying = true;
      if (btnPlay) {
        btnPlay.classList.add("playing");
        btnPlay.innerHTML = `<i class="fa-solid fa-pause"></i>`;
      }
      if (jog) jog.classList.add("spin-deck");
    } else {
      deck.audio.pause();
      deck.isPlaying = false;
      if (btnPlay) {
        btnPlay.classList.remove("playing");
        btnPlay.innerHTML = `<i class="fa-solid fa-play"></i>`;
      }
      if (jog) jog.classList.remove("spin-deck");
    }
  },

  cue(deckKey) {
    const deck = deckKey === "a" ? this.deckA : this.deckB;
    if (deck.audio) {
      deck.audio.currentTime = 0;
      if (!deck.isPlaying) deck.audio.pause();
    }
  },

  syncBpm() {
    // Alínea el tempo del Deck B con el Deck A
    if (this.deckA.audio && this.deckB.audio) {
      this.deckB.audio.playbackRate = this.deckA.audio.playbackRate;
      const pitchSlider = document.getElementById("deckBPitch");
      if (pitchSlider) pitchSlider.value = this.deckA.audio.playbackRate;
      const bpmDisp = document.getElementById("deckBBpmDisplay");
      if (bpmDisp) bpmDisp.textContent = `${(128 * this.deckA.audio.playbackRate).toFixed(1)} BPM`;
      showToast("BPM SYNC", "Tempo del Deck B alineado con Deck A.");
    }
  },

  startVuMeters() {
    const dataA = new Uint8Array(32);
    const dataB = new Uint8Array(32);
    const ledsA = document.getElementById("deckALeds")?.querySelectorAll(".led-dot") || [];
    const ledsB = document.getElementById("deckBLeds")?.querySelectorAll(".led-dot") || [];

    const loop = () => {
      if (this.deckA.analyser && this.deckA.isPlaying) {
        this.deckA.analyser.getByteFrequencyData(dataA);
        const avgA = dataA.reduce((sum, v) => sum + v, 0) / dataA.length;
        const levelA = Math.min(5, Math.floor((avgA / 180) * 5));
        ledsA.forEach((led, i) => led.classList.toggle("on", i < levelA));
      } else {
        ledsA.forEach((led) => led.classList.remove("on"));
      }

      if (this.deckB.analyser && this.deckB.isPlaying) {
        this.deckB.analyser.getByteFrequencyData(dataB);
        const avgB = dataB.reduce((sum, v) => sum + v, 0) / dataB.length;
        const levelB = Math.min(5, Math.floor((avgB / 180) * 5));
        ledsB.forEach((led, i) => led.classList.toggle("on", i < levelB));
      } else {
        ledsB.forEach((led) => led.classList.remove("on"));
      }

      requestAnimationFrame(loop);
    };
    loop();
  },

  // 8 Sound FX Pads: Sintetizadores de audio Web Audio instantáneos
  playFx(fxName) {
    this.ensureContext();
    const ctx = this.ctx;
    const now = ctx.currentTime;

    const padBtn = document.querySelector(`.dj-fx-pad[data-fx="${fxName}"]`);
    if (padBtn) {
      padBtn.classList.add("pad-pressed");
      setTimeout(() => padBtn.classList.remove("pad-pressed"), 180);
    }

    if (fxName === "horn") {
      // Bocina Air Horn DJ (2 ondas saw desafinadas con modulación)
      [466.16, 472.0].forEach((freq) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(freq, now);

        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.35, now + 0.03);
        gain.gain.setValueAtTime(0.35, now + 0.15);
        gain.gain.linearRampToValueAtTime(0, now + 0.18);
        gain.gain.linearRampToValueAtTime(0.4, now + 0.22);
        gain.gain.linearRampToValueAtTime(0, now + 0.6);

        osc.connect(gain).connect(this.masterGain);
        osc.start(now);
        osc.stop(now + 0.65);
      });
    } else if (fxName === "drop") {
      // Sub Bass Drop (Onda senoidal 130Hz -> 35Hz)
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(130, now);
      osc.frequency.exponentialRampToValueAtTime(35, now + 1.2);

      gain.gain.setValueAtTime(0.7, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 1.2);

      osc.connect(gain).connect(this.masterGain);
      osc.start(now);
      osc.stop(now + 1.25);
    } else if (fxName === "siren") {
      // Sirena Rave Sweep
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(600, now);
      osc.frequency.linearRampToValueAtTime(1200, now + 0.3);
      osc.frequency.linearRampToValueAtTime(600, now + 0.6);
      osc.frequency.linearRampToValueAtTime(1200, now + 0.9);

      gain.gain.setValueAtTime(0.4, now);
      gain.gain.linearRampToValueAtTime(0, now + 1.0);

      osc.connect(gain).connect(this.masterGain);
      osc.start(now);
      osc.stop(now + 1.05);
    } else if (fxName === "laser") {
      // Laser Zap
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(1800, now);
      osc.frequency.exponentialRampToValueAtTime(60, now + 0.22);

      gain.gain.setValueAtTime(0.5, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.22);

      osc.connect(gain).connect(this.masterGain);
      osc.start(now);
      osc.stop(now + 0.25);
    } else if (fxName === "kick") {
      // Bombo Punchy Kick
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(150, now);
      osc.frequency.exponentialRampToValueAtTime(45, now + 0.25);

      gain.gain.setValueAtTime(0.8, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

      osc.connect(gain).connect(this.masterGain);
      osc.start(now);
      osc.stop(now + 0.26);
    } else if (fxName === "clap") {
      // Clap Trap (Pulsos de ruido blanco)
      const bufferSize = ctx.sampleRate * 0.25;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

      const noise = ctx.createBufferSource();
      noise.buffer = buffer;

      const filter = ctx.createBiquadFilter();
      filter.type = "bandpass";
      filter.frequency.value = 1100;
      filter.Q.value = 3;

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.6, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.2);

      noise.connect(filter).connect(gain).connect(this.masterGain);
      noise.start(now);
      noise.stop(now + 0.22);
    } else if (fxName === "sweep") {
      // Filter Riser Sweep
      const bufferSize = ctx.sampleRate * 0.8;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

      const noise = ctx.createBufferSource();
      noise.buffer = buffer;

      const filter = ctx.createBiquadFilter();
      filter.type = "bandpass";
      filter.frequency.setValueAtTime(200, now);
      filter.frequency.exponentialRampToValueAtTime(4000, now + 0.75);
      filter.Q.value = 5;

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.5, now);
      gain.gain.linearRampToValueAtTime(0, now + 0.8);

      noise.connect(filter).connect(gain).connect(this.masterGain);
      noise.start(now);
      noise.stop(now + 0.82);
    } else if (fxName === "brake") {
      // Vinyl Stop Brake (Frenado realista de motor de tocadiscos)
      const targetAudio = this.deckA.isPlaying ? this.deckA.audio : this.deckB.audio;
      if (targetAudio && !targetAudio.paused) {
        const origRate = targetAudio.playbackRate;
        const steps = 15;
        let step = 0;
        const interval = setInterval(() => {
          step++;
          targetAudio.playbackRate = Math.max(0.05, origRate * (1 - step / steps));
          if (step >= steps) {
            clearInterval(interval);
            targetAudio.pause();
            targetAudio.playbackRate = origRate;
            if (this.deckA.isPlaying) DjEngine.togglePlay("a");
            else DjEngine.togglePlay("b");
          }
        }, 35);
      }
    }
  },
};

function setupDjConsole() {
  // Inicialización de la consola al interactuar
  const chassis = document.querySelector(".dj-console-chassis");
  if (chassis) {
    chassis.addEventListener("click", () => DjEngine.init(), { once: true });
  }

  // Carga de Canciones en Decks desde la Biblioteca
  const selectA = document.getElementById("djDeckATrackSelect");
  const selectB = document.getElementById("djDeckBTrackSelect");

  const populateDjSelectors = () => {
    const tracks = libraryData.tracks || [];
    if (selectA) {
      selectA.innerHTML = `<option value="">-- Cargar Canción en Deck A --</option>` +
        tracks.map((t) => `<option value="${t.id}">${escapeHtml(t.title)} - ${escapeHtml(t.artist)}</option>`).join("");
    }
    if (selectB) {
      selectB.innerHTML = `<option value="">-- Cargar Canción en Deck B --</option>` +
        tracks.map((t) => `<option value="${t.id}">${escapeHtml(t.title)} - ${escapeHtml(t.artist)}</option>`).join("");
    }
  };

  if (selectA) {
    selectA.addEventListener("change", (e) => {
      const trackId = e.target.value;
      const track = (libraryData.tracks || []).find((t) => t.id === trackId);
      if (track) DjEngine.loadTrack("a", track);
    });
  }

  if (selectB) {
    selectB.addEventListener("change", (e) => {
      const trackId = e.target.value;
      const track = (libraryData.tracks || []).find((t) => t.id === trackId);
      if (track) DjEngine.loadTrack("b", track);
    });
  }

  // Botones de Transporte (Play, Cue, Sync)
  document.getElementById("btnDeckAPlay")?.addEventListener("click", () => DjEngine.togglePlay("a"));
  document.getElementById("btnDeckBPlay")?.addEventListener("click", () => DjEngine.togglePlay("b"));
  document.getElementById("btnDeckACue")?.addEventListener("click", () => DjEngine.cue("a"));
  document.getElementById("btnDeckBCue")?.addEventListener("click", () => DjEngine.cue("b"));
  document.getElementById("btnDeckASync")?.addEventListener("click", () => DjEngine.syncBpm());
  document.getElementById("btnDeckBSync")?.addEventListener("click", () => DjEngine.syncBpm());
  document.getElementById("btnDjBpmSync")?.addEventListener("click", () => DjEngine.syncBpm());

  // Auto-Mix 4s
  document.getElementById("btnDjAutoMix")?.addEventListener("click", () => {
    DjEngine.ensureContext();
    const slider = document.getElementById("djCrossfaderSlider");
    if (!slider) return;
    const startVal = parseFloat(slider.value);
    const targetVal = startVal < 0.5 ? 1.0 : 0.0;
    const duration = 4000;
    const startTime = performance.now();

    const animateXFade = (now) => {
      const elapsed = now - startTime;
      const p = Math.min(1, elapsed / duration);
      // Smooth step
      const current = startVal + (targetVal - startVal) * (p * p * (3 - 2 * p));
      slider.value = current;
      DjEngine.updateCrossfader(current);
      if (p < 1) requestAnimationFrame(animateXFade);
      else showToast("Auto-Mix Completado", `Transición al Deck ${targetVal === 1 ? "B" : "A"}`);
    };
    requestAnimationFrame(animateXFade);
  });

  // Crossfader Slider & Quick Buttons
  const xfaderSlider = document.getElementById("djCrossfaderSlider");
  if (xfaderSlider) {
    xfaderSlider.addEventListener("input", (e) => DjEngine.updateCrossfader(parseFloat(e.target.value)));
  }
  document.getElementById("btnXFadeCutA")?.addEventListener("click", () => {
    if (xfaderSlider) { xfaderSlider.value = 0; DjEngine.updateCrossfader(0); }
  });
  document.getElementById("btnXFadeCenter")?.addEventListener("click", () => {
    if (xfaderSlider) { xfaderSlider.value = 0.5; DjEngine.updateCrossfader(0.5); }
  });
  document.getElementById("btnXFadeCutB")?.addEventListener("click", () => {
    if (xfaderSlider) { xfaderSlider.value = 1; DjEngine.updateCrossfader(1); }
  });

  // Master Volume
  document.getElementById("djMasterGain")?.addEventListener("input", (e) => {
    if (DjEngine.masterGain && DjEngine.ctx) {
      DjEngine.masterGain.gain.setValueAtTime(parseFloat(e.target.value), DjEngine.ctx.currentTime);
    }
  });

  // Channel Volume Faders
  document.getElementById("deckAVolume")?.addEventListener("input", () => DjEngine.updateCrossfader(DjEngine.crossfaderVal));
  document.getElementById("deckBVolume")?.addEventListener("input", () => DjEngine.updateCrossfader(DjEngine.crossfaderVal));

  // EQ Knobs Deck A
  const bindEq = (id, readId, filterKey, deck) => {
    const el = document.getElementById(id);
    const read = document.getElementById(readId);
    if (el) {
      el.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        if (read) read.textContent = `${val >= 0 ? "+" : ""}${val}dB`;
        if (deck[filterKey] && DjEngine.ctx) {
          deck[filterKey].gain.setValueAtTime(val, DjEngine.ctx.currentTime);
        }
      });
    }
  };

  bindEq("deckAEqHigh", "deckAEqHighVal", "eqHigh", DjEngine.deckA);
  bindEq("deckAEqMid", "deckAEqMidVal", "eqMid", DjEngine.deckA);
  bindEq("deckAEqLow", "deckAEqLowVal", "eqLow", DjEngine.deckA);

  bindEq("deckBEqHigh", "deckBEqHighVal", "eqHigh", DjEngine.deckB);
  bindEq("deckBEqMid", "deckBEqMidVal", "eqMid", DjEngine.deckB);
  bindEq("deckBEqLow", "deckBEqLowVal", "eqLow", DjEngine.deckB);

  // Pitch / Tempo Sliders
  const pitchA = document.getElementById("deckAPitch");
  if (pitchA) {
    pitchA.addEventListener("input", (e) => {
      const rate = parseFloat(e.target.value);
      if (DjEngine.deckA.audio) DjEngine.deckA.audio.playbackRate = rate;
      const bpmDisp = document.getElementById("deckABpmDisplay");
      if (bpmDisp) bpmDisp.textContent = `${(128 * rate).toFixed(1)} BPM`;
    });
  }

  const pitchB = document.getElementById("deckBPitch");
  if (pitchB) {
    pitchB.addEventListener("input", (e) => {
      const rate = parseFloat(e.target.value);
      if (DjEngine.deckB.audio) DjEngine.deckB.audio.playbackRate = rate;
      const bpmDisp = document.getElementById("deckBBpmDisplay");
      if (bpmDisp) bpmDisp.textContent = `${(128 * rate).toFixed(1)} BPM`;
    });
  }

  // Beat Loop Buttons
  document.querySelectorAll(".btn-loop-pad").forEach((btn) => {
    btn.addEventListener("click", () => {
      const deckKey = btn.dataset.deck;
      const beats = parseFloat(btn.dataset.beats || 1);
      const deck = deckKey === "a" ? DjEngine.deckA : DjEngine.deckB;
      btn.parentElement.querySelectorAll(".btn-loop-pad").forEach((b) => b.classList.remove("active-loop"));
      btn.classList.add("active-loop");

      if (deck.audio) {
        const loopDuration = (60 / (deck.bpm || 128)) * beats;
        const loopStart = deck.audio.currentTime;
        if (deck.loopInterval) clearInterval(deck.loopInterval);
        deck.loopInterval = setInterval(() => {
          if (deck.audio && deck.audio.currentTime >= loopStart + loopDuration) {
            deck.audio.currentTime = loopStart;
          }
        }, 50);
      }
    });
  });

  // 8 Performance SFX Pads
  document.querySelectorAll(".dj-fx-pad").forEach((pad) => {
    pad.addEventListener("click", () => {
      const fx = pad.dataset.fx;
      if (fx) DjEngine.playFx(fx);
    });
  });

  // Scratch en Platos Jog Wheel
  const setupScratch = (jogId, deckKey) => {
    const jog = document.getElementById(jogId);
    if (!jog) return;
    let isScratching = false;
    let lastX = 0;

    const onStart = (e) => {
      isScratching = true;
      lastX = e.clientX || (e.touches && e.touches[0].clientX);
      DjEngine.ensureContext();
    };

    const onMove = (e) => {
      if (!isScratching) return;
      const curX = e.clientX || (e.touches && e.touches[0].clientX);
      const delta = curX - lastX;
      lastX = curX;

      const deck = deckKey === "a" ? DjEngine.deckA : DjEngine.deckB;
      if (deck.audio && !isNaN(deck.audio.duration)) {
        deck.audio.currentTime = Math.max(0, Math.min(deck.audio.duration, deck.audio.currentTime + delta * 0.04));
      }
    };

    const onEnd = () => { isScratching = false; };

    jog.addEventListener("mousedown", onStart);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);

    jog.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd);
  };

  setupScratch("deckAJogWheel", "a");
  setupScratch("deckBJogWheel", "b");

  // Re-poblar selectores cuando la biblioteca se cargue (o si ya está disponible)
  window.addEventListener("arachiz_library_loaded", populateDjSelectors);
  // Si la biblioteca ya estaba cargada antes de que se initializara la consola:
  if (libraryData && (libraryData.tracks || []).length > 0) {
    populateDjSelectors();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MÓDULO 4: MODO OFFLINE & ALMACENAMIENTO LOCAL INDEXEDDB
// ─────────────────────────────────────────────────────────────────────────────
let isOfflineModeActive = false;

const OfflineStorage = {
  db: null,

  async init() {
    return new Promise((resolve) => {
      const req = indexedDB.open("ArachizOfflineDB", 1);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("tracks")) {
          db.createObjectStore("tracks", { keyPath: "id" });
        }
      };
      req.onsuccess = (e) => {
        this.db = e.target.result;
        resolve(this.db);
      };
      req.onerror = () => resolve(null);
    });
  },

  async saveTrack(track) {
    if (!this.db) await this.init();
    try {
      const res = await fetch(`${API_URL}/api/stream/${track.id}`);
      if (!res.ok) return false;
      const audioBlob = await res.blob();

      // Guardar también carátula en Base64 para 100% offline
      let offlineCover = "";
      if (track.cover_url) {
        try {
          const coverFullUrl = track.cover_url.startsWith("http") ? track.cover_url : `${API_URL}${track.cover_url}`;
          const cRes = await fetch(coverFullUrl);
          if (cRes.ok) {
            const cBlob = await cRes.blob();
            offlineCover = await new Promise((resCover) => {
              const reader = new FileReader();
              reader.onload = () => resCover(reader.result);
              reader.readAsDataURL(cBlob);
            });
          }
        } catch (e) {}
      }

      return new Promise((resolve) => {
        const tx = this.db.transaction("tracks", "readwrite");
        const store = tx.objectStore("tracks");
        store.put({
          id: track.id,
          title: track.title,
          artist: track.artist,
          album: track.album || track.playlist,
          duration: track.duration,
          cover_url: offlineCover || track.cover_url,
          audioBlob: audioBlob,
          cachedAt: Date.now(),
        });
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => resolve(false);
      });
    } catch (e) {
      return false;
    }
  },

  async getAllTracks() {
    if (!this.db) await this.init();
    return new Promise((resolve) => {
      const tx = this.db.transaction("tracks", "readonly");
      const store = tx.objectStore("tracks");
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => resolve([]);
    });
  },

  async getTrackBlobUrl(id) {
    if (!this.db) await this.init();
    return new Promise((resolve) => {
      const tx = this.db.transaction("tracks", "readonly");
      const store = tx.objectStore("tracks");
      const req = store.get(id);
      req.onsuccess = () => {
        if (req.result && req.result.audioBlob) {
          resolve(URL.createObjectURL(req.result.audioBlob));
        } else {
          resolve(null);
        }
      };
      req.onerror = () => resolve(null);
    });
  },
};

function setupOfflineManager() {
  OfflineStorage.init();

  const btnToggle = document.getElementById("btnToggleOffline");
  const icon = document.getElementById("navOfflineIcon");
  const label = document.getElementById("navOfflineLabel");

  if (btnToggle) {
    btnToggle.addEventListener("click", async () => {
      isOfflineModeActive = !isOfflineModeActive;
      btnToggle.classList.toggle("online", !isOfflineModeActive);
      btnToggle.classList.toggle("offline", isOfflineModeActive);

      if (isOfflineModeActive) {
        if (icon) icon.className = "fa-solid fa-plane";
        if (label) label.textContent = "Offline";
        showToast("Modo Offline Activado", "Reproduciendo directamente desde la memoria interna de este dispositivo.");
        loadOfflineTracks();
      } else {
        if (icon) icon.className = "fa-solid fa-wifi";
        if (label) label.textContent = "Online";
        showToast("Modo Online Activado", "Conectado al servidor de música.");
        loadLibrary();
      }
    });
  }

  // Guardar toda la biblioteca en la memoria de este celular o PC
  const btnSaveAll = document.getElementById("btnSaveAllOffline");
  if (btnSaveAll) {
    btnSaveAll.addEventListener("click", async () => {
      const tracks = libraryData.tracks || [];
      if (tracks.length === 0) {
        showError("Biblioteca Vacía", "No hay canciones para guardar.");
        return;
      }
      btnSaveAll.disabled = true;
      btnSaveAll.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Guardando...`;

      let saved = 0;
      for (const t of tracks) {
        const ok = await OfflineStorage.saveTrack(t);
        if (ok) saved++;
      }

      btnSaveAll.disabled = false;
      btnSaveAll.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> <span>Guardar en Celular (Offline)</span>`;
      showToast("Descarga Offline Lista", `${saved} canciones guardadas en el almacenamiento de este dispositivo.`);
    });
  }
}

async function loadOfflineTracks() {
  const offlineTracks = await OfflineStorage.getAllTracks();
  const container = document.getElementById("libTracksList");
  if (!container) return;

  if (offlineTracks.length === 0) {
    container.innerHTML = `
      <div class="lib-empty-notice">
        <i class="fa-solid fa-cloud-arrow-down"></i>
        <p>No tienes canciones guardadas para el Modo Offline.</p>
        <small>Toca 'Guardar en Celular (Offline)' cuando tengas conexión para escucharlas en la calle o avión.</small>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  offlineTracks.forEach((track, idx) => {
    const row = document.createElement("div");
    row.className = "lib-track-row";
    row.innerHTML = `
      <div class="col-index">
        <button class="btn-play-mini-row" title="Reproducir"><i class="fa-solid fa-play"></i></button>
      </div>
      <div class="col-title lib-track-cell-title">
        <img src="${getTrackCoverSrc(track)}" class="lib-track-mini-thumb" alt="Cover" />
        <span>${escapeHtml(track.title)}</span>
      </div>
      <div class="col-artist">${escapeHtml(track.artist)}</div>
      <div class="col-album"><span class="badge-status-synced">Memoria Celular</span></div>
      <div class="col-duration tabular">${track.duration}</div>
      <div class="col-actions">
        <button class="btn-pill-micro btn-lib-play" title="Reproducir"><i class="fa-solid fa-play"></i></button>
      </div>
    `;

    const playOffline = async () => {
      const blobUrl = await OfflineStorage.getTrackBlobUrl(track.id);
      if (blobUrl && activeAudio) {
        track.stream_url = blobUrl;
        currentQueue = offlineTracks;
        playTrack(track, idx);
      }
    };

    row.querySelector(".btn-play-mini-row").addEventListener("click", playOffline);
    row.querySelector(".btn-lib-play").addEventListener("click", playOffline);
    row.addEventListener("dblclick", playOffline);
    container.appendChild(row);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// MÓDULO 5: PERFILES MULTIDISPOSITIVO (IPHONE, SAMSUNG, PC PRINCIPAL)
// ─────────────────────────────────────────────────────────────────────────────
let activeProfileId = localStorage.getItem("arachiz_profile_id") || "pc_principal";

const ProfileManager = {
  data: {
    favorites: [],
    playlists: {},
    history: [],
  },

  async init() {
    this.updateHeaderBadge();
    await this.loadProfileData();

    const btnSelector = document.getElementById("btnProfileSelector");
    const modal = document.getElementById("profileModal");
    const btnClose = document.getElementById("btnCloseProfileModal");
    const btnCreate = document.getElementById("btnCreateProfile");

    if (btnSelector && modal) {
      btnSelector.addEventListener("click", () => {
        this.renderProfilesList();
        this.updateStatsDisplay();
        modal.classList.remove("hidden");
      });
    }

    if (btnClose && modal) {
      btnClose.addEventListener("click", () => modal.classList.add("hidden"));
      modal.addEventListener("click", (e) => {
        if (e.target === modal) modal.classList.add("hidden");
      });
    }

    if (btnCreate) {
      btnCreate.addEventListener("click", async () => {
        const inp = document.getElementById("newProfileNameInput");
        const name = inp ? inp.value.trim() : "";
        if (!name) return;
        try {
          const res = await fetch(`${API_URL}/api/profiles/create`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
          if (res.ok) {
            const data = await res.json();
            activeProfileId = data.id || data.profile_id;
            localStorage.setItem("arachiz_profile_id", activeProfileId);
            this.updateHeaderBadge();
            await this.loadProfileData();
            this.renderProfilesList();
            showToast("Perfil Creado", `Bienvenido a ${name}. Tus canciones y listas se guardan aquí.`);
            if (inp) inp.value = "";
          }
        } catch (e) {}
      });
    }
  },

  async loadProfileData() {
    try {
      const res = await fetch(`${API_URL}/api/profile/${activeProfileId}`);
      if (res.ok) {
        this.data = await res.json();
        this.updateStatsDisplay();
      }
    } catch (e) {
      console.warn("Could not load profile data:", e);
    }
  },

  async saveProfileData() {
    try {
      await fetch(`${API_URL}/api/profile/${activeProfileId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          favorites: this.data.favorites || [],
          playlists: this.data.playlists || {},
          history: this.data.history || [],
        }),
      });
      this.updateStatsDisplay();
    } catch (e) {}
  },

  isFavorite(trackId) {
    return (this.data.favorites || []).includes(trackId);
  },

  async toggleFavorite(trackId) {
    if (!this.data.favorites) this.data.favorites = [];
    const idx = this.data.favorites.indexOf(trackId);
    if (idx >= 0) {
      this.data.favorites.splice(idx, 1);
      showToast("Favoritos", "Canción eliminada de favoritos en este perfil.");
    } else {
      this.data.favorites.push(trackId);
      showToast("Favoritos", "Canción agregada a tus favoritos en este perfil.");
    }
    await this.saveProfileData();
  },

  updateStatsDisplay() {
    const statsEl = document.getElementById("modalProfileStats");
    if (statsEl) {
      const favs = (this.data.favorites || []).length;
      const pls = Object.keys(this.data.playlists || {}).length;
      statsEl.textContent = `${favs} favoritas • ${pls} listas en este perfil`;
    }
  },

  updateHeaderBadge() {
    const el = document.getElementById("navProfileName");
    const modalActive = document.getElementById("modalProfileActiveName");
    const prettyName = activeProfileId.replace(/^p_\d+_\d+_?/, "").replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()) || "Mi Dispositivo";
    if (el) el.textContent = prettyName;
    if (modalActive) modalActive.textContent = prettyName;
  },

  async renderProfilesList() {
    const container = document.getElementById("profilesListContainer");
    if (!container) return;
    try {
      const res = await fetch(`${API_URL}/api/profiles`);
      if (res.ok) {
        const list = await res.json();
        container.innerHTML = list.map((p) => `
          <button class="profile-pill-item ${p.id === activeProfileId ? "active" : ""}" data-id="${p.id}">
            <i class="fa-solid ${p.icon || 'fa-mobile-screen'}"></i>
            <span>${escapeHtml(p.name)}</span>
          </button>
        `).join("");

        container.querySelectorAll(".profile-pill-item").forEach((btn) => {
          btn.addEventListener("click", async () => {
            activeProfileId = btn.dataset.id;
            localStorage.setItem("arachiz_profile_id", activeProfileId);
            this.updateHeaderBadge();
            await this.loadProfileData();
            this.renderProfilesList();
            showToast("Perfil Cambiado", `Sesión activa para ${btn.textContent.trim()}.`);
          });
        });
      }
    } catch (e) {}
  },
};

function setupProfileManager() {
  ProfileManager.init();
}

