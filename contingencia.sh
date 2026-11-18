#!/bin/sh
# =====================================================================
# Hotel Soluna: respaldos y nodo de contingencia (bloque 4)
#
# La computadora del hotel guarda copias periódicas de la base de Supabase.
# Si la nube o Internet fallan, restaura la última copia en Docker y el
# hotel sigue operando en https://localhost (o en la IP de esta computadora
# dentro de la red del hotel).
#
#   sh contingencia.sh iniciar     enciende los respaldos automáticos (cada 6 h)
#   sh contingencia.sh respaldar   hace un respaldo ahora
#   sh contingencia.sh estado      muestra las copias guardadas y el registro
#   sh contingencia.sh simulacro   prueba respaldo y restauración sin interrumpir nada
#   sh contingencia.sh activar     pasa a operar con la base local
#   sh contingencia.sh volver      reporte de lo hecho en contingencia y regreso a la nube
#
# Requiere el .env en modo Supabase (crear-env, opción 2).
# =====================================================================
set -eu
cd "$(dirname "$0")"

NUBE="-f docker-compose.yml -f docker-compose.supabase.yml --profile respaldos"
LOCAL="-f docker-compose.yml -f docker-compose.contingencia.yml"

if [ ! -f .env ] || ! grep -q '^SUPABASE_HOST=' .env; then
    echo "El .env no está en modo Supabase. Ejecute: sh crear-env.sh (opción 2)." >&2
    exit 1
fi

titulo() { printf '\n== %s ==\n' "$1"; }

conteos_origen() {
    # Cuenta las filas en Supabase con el mismo usuario de solo lectura
    docker compose $NUBE run --rm --no-deps -T --entrypoint sh respaldo -c '
        PGPASSWORD=$(cat "$ORIGEN_PASSWORD_FILE") psql -X -A -t -F " " \
          "host=$ORIGEN_HOST port=$ORIGEN_PUERTO dbname=$ORIGEN_BASE user=$ORIGEN_USUARIO sslmode=$ORIGEN_SSLMODE" -c "
          SELECT '\''reservas'\'', count(*) FROM hotel.reservas UNION ALL
          SELECT '\''pagos'\'', count(*) FROM hotel.pagos UNION ALL
          SELECT '\''facturas'\'', count(*) FROM hotel.facturas UNION ALL
          SELECT '\''usuarios'\'', count(*) FROM hotel.usuarios"'
}

conteos_local() {
    docker compose $LOCAL exec -T db psql -X -A -t -F " " -U postgres -d "$1" -c "
        SELECT 'reservas', count(*) FROM hotel.reservas UNION ALL
        SELECT 'pagos', count(*) FROM hotel.pagos UNION ALL
        SELECT 'facturas', count(*) FROM hotel.facturas UNION ALL
        SELECT 'usuarios', count(*) FROM hotel.usuarios"
}

case "${1:-}" in
iniciar)
    docker compose $NUBE up -d respaldo
    echo "Respaldos automáticos encendidos. El primero se hace ahora; vea el avance con: sh contingencia.sh estado"
    ;;

respaldar)
    docker compose $NUBE run --rm --no-deps respaldo --una-vez
    ;;

estado)
    docker compose $NUBE run --rm --no-deps -T --entrypoint sh respaldo -c '
        echo "Copias guardadas (las horas están en UTC):"
        ls -1t /respaldos/hotel-*.dump 2>/dev/null | head -n 10 | while read -r f; do
            printf "  %s  %s\n" "$(basename "$f")" "$(du -h "$f" | cut -f1)"; done
        echo; echo "Últimos eventos:"; tail -n 8 /respaldos/registro.txt 2>/dev/null | sed "s/^/  /"'
    ;;

simulacro)
    # Comprueba que los respaldos sirven sin tocar el sistema en uso: copia,
    # restaura en una base aparte, compara y borra esa base.
    inicio=$(date +%s)
    titulo "1. Respaldo de Supabase"
    docker compose $NUBE run --rm --no-deps respaldo --una-vez
    origen=$(conteos_origen)

    titulo "2. Restauración en una base de prueba del nodo"
    db_encendida=$(docker compose $LOCAL ps --status running -q db)
    docker compose $LOCAL up -d --wait db
    docker compose $LOCAL exec -T -e BD_DESTINO=hotel_simulacro db sh /scripts/restaurar.sh
    local_=$(conteos_local hotel_simulacro)

    titulo "3. Comparación"
    printf '  %-10s %8s %8s\n' "tabla" "nube" "nodo"
    echo "$origen" | while read -r tabla n; do
        m=$(echo "$local_" | awk -v t="$tabla" '$1 == t {print $2}')
        marca=""; [ "$n" = "$m" ] || marca="  <- distinto (¿hubo actividad durante el simulacro?)"
        printf '  %-10s %8s %8s%s\n' "$tabla" "$n" "$m" "$marca"
    done
    docker compose $LOCAL exec -T db psql -X -q -U postgres -d postgres -c "DROP DATABASE hotel_simulacro WITH (FORCE)"
    [ -n "$db_encendida" ] || docker compose $LOCAL stop db > /dev/null 2>&1
    echo ""
    echo "Simulacro terminado en $(( $(date +%s) - inicio )) s, sin interrumpir el servicio en la nube."
    ;;

activar)
    titulo "Activando el nodo de contingencia"
    docker compose $LOCAL up -d --wait db
    docker compose $LOCAL exec -T db sh /scripts/restaurar.sh ${2:-}
    # Sin --build ni descargas: debe funcionar aunque no haya Internet
    docker compose $LOCAL up -d --wait --remove-orphans
    echo ""
    echo "El hotel opera ahora con la base local: https://localhost"
    echo "Los correos quedan en Mailpit (http://localhost:8025) hasta volver a la nube."
    echo "Cuando la nube responda: sh contingencia.sh volver"
    ;;

volver)
    titulo "Cambios hechos durante la contingencia"
    reporte="contingencia-cambios-$(date +%Y%m%d-%H%M).csv"
    docker compose $LOCAL exec -T db psql -X -q -U postgres -d hotel_contingencia --csv -c "
        SELECT r.codigo, r.canal, r.estado, r.nombre_huesped, r.correo_huesped,
               h.numero AS habitacion, r.fecha_entrada, r.fecha_salida, r.personas, r.total,
               EXISTS (SELECT 1 FROM hotel.pagos p WHERE p.reserva_id = r.id
                       AND p.tipo = 'cobro' AND p.estado = 'aprobado') AS pagada,
               CASE WHEN r.creada_en >= c.restaurada_en THEN 'nueva' ELSE 'modificada' END AS cambio,
               r.creada_en, r.actualizada_en
        FROM hotel.reservas r
        JOIN hotel.habitaciones h ON h.id = r.habitacion_id
        CROSS JOIN public.contingencia c
        WHERE r.creada_en >= c.restaurada_en OR r.actualizada_en >= c.restaurada_en
        ORDER BY r.creada_en" > "$reporte"
    filas=$(( $(wc -l < "$reporte") - 1 ))
    echo "$filas reserva(s) nueva(s) o modificada(s), guardada(s) en $reporte."
    echo "Regístrelas en el sistema de la nube antes de seguir operando (ver README, bloque 4)."

    titulo "Regreso a la nube"
    docker compose $LOCAL down
    docker compose $NUBE up -d --wait
    echo "El hotel opera de nuevo con Supabase. La base de contingencia se conserva para auditoría."
    ;;

*)
    sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
