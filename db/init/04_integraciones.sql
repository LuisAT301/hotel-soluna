-- =====================================================================
-- Hotel Soluna: tablas del bloque 3 (pagos, facturas y reservas de OTA)
-- Se ejecuta después de 03_usuarios_bd.sh, así que el usuario app_hotel
-- ya existe y aquí mismo se le dan los permisos mínimos.
-- =====================================================================

-- Las agencias de viajes en línea (OTA) envían su propio número de
-- reserva. Ser único evita duplicados si la OTA reenvía el mismo aviso.
ALTER TABLE reservas ADD COLUMN referencia_externa text UNIQUE;

-- ---------------------------------------------------------------------
-- Pagos con tarjeta procesados por la pasarela
-- Nunca se guarda el número de tarjeta ni el código de seguridad: la
-- pasarela los recibe directamente del navegador y la API solo conoce
-- un token de un solo uso, la marca y los últimos cuatro dígitos.
-- ---------------------------------------------------------------------
CREATE TABLE pagos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id  bigint        NOT NULL REFERENCES reservas (id),
    tipo        text          NOT NULL CHECK (tipo IN ('cobro', 'reembolso')),
    estado      text          NOT NULL CHECK (estado IN ('aprobado', 'rechazado')),
    transaccion text          NOT NULL UNIQUE,     -- identificador de la pasarela
    monto       numeric(10,2) NOT NULL CHECK (monto >= 0),
    marca       text,
    ultimos4    char(4)       CHECK (ultimos4 ~ '^[0-9]{4}$'),
    motivo      text,                              -- motivo del rechazo, si lo hubo
    creado_en   timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX pagos_reserva_idx ON pagos (reserva_id);

-- ---------------------------------------------------------------------
-- Facturas electrónicas enviadas al simulador de Hacienda
-- La clave numérica (50 dígitos) y el consecutivo (20 dígitos) siguen el
-- formato de los comprobantes electrónicos de Costa Rica.
-- ---------------------------------------------------------------------
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
    mensaje       text,                             -- respuesta de Hacienda
    emitida_en    timestamptz   NOT NULL DEFAULT now(),
    respondida_en timestamptz
);

-- ---------------------------------------------------------------------
-- Permisos de la API: los pagos no se modifican ni se borran (un
-- reembolso es un registro nuevo); de una factura solo cambia el estado.
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT         ON pagos    TO app_hotel;
GRANT SELECT, INSERT         ON facturas TO app_hotel;
GRANT UPDATE (estado, mensaje, respondida_en) ON facturas TO app_hotel;  -- montos y clave, nunca
GRANT USAGE                  ON SEQUENCE consecutivo_factura TO app_hotel;
