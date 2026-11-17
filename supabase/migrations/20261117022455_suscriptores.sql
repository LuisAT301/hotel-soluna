-- =====================================================================
-- Hotel Soluna: correos suscritos desde el sitio web (esquema hotel)
-- Equivale a db/init/05_suscriptores.sql.
-- =====================================================================
SET search_path = hotel, extensions;

CREATE TABLE suscriptores (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correo    text        NOT NULL UNIQUE CHECK (correo = lower(correo)),
    origen    text        NOT NULL DEFAULT 'sitio_web',
    activo    boolean     NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT  ON suscriptores TO app_hotel;
GRANT UPDATE (activo) ON suscriptores TO app_hotel;
GRANT SELECT          ON suscriptores TO respaldo;
