@echo off
REM Barrido rapido: busca anuncios nuevos y avisa por Telegram.
REM Es el que ejecuta la tarea programada cada hora.
cd /d "%~dp0"
".venv\Scripts\python.exe" run.py vigilar >> "data\radar.log" 2>&1
