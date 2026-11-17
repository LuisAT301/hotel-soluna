#!/bin/sh
# =====================================================================
# Crea el archivo .env con todas las contraseñas listas (Mac y Linux).
# Uso, dentro de la carpeta hotel-soluna:
#     sh crear-env.sh
# Pregunta si la base de datos estará en Supabase o en Docker (local).
# Si ya existe un .env, lo guarda como .env.anterior antes de reemplazarlo.
# =====================================================================
set -e
cd "$(dirname "$0")"

aleatorio() {
    # 48 caracteres hexadecimales al azar
    od -An -tx1 -N24 /dev/urandom | tr -dc '0-9a-f'
}

echo "¿Dónde estará la base de datos?"
echo "  1) En Docker, en este equipo (recomendado para empezar)"
echo "  2) En Supabase"
printf "Elija 1 o 2 [1]: "
read -r opcion || opcion=1

SUPABASE_REF=""
SUPABASE_HOST=""
COMPARTIDA=""
if [ "$opcion" = "2" ]; then
    echo ""
    echo "En el panel de Supabase pulse 'Connect', elija 'Session pooler' y copie la cadena"
    echo "de conexión. Se ve así (no hace falta poner la contraseña):"
    echo "  postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-us-east-2.pooler.supabase.com:5432/postgres"
    printf "Pegue la cadena aquí: "
    read -r cadena
    SUPABASE_REF=$(printf '%s' "$cadena" | sed -n 's#.*postgres\.\([a-z0-9]*\)[:@].*#\1#p')
    SUPABASE_HOST=$(printf '%s' "$cadena" | sed -n 's#.*@\([^:/]*\).*#\1#p')
    if [ -z "$SUPABASE_REF" ] || [ -z "$SUPABASE_HOST" ]; then
        echo "No se reconoció la cadena. Verifique que sea la de 'Session pooler' y vuelva a ejecutar el script."
        exit 1
    fi
    # Todo el equipo comparte la misma base, así que la contraseña del usuario
    # de la API también es una sola: la genera quien configura Supabase primero.
    echo ""
    echo "Si otro integrante ya activó los usuarios de la base en Supabase, pegue la"
    echo "contraseña de la API (DB_APP_PASSWORD) que le compartió por un medio privado."
    printf "Contraseña compartida (Enter si usted es el primero del equipo): "
    stty -echo 2>/dev/null || true
    read -r COMPARTIDA || COMPARTIDA=""
    stty echo 2>/dev/null || true
    echo ""
fi

if [ -f .env ]; then
    cp .env .env.anterior
    echo "Había un .env: se guardó una copia en .env.anterior"
fi

APP_PASS=${COMPARTIDA:-$(aleatorio)}
RESPALDO_PASS=$(aleatorio)

cat > .env <<EOF
# Creado por crear-env.sh el $(date '+%d/%m/%Y %H:%M'). No se sube al repositorio.
POSTGRES_PASSWORD=$(aleatorio)
DB_APP_PASSWORD=$APP_PASS
DB_RESPALDO_PASSWORD=$RESPALDO_PASS
JWT_SECRET=$(aleatorio)
DEMO_PASSWORD=SolunaDemo2026
SERVICIOS_LLAVE=$(aleatorio)
OTA_SECRETO=$(aleatorio)
EOF

if [ "$opcion" = "2" ]; then
    cat >> .env <<EOF

# Base de datos en Supabase
SUPABASE_REF=$SUPABASE_REF
SUPABASE_HOST=$SUPABASE_HOST
COMPOSE_FILE=docker-compose.yml:docker-compose.supabase.yml
EOF
fi
if [ "$opcion" = "2" ] && [ -z "$COMPARTIDA" ]; then
    # Comando para activar los usuarios de la base con estas mismas contraseñas
    cat > activar-roles-supabase.sql <<EOF
-- Copie todo este archivo en el SQL Editor de Supabase y pulse "Run".
-- Activa los usuarios de la API y de respaldos con las contraseñas del .env.
-- Este archivo tiene contraseñas: no lo comparta (Git ya lo ignora).
ALTER ROLE app_hotel WITH LOGIN PASSWORD '$APP_PASS';
ALTER ROLE respaldo  WITH LOGIN PASSWORD '$RESPALDO_PASS';
EOF
fi

echo ""
echo "Listo: .env creado con todas las contraseñas."
echo "Contraseña de las cuentas de demostración: SolunaDemo2026"
echo ""
if [ "$opcion" = "2" ] && [ -z "$COMPARTIDA" ]; then
    echo "Falta un paso en Supabase: abra el archivo activar-roles-supabase.sql, copie su"
    echo "contenido en el SQL Editor del panel de Supabase y pulse 'Run'."
    echo "Luego comparta con su equipo, por un medio privado, el valor de DB_APP_PASSWORD"
    echo "de su .env: cada integrante lo pega cuando este script se lo pida."
    echo ""
    echo "Después ejecute:"
    echo "  docker compose up --build -d"
    echo "  docker compose exec api python -m app.seed"
elif [ "$opcion" = "2" ]; then
    echo "Se usará la contraseña compartida. Ejecute:"
    echo "  docker compose up --build -d"
    echo "  docker compose exec api python -m app.seed"
else
    echo "Ahora ejecute:"
    echo "  docker compose down -v"
    echo "  docker compose up --build -d"
    echo "  docker compose exec api python -m app.seed"
fi
