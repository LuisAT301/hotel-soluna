#!/bin/sh
# =====================================================================
# Hotel Soluna: prueba de carga con Locust (bloque 4)
#
#   sh carga.sh docker [usuarios] [duración]   contra el prototipo en Docker
#   sh carga.sh vercel [usuarios] [duración]   contra el sitio publicado en Vercel
#
# Por defecto: 30 usuarios por 1 minuto en Docker; 15 por 1 minuto en Vercel,
# para no gastar las cuotas gratuitas de Vercel y Supabase. La duración usa
# el formato de Locust: 30s, 2m, 1h30m.
#
# El reporte (gráficos y tabla, en HTML) queda en carga/resultados/.
# Para ver el balanceo con más réplicas en Docker:
#   docker compose up -d --scale api=5 --no-recreate
# =====================================================================
set -eu
cd "$(dirname "$0")"

destino="${1:-}"
case "$destino" in
docker)
    servicio=carga-local; sitio=https://localhost; usuarios="${2:-30}"
    if [ -z "$(docker compose ps --status running -q nginx 2>/dev/null)" ]; then
        echo "El prototipo no está encendido. Ejecute primero: docker compose up -d" >&2
        exit 1
    fi
    ;;
vercel)
    servicio=carga-nube; sitio=https://hotel-soluna-web.vercel.app; usuarios="${2:-15}"
    if [ "$usuarios" -gt 50 ]; then
        echo "Más de 50 usuarios contra Vercel gastaría las cuotas gratuitas. Use 50 o menos." >&2
        exit 1
    fi
    ;;
*)
    sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
duracion="${3:-1m}"
tasa=$(( usuarios / 10 + 1 ))     # usuarios nuevos por segundo al arrancar
reporte="$destino-$(date +%Y%m%d-%H%M)"
mkdir -p carga/resultados

echo "Locust: $usuarios usuarios contra $sitio durante $duracion (reporte en carga/resultados/$reporte.html)"
docker compose --profile carga run --rm --no-deps "$servicio" \
    -f locustfile.py --headless --only-summary \
    --users "$usuarios" --spawn-rate "$tasa" --run-time "$duracion" --host "$sitio" \
    --html "resultados/$reporte.html" --csv "resultados/$reporte"
