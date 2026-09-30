@echo off
REM Barrido completo: recorre todo el catalogo. Detecta cambios de precio
REM y anuncios retirados, ademas de los nuevos. Tarda bastante mas.
REM Es el que ejecuta la tarea programada una vez al dia.
cd /d "%~dp0"
".venv\Scripts\python.exe" run.py vigilar --completo >> "data\radar.log" 2>&1
