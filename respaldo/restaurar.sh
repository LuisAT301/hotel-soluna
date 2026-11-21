#!/bin/sh
# =====================================================================
# Hotel Soluna: restaura un respaldo de Supabase en la base local (bloque 4)
#
# Corre dentro del contenedor "db" del nodo de contingencia y entra por el
# socket local como administrador. Crea desde cero la base BD_DESTINO, carga
# el respaldo con sus permisos y deja a la API (app_hotel) usando el esquema
# "hotel", igual que en Supabase.
#
#   restaurar.sh                    el respaldo más reciente
#   restaurar.sh hotel-...dump      uno en particular
#
# Variables: BD_DESTINO (por defecto hotel_contingencia).
# =====================================================================
set -eu

BD="${BD_DESTINO:-hotel_contingencia}"
CARPETA=/respaldos
cd "$CARPETA"

if [ -n "${1:-}" ]; then
    archivo="$1"
else
    archivo=$(ls -1t hotel-*.dump 2>/dev/null | head -n 1 || true)
fi
if [ -z "$archivo" ] || [ ! -f "$archivo" ]; then
    echo "No hay respaldos en el nodo. Ejecute primero: sh contingencia.sh respaldar" >&2
    exit 1
fi

# La huella confirma que el archivo no se dañó ni se alteró desde que se creó
if ! sha256sum -c -s "$archivo.sha256"; then
    echo "La huella SHA-256 de $archivo no coincide: el respaldo está dañado." >&2
    exit 1
fi

# Fecha del respaldo, tomada del nombre (hotel-AAAAMMDDTHHMMSSZ.dump)
marca=$(echo "$archivo" | sed -E 's/hotel-([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z\.dump/\1-\2-\3 \4:\5:\6+00/')
inicio=$(date +%s)

export PGOPTIONS="-c client_min_messages=warning"
# psql como administrador, sin leer ~/.psqlrc (-X), silencioso (-q) y deteniéndose ante el primer error
psql() { command psql -X -q -v ON_ERROR_STOP=1 -U postgres "$@"; }

# No se pisa una contingencia con trabajo hecho: esas reservas aún no están en la nube
if [ "${FORZAR:-no}" != "si" ] && psql -d "$BD" -A -t -c "SELECT 1" > /dev/null 2>&1; then
    cambios=$(psql -d "$BD" -A -t -c "SELECT count(*) FROM hotel.reservas r, public.contingencia c
        WHERE r.creada_en >= c.restaurada_en OR r.actualizada_en >= c.restaurada_en" 2>/dev/null || echo 0)
    if [ "${cambios:-0}" -gt 0 ]; then
        echo "La base $BD tiene $cambios reserva(s) registrada(s) durante la contingencia." >&2
        echo "Ejecute primero 'sh contingencia.sh volver' para sacar el reporte, o repita con FORZAR=si." >&2
        exit 1
    fi
fi

echo "Restaurando $archivo en la base $BD..."
psql -d postgres -c "DROP DATABASE IF EXISTS $BD WITH (FORCE)" -c "CREATE DATABASE $BD"

# btree_gist sostiene la regla contra la sobreventa; en Supabase vive en "extensions"
psql -d "$BD" -c "CREATE SCHEMA extensions" -c "CREATE EXTENSION btree_gist WITH SCHEMA extensions"

# Los permisos de las tablas viajan en el respaldo: solo mencionan a app_hotel y
# respaldo, que también existen en la base local. Los permisos por defecto
# (DEFAULT ACL) se omiten: solo aplican a tablas futuras y nombran a usuarios
# internos de Supabase que aquí no existen. --exit-on-error: o todo, o nada.
lista=$(mktemp)
pg_restore --list "$archivo" | grep -v " DEFAULT ACL " > "$lista"
pg_restore -U postgres -d "$BD" --no-owner --exit-on-error --use-list="$lista" "$archivo"
rm -f "$lista"

psql -d "$BD" <<SQL
REVOKE ALL ON DATABASE $BD FROM PUBLIC;
GRANT CONNECT ON DATABASE $BD TO app_hotel, respaldo;
GRANT USAGE ON SCHEMA extensions TO app_hotel, respaldo;
ALTER ROLE app_hotel IN DATABASE $BD SET search_path = hotel, extensions;
ALTER ROLE respaldo  IN DATABASE $BD SET search_path = hotel, extensions;

-- La API local entra con la contraseña del .env actual, aunque la base
-- local se haya creado con otra en una instalación anterior.
\set clave \`cat /run/secrets/db_app_password\`
ALTER ROLE app_hotel WITH LOGIN PASSWORD :'clave';

-- Cuándo se restauró y de qué respaldo: sirve para el reporte al volver a la nube
CREATE TABLE public.contingencia (
    respaldo      text        NOT NULL,
    respaldo_de   timestamptz NOT NULL,
    restaurada_en timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.contingencia (respaldo, respaldo_de) VALUES ('$archivo', '$marca');
SQL

duracion=$(( $(date +%s) - inicio ))
echo ""
echo "Registros restaurados:"
psql -d "$BD" -A -F ' ' -t <<'SQL' | while read -r tabla filas; do printf "  %-18s %s\n" "$tabla" "$filas"; done
SELECT 'usuarios', count(*) FROM hotel.usuarios UNION ALL
SELECT 'habitaciones', count(*) FROM hotel.habitaciones UNION ALL
SELECT 'reservas', count(*) FROM hotel.reservas UNION ALL
SELECT 'pagos', count(*) FROM hotel.pagos UNION ALL
SELECT 'facturas', count(*) FROM hotel.facturas UNION ALL
SELECT 'suscriptores', count(*) FROM hotel.suscriptores UNION ALL
SELECT 'bitacora', count(*) FROM hotel.bitacora;
SQL
antiguedad=$(psql -d "$BD" -A -t -c "SELECT (s / 3600) || ' h ' || (s % 3600 / 60) || ' min'
    FROM (SELECT extract(epoch FROM now() - respaldo_de)::int AS s FROM public.contingencia) t")
echo ""
echo "Restauración completa en $duracion s. El respaldo tiene $antiguedad de antigüedad:"
echo "lo registrado en la nube después de ese momento no está en el nodo (RPO)."
