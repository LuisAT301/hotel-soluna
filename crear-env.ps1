# =====================================================================
# Crea el archivo .env con todas las contrasenas listas (Windows).
# Uso, en PowerShell dentro de la carpeta hotel-soluna:
#     powershell -ExecutionPolicy Bypass -File .\crear-env.ps1
# Pregunta si la base de datos estara en Supabase o en Docker (local).
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

function Guardar($ruta, $lineas) {
    # Sin BOM y con finales LF, como lo espera Docker Compose
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot $ruta), (($lineas -join "`n") + "`n"))
}

Write-Host "Donde estara la base de datos?"
Write-Host "  1) En Docker, en este equipo (recomendado para empezar)"
Write-Host "  2) En Supabase"
$opcion = Read-Host "Elija 1 o 2 [1]"

$supabaseRef = ''
$supabaseHost = ''
if ($opcion -eq '2') {
    Write-Host ""
    Write-Host "En el panel de Supabase pulse 'Connect', elija 'Session pooler' y copie la cadena"
    Write-Host "de conexion. Se ve asi (no hace falta poner la contrasena):"
    Write-Host "  postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-us-east-2.pooler.supabase.com:5432/postgres"
    $cadena = Read-Host "Pegue la cadena aqui"
    if ($cadena -match 'postgres\.([a-z0-9]+)[:@]') { $supabaseRef = $Matches[1] }
    if ($cadena -match '@([^:/]+)') { $supabaseHost = $Matches[1] }
    if (-not $supabaseRef -or -not $supabaseHost) {
        Write-Host "No se reconocio la cadena. Verifique que sea la de 'Session pooler' y vuelva a ejecutar el script."
        exit 1
    }
}

if (Test-Path .env) {
    Copy-Item .env .env.anterior -Force
    Write-Host "Habia un .env: se guardo una copia en .env.anterior"
}

$appPass = Aleatorio
$respaldoPass = Aleatorio
$fecha = Get-Date -Format 'dd/MM/yyyy HH:mm'
$lineas = @(
    "# Creado por crear-env.ps1 el $fecha. No se sube al repositorio."
    "POSTGRES_PASSWORD=$(Aleatorio)"
    "DB_APP_PASSWORD=$appPass"
    "DB_RESPALDO_PASSWORD=$respaldoPass"
    "JWT_SECRET=$(Aleatorio)"
    "DEMO_PASSWORD=SolunaDemo2026"
    "SERVICIOS_LLAVE=$(Aleatorio)"
    "OTA_SECRETO=$(Aleatorio)"
)
if ($opcion -eq '2') {
    # En Windows, Docker Compose separa la lista de archivos con punto y coma
    $lineas += @(
        ""
        "# Base de datos en Supabase"
        "SUPABASE_REF=$supabaseRef"
        "SUPABASE_HOST=$supabaseHost"
        "COMPOSE_FILE=docker-compose.yml;docker-compose.supabase.yml"
    )
    Guardar 'activar-roles-supabase.sql' @(
        "-- Copie todo este archivo en el SQL Editor de Supabase y pulse Run."
        "-- Activa los usuarios de la API y de respaldos con las contrasenas del .env."
        "-- Este archivo tiene contrasenas: no lo comparta (Git ya lo ignora)."
        "ALTER ROLE app_hotel WITH LOGIN PASSWORD '$appPass';"
        "ALTER ROLE respaldo  WITH LOGIN PASSWORD '$respaldoPass';"
    )
}
Guardar '.env' $lineas

Write-Host ""
Write-Host "Listo: .env creado con todas las contrasenas."
Write-Host "Contrasena de las cuentas de demostracion: SolunaDemo2026"
Write-Host ""
if ($opcion -eq '2') {
    Write-Host "Falta un paso en Supabase: abra el archivo activar-roles-supabase.sql, copie su"
    Write-Host "contenido en el SQL Editor del panel de Supabase y pulse Run."
    Write-Host ""
    Write-Host "Despues ejecute:"
    Write-Host "  docker compose up --build -d"
    Write-Host "  docker compose exec api python -m app.seed"
} else {
    Write-Host "Ahora ejecute:"
    Write-Host "  docker compose down -v"
    Write-Host "  docker compose up --build -d"
    Write-Host "  docker compose exec api python -m app.seed"
}
