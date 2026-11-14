-- =====================================================================
-- Hotel Soluna: correos suscritos desde el sitio web
-- Personas que dejan su correo en el sitio para recibir ofertas y
-- novedades. Se guardan para enviarles correos más adelante con un
-- servicio de envío (hoy los captura Mailpit).
-- Si cambia esta tabla, actualice también supabase/migrations.
-- =====================================================================
CREATE TABLE suscriptores (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correo    text        NOT NULL UNIQUE CHECK (correo = lower(correo)),
    origen    text        NOT NULL DEFAULT 'sitio_web',
    activo    boolean     NOT NULL DEFAULT true,   -- false si pide no recibir más correos
    creado_en timestamptz NOT NULL DEFAULT now()
);

-- La API agrega correos y los consulta; no puede borrarlos (solo desactivarlos)
GRANT SELECT, INSERT     ON suscriptores TO app_hotel;
GRANT UPDATE (activo)    ON suscriptores TO app_hotel;
