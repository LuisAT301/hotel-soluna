#!/bin/sh
# Crea un certificado autofirmado la primera vez que arranca Nginx.
# Se guarda en un volumen, así no cambia cada vez que se reinicia el contenedor.
# En producción se usaría un certificado emitido por una autoridad (por ejemplo, Let's Encrypt).
set -e
DIR=/etc/nginx/certs

if [ ! -f "$DIR/soluna.crt" ] || [ ! -f "$DIR/soluna.key" ]; then
    mkdir -p "$DIR"
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
        -keyout "$DIR/soluna.key" -out "$DIR/soluna.crt" \
        -subj "/C=CR/O=Hotel Soluna (prototipo)/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
    chmod 600 "$DIR/soluna.key"
    echo "40-certificado.sh: certificado autofirmado creado en $DIR"
else
    echo "40-certificado.sh: se usa el certificado existente"
fi
