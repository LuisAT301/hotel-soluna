-- =====================================================================
-- Hotel Soluna: reservas por teléfono (esquema "hotel")
-- Igual que db/init/10_reservas_telefono.sql: teléfono de contacto del
-- huésped y canal "telefono". Compatible con la versión anterior de la
-- API: la columna admite nulos y el canal solo suma un valor.
-- =====================================================================
SET search_path = hotel, extensions;

ALTER TABLE reservas ADD COLUMN telefono_huesped text
    CHECK (telefono_huesped ~ '^\+?[0-9 ()-]{8,20}$');

ALTER TABLE reservas
    DROP CONSTRAINT reservas_canal_check,
    ADD CONSTRAINT reservas_canal_check CHECK (canal IN ('web', 'recepcion', 'telefono', 'ota'));
