-- =====================================================================
-- Hotel Soluna: reseñas verificadas de huéspedes (esquema "hotel")
-- Igual que db/init/06_resenas.sql. Solo opina quien tiene una cuenta
-- activa y una reservación propia ya cumplida; esas reglas las aplica la
-- API. La base garantiza una reseña por reservación, calificación de 1 a 5
-- y un comentario de longitud razonable.
-- =====================================================================
SET search_path = hotel, extensions;

CREATE TABLE resenas (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id   bigint      NOT NULL UNIQUE REFERENCES reservas (id),   -- una reseña por estadía
    usuario_id   bigint      NOT NULL REFERENCES usuarios (id),          -- cuenta que la escribió
    calificacion smallint    NOT NULL CHECK (calificacion BETWEEN 1 AND 5),
    comentario   text        NOT NULL CHECK (char_length(comentario) BETWEEN 10 AND 1000),
    creada_en    timestamptz NOT NULL DEFAULT now()
);

-- El sitio muestra las más recientes primero
CREATE INDEX resenas_creada_idx ON resenas (creada_en DESC);

-- La API publica y consulta reseñas, pero no puede modificarlas ni borrarlas;
-- el usuario de respaldos solo lee.
GRANT SELECT, INSERT ON resenas TO app_hotel;
GRANT SELECT ON resenas TO respaldo;
