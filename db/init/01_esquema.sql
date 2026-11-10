-- =====================================================================
-- Hotel Soluna: esquema principal de la base de datos
-- PostgreSQL ejecuta este archivo una sola vez, al crear el volumen
-- de datos por primera vez (carpeta /docker-entrypoint-initdb.d).
-- =====================================================================

-- btree_gist permite combinar "=" y "&&" en una misma restricción
-- de exclusión (la regla contra la sobreventa de la tabla reservas).
CREATE EXTENSION IF NOT EXISTS btree_gist;

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
-- Reservas
-- ---------------------------------------------------------------------
CREATE TABLE reservas (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo         text          NOT NULL UNIQUE,
    habitacion_id  bigint        NOT NULL REFERENCES habitaciones (id),
    cliente_id     bigint        REFERENCES usuarios (id),   -- nulo si la crea recepción para alguien sin cuenta
    nombre_huesped text          NOT NULL,
    correo_huesped text          NOT NULL,
    personas       smallint      NOT NULL CHECK (personas > 0),
    fecha_entrada  date          NOT NULL,
    fecha_salida   date          NOT NULL,
    canal          text          NOT NULL CHECK (canal IN ('web', 'recepcion', 'ota')),
    estado         text          NOT NULL
                   CHECK (estado IN ('pendiente_pago', 'confirmada', 'en_curso',
                                     'finalizada', 'cancelada')),
    total          numeric(10,2) NOT NULL CHECK (total >= 0),
    creada_por     bigint        REFERENCES usuarios (id),
    creada_en      timestamptz   NOT NULL DEFAULT now(),
    actualizada_en timestamptz   NOT NULL DEFAULT now(),
    CHECK (fecha_salida > fecha_entrada),

    -- Regla contra la sobreventa: dos reservas activas de la misma
    -- habitación no pueden traslaparse en fechas. El rango [entrada, salida)
    -- deja libre el día de salida para que otro huésped entre ese día.
    -- La base de datos la aplica aunque dos solicitudes lleguen al mismo
    -- tiempo desde réplicas distintas de la API.
    CONSTRAINT sin_traslape EXCLUDE USING gist (
        habitacion_id WITH =,
        (daterange(fecha_entrada, fecha_salida)) WITH &&
    ) WHERE (estado <> 'cancelada')
);

CREATE INDEX reservas_cliente_idx ON reservas (cliente_id);
CREATE INDEX reservas_fechas_idx  ON reservas (fecha_entrada, fecha_salida);

-- ---------------------------------------------------------------------
-- Bitácora de auditoría (RNF-12): quién hizo qué y cuándo
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
