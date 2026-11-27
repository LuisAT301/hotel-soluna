-- =====================================================================
-- Hotel Soluna: reservas por teléfono
-- Recepción registra las reservas que llegan por teléfono con un número de
-- contacto y el canal "telefono", para distinguirlas de las que se hacen
-- en el mostrador ("recepcion"). Ambas se pagan al llegar y se garantizan
-- hasta las 17:00 del día de entrada (regla de la API, ver reservas.py).
-- El formato del teléfono se revisa también aquí: solo números, espacios,
-- guiones, paréntesis y un "+" inicial; la API exige además 8 a 15 dígitos.
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
ALTER TABLE reservas ADD COLUMN telefono_huesped text
    CHECK (telefono_huesped ~ '^\+?[0-9 ()-]{8,20}$');

ALTER TABLE reservas
    DROP CONSTRAINT reservas_canal_check,
    ADD CONSTRAINT reservas_canal_check CHECK (canal IN ('web', 'recepcion', 'telefono', 'ota'));
