# Registra las dos tareas programadas de Windows que mantienen vivo el radar.
#
#   RadarInmobiliario-Rapido    cada hora, de 08:00 a 22:00 -> anuncios nuevos
#   RadarInmobiliario-Completo  todos los dias a las 03:15  -> precios y bajas
#
# Ejecutar desde esta carpeta:   powershell -ExecutionPolicy Bypass -File instalar-tareas.ps1
# Para desinstalarlas:           powershell -ExecutionPolicy Bypass -File instalar-tareas.ps1 -Desinstalar

param([switch]$Desinstalar)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path

$tareas = @(
    @{ Nombre = "RadarInmobiliario-Rapido"
       Script = Join-Path $raiz "vigilar.bat"
       Desc   = "Busca anuncios nuevos en Huelva y Sevilla y avisa por Telegram" },
    @{ Nombre = "RadarInmobiliario-Completo"
       Script = Join-Path $raiz "vigilar-completo.bat"
       Desc   = "Barrido completo: cambios de precio y anuncios retirados" }
)

if ($Desinstalar) {
    foreach ($t in $tareas) {
        try {
            Unregister-ScheduledTask -TaskName $t.Nombre -Confirm:$false -ErrorAction Stop
            Write-Host "Eliminada: $($t.Nombre)"
        } catch {
            Write-Host "No estaba registrada: $($t.Nombre)"
        }
    }
    return
}

# --- comprobaciones previas ---------------------------------------------------
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Falta el entorno virtual. Ejecuta primero: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}
$envFile = Join-Path $raiz ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning "No existe .env: el radar funcionara pero no podra avisarte por Telegram."
    Write-Warning "Copia .env.example a .env y ejecuta: python run.py telegram-setup"
}

# --- tarea rapida: cada hora, en horario razonable -----------------------------
$accionRapida = New-ScheduledTaskAction -Execute $tareas[0].Script -WorkingDirectory $raiz
$disparoRapido = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(8) `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 14)

# --- tarea completa: de madrugada, cuando los portales estan tranquilos --------
$accionCompleta = New-ScheduledTaskAction -Execute $tareas[1].Script -WorkingDirectory $raiz
$disparoCompleto = New-ScheduledTaskTrigger -Daily -At "03:15"

# Si el equipo estaba apagado a la hora prevista, que se ejecute al encenderlo.
$ajustes = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $tareas[0].Nombre -Action $accionRapida `
    -Trigger $disparoRapido -Settings $ajustes -Description $tareas[0].Desc -Force | Out-Null
Write-Host "Registrada: $($tareas[0].Nombre)  (cada hora, 08:00-22:00)"

Register-ScheduledTask -TaskName $tareas[1].Nombre -Action $accionCompleta `
    -Trigger $disparoCompleto -Settings $ajustes -Description $tareas[1].Desc -Force | Out-Null
Write-Host "Registrada: $($tareas[1].Nombre)  (diaria, 03:15)"

Write-Host ""
Write-Host "Listo. Comprueba el estado cuando quieras con:"
Write-Host "    .venv\Scripts\python.exe run.py estado"
Write-Host "El registro de ejecuciones se va escribiendo en data\radar.log"
