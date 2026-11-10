#!/bin/sh
# =====================================================================
# Crea el archivo .env con todas las contraseñas listas (Mac y Linux).
# Uso, dentro de la carpeta hotel-soluna:
#     sh crear-env.sh
# Si ya existe un .env, lo guarda como .env.anterior antes de reemplazarlo.
# =====================================================================
set -e
cd "$(dirname "$0")"

aleatorio() {
    # 48 caracteres hexadecimales al azar
    od -An -tx1 -N24 /dev/urandom | tr -d ' \n'
}

if [ -f .env ]; then
    cp .env .env.anterior
    echo "Había un .env: se guardó una copia en .env.anterior"
fi

cat > .env <<EOF
# Creado por crear-env.sh el $(date '+%d/%m/%Y %H:%M'). No se sube al repositorio.
POSTGRES_PASSWORD=$(aleatorio)
DB_APP_PASSWORD=$(aleatorio)
DB_RESPALDO_PASSWORD=$(aleatorio)
JWT_SECRET=$(aleatorio)
DEMO_PASSWORD=SolunaDemo2026
SERVICIOS_LLAVE=$(aleatorio)
OTA_SECRETO=$(aleatorio)
EOF

echo ""
echo "Listo: .env creado con todas las contraseñas."
echo "Contraseña de las cuentas de demostración: SolunaDemo2026"
echo ""
echo "Ahora ejecute:"
echo "  docker compose down -v"
echo "  docker compose up --build -d"
echo "  docker compose exec api python -m app.seed"
