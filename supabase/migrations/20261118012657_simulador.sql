-- =====================================================================
-- Hotel Soluna: estado del simulador de servicios externos (fase 2)
--
-- En Vercel el simulador corre en varias instancias a la vez, así que lo que
-- en Docker guarda en memoria vive aquí. Es un esquema aparte, con su propio
-- usuario (app_simulador): la pasarela, Hacienda y la OTA son "otros
-- proveedores" y no ven los datos del hotel, ni el hotel ve los suyos.
--
-- Ninguna tabla guarda el número completo de la tarjeta ni el CVV.
-- =====================================================================
CREATE SCHEMA simulador;
SET search_path = simulador;

-- Tokens de tarjeta de un solo uso (15 minutos): marca, últimos 4 dígitos y resultado
CREATE TABLE tokens (
    token text        PRIMARY KEY,
    datos jsonb       NOT NULL,
    vence timestamptz NOT NULL
);
CREATE INDEX tokens_vence_idx ON tokens (vence);

-- Respuestas ya dadas por llave de idempotencia: un reintento no cobra dos veces
CREATE TABLE idempotencia (
    llave     text        PRIMARY KEY,
    huella    text        NOT NULL,
    respuesta jsonb       NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now()
);

-- Cobros y reembolsos; "reembolso" se anota una sola vez
CREATE TABLE cobros (
    transaccion text        PRIMARY KEY,
    datos       jsonb       NOT NULL,
    reembolso   text,
    creado_en   timestamptz NOT NULL DEFAULT now()
);

-- Facturas electrónicas recibidas por "Hacienda"
CREATE TABLE comprobantes (
    clave       text        PRIMARY KEY,
    comprobante jsonb       NOT NULL,
    respuesta   jsonb       NOT NULL,
    creado_en   timestamptz NOT NULL DEFAULT now()
);

-- Avisos de reserva enviados por la OTA y la respuesta del hotel
CREATE TABLE avisos_ota (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resultado jsonb       NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Usuario del simulador: sin inicio de sesión hasta activarlo (ver README)
-- ---------------------------------------------------------------------
CREATE ROLE app_simulador NOLOGIN;
ALTER ROLE app_simulador SET search_path = simulador;

REVOKE ALL ON SCHEMA simulador FROM PUBLIC;
GRANT USAGE ON SCHEMA simulador TO app_simulador, respaldo;

GRANT SELECT, INSERT, DELETE ON tokens       TO app_simulador;  -- un token se borra al usarse
GRANT SELECT, INSERT         ON idempotencia TO app_simulador;
GRANT SELECT, INSERT         ON cobros       TO app_simulador;
GRANT UPDATE (reembolso)     ON cobros       TO app_simulador;  -- nada más de un cobro cambia
GRANT SELECT, INSERT         ON comprobantes TO app_simulador;
GRANT SELECT, INSERT         ON avisos_ota   TO app_simulador;

GRANT SELECT ON ALL TABLES IN SCHEMA simulador TO respaldo;
