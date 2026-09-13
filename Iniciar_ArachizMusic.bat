@echo off
title Arachiz Music v3.0 - Apple Liquid Glass Sound Studio & Player
color 0b
chcp 65001 > nul

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║          ARACHIZ MUSIC v3.0  -  Sound Studio         ║
echo  ║     Reproductor · Letras Sincronizadas · PWA Móvil   ║
echo  ║     IA Mood · Estudio de Audio · Spotify & YouTube   ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Verificar que Python esté instalado
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python no está instalado o no está en el PATH.
    echo  Descárgalo de: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  [1/3] Verificando dependencias...
python -m pip install -r "%~dp0requirements.txt" --quiet --upgrade
if %errorlevel% neq 0 (
    echo  [WARN] Algunas dependencias pueden no haberse instalado correctamente.
)

echo  [2/3] Dependencias verificadas.
echo  [3/3] Iniciando servidor en http://127.0.0.1:5555 ...
echo.
echo  Para cerrar Arachiz Music, cierra esta ventana o presiona Ctrl+C
echo.

:: Liberar puerto 5555 si quedó ocupado por una sesión previa
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5555" ^| find "LISTENING"') do (
    taskkill /f /pid %%a > nul 2>&1
)

:: Esperar 1 segundo y abrir el navegador
timeout /t 1 /nobreak > nul
start "" http://127.0.0.1:5555

:: Iniciar el servidor
cd /d "%~dp0backend"
python server.py

echo.
echo  Servidor detenido.
pause
