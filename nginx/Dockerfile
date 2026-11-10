# Proxy inverso, HTTPS y balanceo de carga del Hotel Soluna
# nginx:1.30-alpine es la versión estable; existe para amd64 y arm64 (Apple Silicon)
FROM nginx:1.30-alpine

# openssl se usa solo para crear el certificado autofirmado al arrancar
RUN apk add --no-cache openssl

# Los scripts de /docker-entrypoint.d se ejecutan antes de iniciar Nginx
COPY 40-certificado.sh /docker-entrypoint.d/40-certificado.sh
RUN chmod +x /docker-entrypoint.d/40-certificado.sh && rm -f /etc/nginx/conf.d/default.conf

COPY soluna.conf /etc/nginx/conf.d/soluna.conf
COPY proxy_api.conf cabeceras_seguridad.conf /etc/nginx/
