#!/bin/sh
# =====================================================================
# Hotel Soluna: respaldo automático de la base de datos (bloque 4)
#
# Copia el esquema "hotel" de Supabase con pg_dump, usando el usuario
# "respaldo", que solo puede leer. Cada copia se comprueba antes de darla
# por buena, se guarda con su huella SHA-256 y se conservan las últimas
# CONSERVAR copias. Corre dentro del contenedor "respaldo".
#
#   respaldar.sh             un respaldo cada INTERVALO_MINUTOS, sin parar
#   respaldar.sh --una-vez   un solo respaldo; termina con error si falla
#
# Las horas de los nombres de archivo están en UTC (terminan en Z).
# =====================================================================
set -u

DESTINO=${DESTINO:-/respaldos}
ESQUEMA=${ESQUEMA:-hotel}
INTERVALO=${INTERVALO_MINUTOS:-360}
CONSERVAR=${CONSERVAR:-28}

export PGHOST="${ORIGEN_HOST:?Falta ORIGEN_HOST}"
export PGPORT="${ORIGEN_PUERTO:-5432}"
export PGDATABASE="${ORIGEN_BASE:-postgres}"
export PGUSER="${ORIGEN_USUARIO:?Falta ORIGEN_USUARIO}"
export PGSSLMODE="${ORIGEN_SSLMODE:-require}"
export PGCONNECT_TIMEOUT=20
PGPASSWORD=$(cat "${ORIGEN_PASSWORD_FILE:?Falta ORIGEN_PASSWORD_FILE}")
export PGPASSWORD

mkdir -p "$DESTINO"

anotar() {
    linea="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
    echo "$linea"
    echo "$linea" >> "$DESTINO/registro.txt"
}

rotar() {
    # Borra las copias más viejas y deja solo las CONSERVAR más recientes
    ls -1t "$DESTINO"/hotel-*.dump 2>/dev/null | tail -n +"$((CONSERVAR + 1))" | while read -r viejo; do
        rm -f "$viejo" "$viejo.sha256"
        anotar "ROTACION se borró $(basename "$viejo")"
    done
}

respaldar() {
    nombre="hotel-$(date -u +%Y%m%dT%H%M%SZ).dump"
    temporal="$DESTINO/.$nombre.parcial"
    inicio=$(date +%s)

    # Formato "custom": comprimido y restaurable tabla por tabla con pg_restore.
    # --no-owner: el dueño en Supabase ("postgres") no tiene por qué existir donde se restaure.
    if ! pg_dump --format=custom --schema="$ESQUEMA" --no-owner --file="$temporal" 2> "$DESTINO/.error"; then
        anotar "ERROR pg_dump: $(tr '\n' ' ' < "$DESTINO/.error" | cut -c1-300)"
        rm -f "$temporal"
        return 1
    fi
    # Una copia que pg_restore no puede leer no es un respaldo
    if ! pg_restore --list "$temporal" > /dev/null 2>&1; then
        anotar "ERROR la copia $nombre está dañada y se descartó"
        rm -f "$temporal"
        return 1
    fi

    mv "$temporal" "$DESTINO/$nombre"
    (cd "$DESTINO" && sha256sum "$nombre" > "$nombre.sha256")
    tablas=$(pg_restore --list "$DESTINO/$nombre" | grep -c " TABLE DATA ")
    tamano=$(du -h "$DESTINO/$nombre" | cut -f1)
    anotar "OK $nombre ($tamano, $tablas tablas, $(( $(date +%s) - inicio )) s)"
    rotar
    return 0
}

if [ "${1:-}" = "--una-vez" ]; then
    respaldar
    exit $?
fi

anotar "INICIO respaldo de $PGHOST cada $INTERVALO minutos; se conservan $CONSERVAR copias"
while true; do
    # Si falla, se espera el intervalo completo: reintentar seguido con una
    # contraseña equivocada haría que Supabase bloquee la dirección del hotel.
    respaldar || true
    sleep "$((INTERVALO * 60))"
done
