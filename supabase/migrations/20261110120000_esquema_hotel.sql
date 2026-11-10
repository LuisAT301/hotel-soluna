-- =====================================================================
-- Hotel Soluna: esquema completo para Supabase (bloques 1 a 3)
--
-- La integración de Supabase con GitHub aplica este archivo una sola vez,
-- al fusionar en la rama de producción. También puede ejecutarse a mano en
-- el SQL Editor del panel de Supabase.
--
-- Diferencias con db/init (la base local en Docker):
--   * Las tablas viven en el esquema "hotel" y no en "public". Supabase
--     publica automáticamente el esquema "public" como API REST; "hotel" no
--     se publica, así que los datos de huéspedes y pagos no quedan expuestos.
--   * btree_gist se instala en el esquema "extensions", como pide Supabase.
--   * No se le quita el acceso a la base a los demás roles: Supabase usa
--     roles propios para su panel y sus servicios.
--   * Los roles app_hotel y respaldo se crean SIN contraseña ni inicio de
--     sesión: las contraseñas no pueden quedar en el repositorio. Se activan
--     después con el comando que imprime crear-env (ver README).
--
-- Si cambia el esquema, actualice también db/init.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;

CREATE SCHEMA hotel;
SET search_path = hotel, extensions;

-- ---------------------------------------------------------------------
-- Usuarios del sistema (personal y clientes) con su rol
-- ---------------------------------------------------------------------
CREATE TABLE usuarios (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correo            text        NOT NULL UNIQUE,
    nombre            text        NOT NULL,
    hash_contrasena   text        NOT NULL,          -- Argon2id, nunca texto plano
    rol               text        NOT NULL
                      CHECK (rol IN ('cliente', 'recepcionista', 'limpieza',
                                     'mantenimiento', 'gerente')),
    activo            boolean     NOT NULL DEFAULT true,
    intentos_fallidos smallint    NOT NULL DEFAULT 0,
    bloqueado_hasta   timestamptz,
    creado_en         timestamptz NOT NULL DEFAULT now(),
    CHECK (correo = lower(correo))
);

-- ---------------------------------------------------------------------
-- Catálogo de habitaciones y tarifas por temporada
-- ---------------------------------------------------------------------
CREATE TABLE tipos_habitacion (
    id          smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      text     NOT NULL UNIQUE,
    capacidad   smallint NOT NULL CHECK (capacidad > 0),
    descripcion text
);

CREATE TABLE tarifas (
    tipo_id      smallint      NOT NULL REFERENCES tipos_habitacion (id),
    temporada    text          NOT NULL CHECK (temporada IN ('alta', 'baja')),
    precio_noche numeric(10,2) NOT NULL CHECK (precio_noche > 0),
    PRIMARY KEY (tipo_id, temporada)
);

CREATE TABLE habitaciones (
    id                bigint   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    numero            text     NOT NULL UNIQUE,
    tipo_id           smallint NOT NULL REFERENCES tipos_habitacion (id),
    piso              smallint NOT NULL,
    estado_limpieza   text     NOT NULL DEFAULT 'limpia'
                      CHECK (estado_limpieza IN ('sucia', 'en_limpieza',
                                                 'limpia', 'inspeccionada')),
    fuera_de_servicio boolean  NOT NULL DEFAULT false
);

-- ---------------------------------------------------------------------
-- Reservas, con la regla contra la sobreventa
-- ---------------------------------------------------------------------
CREATE TABLE reservas (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo             text          NOT NULL UNIQUE,
    habitacion_id      bigint        NOT NULL REFERENCES habitaciones (id),
    cliente_id         bigint        REFERENCES usuarios (id),
    nombre_huesped     text          NOT NULL,
    correo_huesped     text          NOT NULL,
    personas           smallint      NOT NULL CHECK (personas > 0),
    fecha_entrada      date          NOT NULL,
    fecha_salida       date          NOT NULL,
    canal              text          NOT NULL CHECK (canal IN ('web', 'recepcion', 'ota')),
    estado             text          NOT NULL
                       CHECK (estado IN ('pendiente_pago', 'confirmada', 'en_curso',
                                         'finalizada', 'cancelada')),
    total              numeric(10,2) NOT NULL CHECK (total >= 0),
    creada_por         bigint        REFERENCES usuarios (id),
    creada_en          timestamptz   NOT NULL DEFAULT now(),
    actualizada_en     timestamptz   NOT NULL DEFAULT now(),
    referencia_externa text          UNIQUE,      -- número de reserva de la OTA
    CHECK (fecha_salida > fecha_entrada),

    -- Dos reservas activas de la misma habitación no pueden traslaparse.
    -- El rango [entrada, salida) deja libre el día de salida.
    CONSTRAINT sin_traslape EXCLUDE USING gist (
        habitacion_id WITH =,
        (daterange(fecha_entrada, fecha_salida)) WITH &&
    ) WHERE (estado <> 'cancelada')
);

CREATE INDEX reservas_cliente_idx ON reservas (cliente_id);
CREATE INDEX reservas_fechas_idx  ON reservas (fecha_entrada, fecha_salida);

-- ---------------------------------------------------------------------
-- Bitácora de auditoría
-- ---------------------------------------------------------------------
CREATE TABLE bitacora (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha      timestamptz NOT NULL DEFAULT now(),
    usuario_id bigint      REFERENCES usuarios (id),
    accion     text        NOT NULL,
    entidad    text        NOT NULL,
    entidad_id text,
    detalle    jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX bitacora_fecha_idx ON bitacora (fecha DESC);

-- ---------------------------------------------------------------------
-- Pagos y facturas electrónicas (bloque 3)
-- ---------------------------------------------------------------------
CREATE TABLE pagos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id  bigint        NOT NULL REFERENCES reservas (id),
    tipo        text          NOT NULL CHECK (tipo IN ('cobro', 'reembolso')),
    estado      text          NOT NULL CHECK (estado IN ('aprobado', 'rechazado')),
    transaccion text          NOT NULL UNIQUE,
    monto       numeric(10,2) NOT NULL CHECK (monto >= 0),
    marca       text,
    ultimos4    char(4)       CHECK (ultimos4 ~ '^[0-9]{4}$'),
    motivo      text,
    creado_en   timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX pagos_reserva_idx ON pagos (reserva_id);

CREATE SEQUENCE consecutivo_factura;

CREATE TABLE facturas (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id    bigint        NOT NULL UNIQUE REFERENCES reservas (id),
    clave         char(50)      NOT NULL UNIQUE CHECK (clave ~ '^[0-9]{50}$'),
    consecutivo   char(20)      NOT NULL UNIQUE CHECK (consecutivo ~ '^[0-9]{20}$'),
    subtotal      numeric(10,2) NOT NULL CHECK (subtotal >= 0),
    impuesto      numeric(10,2) NOT NULL CHECK (impuesto >= 0),
    total         numeric(10,2) NOT NULL CHECK (total = subtotal + impuesto),
    estado        text          NOT NULL DEFAULT 'pendiente'
                  CHECK (estado IN ('pendiente', 'aceptada', 'rechazada')),
    mensaje       text,
    emitida_en    timestamptz   NOT NULL DEFAULT now(),
    respondida_en timestamptz
);

-- ---------------------------------------------------------------------
-- Catálogo: 46 habitaciones en tres categorías
-- ---------------------------------------------------------------------
INSERT INTO tipos_habitacion (nombre, capacidad, descripcion) VALUES
    ('estándar', 2, 'Cama queen, vista al jardín'),
    ('superior', 3, 'Cama king y sofá cama, balcón con vista parcial al mar'),
    ('suite',    4, 'Dos ambientes, terraza frente al mar');

INSERT INTO tarifas (tipo_id, temporada, precio_noche)
SELECT t.id, v.temporada, v.precio
FROM tipos_habitacion t
JOIN (VALUES
        ('estándar', 'alta', 120.00), ('estándar', 'baja',  85.00),
        ('superior', 'alta', 165.00), ('superior', 'baja', 115.00),
        ('suite',    'alta', 260.00), ('suite',    'baja', 180.00)
     ) AS v (tipo, temporada, precio) ON v.tipo = t.nombre;

INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'estándar'), 1
FROM generate_series(101, 120) AS n;

INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'superior'), 2
FROM generate_series(201, 218) AS n;

INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'suite'), 3
FROM generate_series(301, 308) AS n;

-- ---------------------------------------------------------------------
-- Roles con privilegios mínimos
--   app_hotel : la usa la API. No puede borrar reservas, alterar la
--               bitácora, modificar pagos ni cambiar montos de facturas.
--   respaldo  : solo lectura, para los respaldos del bloque 4.
-- Se crean sin inicio de sesión; ver el encabezado.
-- ---------------------------------------------------------------------
CREATE ROLE app_hotel NOLOGIN;
CREATE ROLE respaldo  NOLOGIN;

-- Al conectarse, ambos trabajan en el esquema "hotel" sin tener que nombrarlo
ALTER ROLE app_hotel SET search_path = hotel, extensions;
ALTER ROLE respaldo  SET search_path = hotel, extensions;

-- Los roles de Supabase para su API pública no ven nada de este esquema
REVOKE ALL ON SCHEMA hotel FROM PUBLIC;
GRANT USAGE ON SCHEMA hotel TO app_hotel, respaldo;
GRANT USAGE ON SCHEMA extensions TO app_hotel, respaldo;

GRANT SELECT, INSERT, UPDATE           ON usuarios         TO app_hotel;
GRANT SELECT                           ON tipos_habitacion TO app_hotel;
GRANT SELECT                           ON tarifas          TO app_hotel;
GRANT SELECT, UPDATE                   ON habitaciones     TO app_hotel;
GRANT SELECT, INSERT, UPDATE           ON reservas         TO app_hotel;
GRANT SELECT, INSERT                   ON bitacora         TO app_hotel;
GRANT SELECT, INSERT                   ON pagos            TO app_hotel;
GRANT SELECT, INSERT                   ON facturas         TO app_hotel;
GRANT UPDATE (estado, mensaje, respondida_en) ON facturas  TO app_hotel;
GRANT USAGE ON SEQUENCE consecutivo_factura TO app_hotel;

-- pg_dump también necesita leer las secuencias para respaldar sus valores
GRANT SELECT ON ALL TABLES    IN SCHEMA hotel TO respaldo;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA hotel TO respaldo;
ALTER DEFAULT PRIVILEGES IN SCHEMA hotel GRANT SELECT ON TABLES    TO respaldo;
ALTER DEFAULT PRIVILEGES IN SCHEMA hotel GRANT SELECT ON SEQUENCES TO respaldo;
