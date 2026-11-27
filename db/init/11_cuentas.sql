-- =====================================================================
-- Hotel Soluna: cuenta de la habitación (consumos, pagos en caja y
-- factura final)
-- Durante la estadía, recepción carga a la cuenta lo que el huésped
-- consume (room service, restaurante, bar, spa, tours...). Al registrar
-- la salida se cobra lo pendiente y se emite la factura electrónica final
-- con una línea por consumo.
-- La base garantiza que nada de esto se borre ni se altere en silencio:
-- un cargo equivocado se anula con motivo (queda a la vista), un pago no
-- se edita, y los montos de una factura nunca cambian.
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================

-- Catálogo de servicios que gerencia mantiene; los cargos copian el precio
-- del momento, así que cambiarlo no altera lo ya cargado
CREATE TABLE servicios (
    id        smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre    text          NOT NULL UNIQUE CHECK (char_length(nombre) BETWEEN 2 AND 80),
    categoria text          NOT NULL CHECK (categoria IN ('room_service', 'restaurante', 'bar', 'minibar', 'spa',
                                                          'lavanderia', 'transporte', 'tours', 'otros')),
    precio    numeric(10,2) NOT NULL CHECK (precio > 0),          -- sin IVA
    activo    boolean       NOT NULL DEFAULT true
);

-- Consumos cargados a la cuenta de una reserva
CREATE TABLE cargos (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id       bigint        NOT NULL REFERENCES reservas (id),
    servicio_id      smallint      REFERENCES servicios (id),        -- nulo: cargo libre ("otro")
    categoria        text          NOT NULL CHECK (categoria IN ('room_service', 'restaurante', 'bar', 'minibar',
                                                                 'spa', 'lavanderia', 'transporte', 'tours', 'otros')),
    descripcion      text          NOT NULL CHECK (char_length(descripcion) BETWEEN 2 AND 120),
    cantidad         smallint      NOT NULL CHECK (cantidad BETWEEN 1 AND 99),
    precio_unitario  numeric(10,2) NOT NULL CHECK (precio_unitario > 0),   -- sin IVA
    total            numeric(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    creado_en        timestamptz   NOT NULL DEFAULT now(),
    creado_por       bigint        NOT NULL REFERENCES usuarios (id),
    anulado_en       timestamptz,
    anulado_por      bigint        REFERENCES usuarios (id),
    motivo_anulacion text,
    -- Una anulación siempre dice quién, cuándo y por qué
    CHECK ((anulado_en IS NULL) = (anulado_por IS NULL)),
    CHECK ((anulado_en IS NULL) = (motivo_anulacion IS NULL)),
    CHECK (motivo_anulacion IS NULL OR char_length(motivo_anulacion) BETWEEN 3 AND 200)
);
CREATE INDEX cargos_reserva_idx ON cargos (reserva_id);

-- Pagos recibidos en la recepción (al llegar, durante la estadía o al salir)
CREATE TABLE pagos_caja (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id   bigint        NOT NULL REFERENCES reservas (id),
    metodo       text          NOT NULL CHECK (metodo IN ('efectivo', 'tarjeta', 'sinpe', 'transferencia')),
    monto        numeric(10,2) NOT NULL CHECK (monto > 0),
    referencia   text          CHECK (char_length(referencia) BETWEEN 1 AND 60),   -- voucher o comprobante
    recibido_por bigint        NOT NULL REFERENCES usuarios (id),
    creado_en    timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX pagos_caja_reserva_idx ON pagos_caja (reserva_id);

-- Facturas: una reserva puede tener la del hospedaje pagado en línea y la
-- de la cuenta final; la cuenta final guarda sus líneas para reenviarla a
-- Hacienda si en el primer intento no respondió
ALTER TABLE facturas
    ADD COLUMN concepto text NOT NULL DEFAULT 'hospedaje' CHECK (concepto IN ('hospedaje', 'cuenta_final')),
    ADD COLUMN lineas jsonb,
    DROP CONSTRAINT facturas_reserva_id_key,
    ADD CONSTRAINT facturas_reserva_concepto_key UNIQUE (reserva_id, concepto);

-- Permisos de la API: el catálogo se agrega y se edita, pero no se borra
-- (los cargos lo referencian); un cargo solo cambia para anularse; un pago
-- en caja no cambia nunca
GRANT SELECT, INSERT ON servicios TO app_hotel;
GRANT UPDATE (nombre, categoria, precio, activo) ON servicios TO app_hotel;
GRANT SELECT, INSERT ON cargos TO app_hotel;
GRANT UPDATE (anulado_en, anulado_por, motivo_anulacion) ON cargos TO app_hotel;
GRANT SELECT, INSERT ON pagos_caja TO app_hotel;

-- Catálogo inicial (precios ficticios en dólares, sin IVA)
INSERT INTO servicios (nombre, categoria, precio) VALUES
    ('Desayuno americano a la habitación', 'room_service', 14.00),
    ('Club sándwich con papas',           'room_service', 12.00),
    ('Casado con pollo',                  'room_service', 13.00),
    ('Ensalada tropical',                 'room_service', 10.00),
    ('Cena del día',                      'restaurante',  22.00),
    ('Pescado entero frito',              'restaurante',  24.00),
    ('Postre tres leches',                'restaurante',   6.00),
    ('Batido natural',                    'bar',           5.00),
    ('Cerveza nacional',                  'bar',           4.00),
    ('Cóctel de la casa',                 'bar',           9.00),
    ('Agua embotellada',                  'minibar',       2.50),
    ('Snack del minibar',                 'minibar',       3.50),
    ('Masaje relajante de 60 minutos',    'spa',          75.00),
    ('Lavado y planchado (por pieza)',    'lavanderia',    3.00),
    ('Traslado al aeropuerto de Liberia', 'transporte',   85.00),
    ('Tour de tortugas en Ostional',      'tours',        65.00),
    ('Clase de surf de 2 horas',          'tours',        45.00),
    ('Salida tardía hasta las 4 p. m.',   'otros',        40.00),
    ('Cama extra por noche',              'otros',        25.00);
