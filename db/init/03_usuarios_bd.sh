#!/bin/sh
# =====================================================================
# Hotel Soluna: usuarios de la base de datos con privilegios mínimos
#   app_hotel : la usa la API. Lee y escribe datos, pero no puede borrar
#               reservas ni modificar o borrar la bitácora, ni cambiar
#               la estructura de las tablas.
#   respaldo  : la usa el contenedor de respaldos. Solo lectura.
# Las contraseñas llegan como secretos de Docker (/run/secrets/...),
# nunca escritas en el repositorio.
# =====================================================================
# Sin "set -u": si Git pierde el permiso de ejecución (por ejemplo, en Windows),
# el contenedor de PostgreSQL carga este archivo con "source" y no conviene
# alterar las opciones de su propio script de arranque.
set -e

SECRETS_DIR="${SECRETS_DIR:-/run/secrets}"
APP_PASS="$(cat "$SECRETS_DIR/db_app_password")"
RESPALDO_PASS="$(cat "$SECRETS_DIR/db_respaldo_password")"

psql -v ON_ERROR_STOP=1 \
     --username "${POSTGRES_USER:-postgres}" \
     --dbname "${POSTGRES_DB:-hotel}" \
     -v app_pass="$APP_PASS" \
     -v respaldo_pass="$RESPALDO_PASS" <<'EOSQL'
CREATE ROLE app_hotel LOGIN PASSWORD :'app_pass';
CREATE ROLE respaldo  LOGIN PASSWORD :'respaldo_pass';

-- Nadie fuera de estos roles puede conectarse a la base
REVOKE ALL ON DATABASE hotel FROM PUBLIC;
GRANT CONNECT ON DATABASE hotel TO app_hotel, respaldo;
GRANT USAGE ON SCHEMA public TO app_hotel, respaldo;

-- API: solo los permisos que necesita cada tabla
GRANT SELECT, INSERT, UPDATE           ON usuarios         TO app_hotel;
GRANT SELECT                           ON tipos_habitacion TO app_hotel;
GRANT SELECT                           ON tarifas          TO app_hotel;
GRANT SELECT, UPDATE                   ON habitaciones     TO app_hotel;
GRANT SELECT, INSERT, UPDATE           ON reservas         TO app_hotel;  -- se cancelan, no se borran
GRANT SELECT, INSERT                   ON bitacora         TO app_hotel;  -- solo se agregan registros

-- Respaldos: lectura de todas las tablas (rol predefinido desde PostgreSQL 14)
GRANT pg_read_all_data TO respaldo;
EOSQL

echo "Usuarios app_hotel y respaldo creados."
