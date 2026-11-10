# =====================================================================
# Crea el archivo .env con todas las contrasenas listas (Windows).
# Uso, en PowerShell dentro de la carpeta hotel-soluna:
#     powershell -ExecutionPolicy Bypass -File .\crear-env.ps1
# Si ya existe un .env, lo guarda como .env.anterior antes de reemplazarlo.
# =====================================================================
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Aleatorio {
    # 48 caracteres hexadecimales al azar
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

if (Test-Path .env) {
    Copy-Item .env .env.anterior -Force
    Write-Host "Habia un .env: se guardo una copia en .env.anterior"
}

$fecha = Get-Date -Format 'dd/MM/yyyy HH:mm'
$lineas = @(
    "# Creado por crear-env.ps1 el $fecha. No se sube al repositorio."
    "POSTGRES_PASSWORD=$(Aleatorio)"
    "DB_APP_PASSWORD=$(Aleatorio)"
    "DB_RESPALDO_PASSWORD=$(Aleatorio)"
    "JWT_SECRET=$(Aleatorio)"
    "DEMO_PASSWORD=SolunaDemo2026"
    "SERVICIOS_LLAVE=$(Aleatorio)"
    "OTA_SECRETO=$(Aleatorio)"
)
# Sin BOM y con finales LF, como lo espera Docker Compose
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), (($lineas -join "`n") + "`n"))

Write-Host ""
Write-Host "Listo: .env creado con todas las contrasenas."
Write-Host "Contrasena de las cuentas de demostracion: SolunaDemo2026"
Write-Host ""
Write-Host "Ahora ejecute:"
Write-Host "  docker compose down -v"
Write-Host "  docker compose up --build -d"
Write-Host "  docker compose exec api python -m app.seed"
