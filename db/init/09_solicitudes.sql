-- =====================================================================
-- Hotel Soluna: solicitudes de huéspedes (chat con el personal)
-- Una solicitud es una conversación sobre una necesidad del huésped
-- durante su estadía (toallas, el aire acondicionado, un taxi) que
-- atiende un área del hotel. La base garantiza lo que no depende de
-- quién escribe: una sola solicitud abierta por reserva, mensajes de
-- longitud razonable que la API no puede editar ni borrar, y que al
-- borrar una solicitud vieja (retención) se borren también sus mensajes.
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
CREATE TABLE solicitudes (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id      bigint      NOT NULL REFERENCES reservas (id),
    categoria       text        NOT NULL DEFAULT 'recepcion'           -- área que la atiende
                    CHECK (categoria IN ('recepcion', 'limpieza', 'mantenimiento')),
    estado          text        NOT NULL DEFAULT 'abierta'
                    CHECK (estado IN ('abierta', 'en_atencion', 'resuelta')),
    asignada_a      bigint      REFERENCES usuarios (id),              -- quién la tomó
    simulada        boolean     NOT NULL DEFAULT false,                -- la creó el simulador de huéspedes
    creada_en       timestamptz NOT NULL DEFAULT now(),
    actualizada_en  timestamptz NOT NULL DEFAULT now(),                -- último mensaje o cambio
    pendiente_desde timestamptz,                                       -- el huésped espera respuesta desde aquí
    resuelta_en     timestamptz,
    CHECK ((estado = 'resuelta') = (resuelta_en IS NOT NULL))
);

-- Una sola solicitud abierta por reserva: los mensajes nuevos del huésped van a ella
CREATE UNIQUE INDEX solicitudes_una_abierta_idx ON solicitudes (reserva_id) WHERE estado <> 'resuelta';
-- El chat del huésped busca por reserva; el panel del personal pide solo lo que cambió
CREATE INDEX solicitudes_reserva_idx ON solicitudes (reserva_id);
CREATE INDEX solicitudes_actualizada_idx ON solicitudes (actualizada_en);

CREATE TABLE mensajes (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    solicitud_id bigint      NOT NULL REFERENCES solicitudes (id) ON DELETE CASCADE,
    autor        text        NOT NULL CHECK (autor IN ('huesped', 'personal')),
    usuario_id   bigint      REFERENCES usuarios (id),                 -- nulo para el huésped simulado
    texto        text        NOT NULL CHECK (char_length(texto) BETWEEN 1 AND 1000),
    creado_en    timestamptz NOT NULL DEFAULT now(),
    CHECK (autor = 'huesped' OR usuario_id IS NOT NULL)                -- el personal siempre se identifica
);
-- Cada conversación se lee en orden y solo desde el último mensaje que ya tiene la pantalla
CREATE INDEX mensajes_solicitud_idx ON mensajes (solicitud_id, id);

-- La API crea y lee; de una solicitud solo cambia su estado, área, asignación y tiempos.
-- Los mensajes no se editan ni se borran.
GRANT SELECT, INSERT ON solicitudes TO app_hotel;
GRANT UPDATE (categoria, estado, asignada_a, actualizada_en, pendiente_desde, resuelta_en) ON solicitudes TO app_hotel;
GRANT SELECT, INSERT ON mensajes TO app_hotel;

-- ---------------------------------------------------------------------
-- Mantenimiento: se agrega la retención de solicitudes resueltas
-- (reemplaza la función de 08_mantenimiento.sql)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION mantenimiento(solo_si_alta boolean DEFAULT false, limite_mb integer DEFAULT 500)
RETURNS text
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
-- Parámetros:
--   solo_si_alta  true: solo limpia si la ocupación es alta (la vigilancia de cada hora).
--   limite_mb     cuota de la base; 500 MB en el plan gratuito de Supabase.
-- Política de retención:
--                         ocupación normal   ocupación alta (70 % del límite o más)
--   bitácora              365 días           90 días
--   historial de pg_cron  7 días             3 días
--   idempotencia          7 días             7 días
--   solicitudes resueltas 90 días            30 días (con sus mensajes)
-- Los 365 días siguen el mínimo de 12 meses de PCI DSS 4.0 (req. 10.5.1); los 90 días, los 3 meses que
-- esa norma exige mantener disponibles de inmediato. Las conversaciones con huéspedes contienen datos
-- personales: se conservan solo lo necesario para atender reclamos posteriores a la estadía.
-- La ocupación alta es una medida de emergencia: evita que la base pase a solo lectura, que detendría
-- las reservas y los pagos.
DECLARE
    tamano          bigint := pg_database_size(current_database());
    limite          bigint := limite_mb::bigint * 1024 * 1024;
    alta            boolean := tamano >= limite * 0.70;
    retencion       interval := CASE WHEN alta THEN interval '90 days' ELSE interval '365 days' END;
    ret_solicitudes interval := CASE WHEN alta THEN interval '30 days' ELSE interval '90 days' END;
    n_bitacora      bigint := 0;
    n_cron          bigint := 0;
    n_idem          bigint := 0;
    n_solicitudes   bigint := 0;
    resumen         text;
BEGIN
    IF solo_si_alta AND NOT alta THEN
        RETURN format('Ocupación normal (%s de %s): no se limpió nada.',
                      pg_size_pretty(tamano), pg_size_pretty(limite));
    END IF;

    -- 1. Bitácora: por lotes de 50 000 filas, para que cada corrida termine rápido
    DELETE FROM bitacora WHERE id IN (
        SELECT id FROM bitacora WHERE fecha < now() - retencion ORDER BY id LIMIT 50000);
    GET DIAGNOSTICS n_bitacora = ROW_COUNT;

    -- 2. Historial de pg_cron: no se borra solo y crece con cada ejecución (solo en Supabase)
    IF to_regclass('cron.job_run_details') IS NOT NULL THEN
        DELETE FROM cron.job_run_details
        WHERE end_time < now() - CASE WHEN alta THEN interval '3 days' ELSE interval '7 days' END;
        GET DIAGNOSTICS n_cron = ROW_COUNT;
    END IF;

    -- 3. Simulador: tokens vencidos y llaves de idempotencia de más de 7 días (solo si guarda en la base)
    IF to_regclass('simulador.idempotencia') IS NOT NULL THEN
        DELETE FROM simulador.idempotencia WHERE creado_en < now() - interval '7 days';
        GET DIAGNOSTICS n_idem = ROW_COUNT;
        DELETE FROM simulador.tokens WHERE vence < now();
    END IF;

    -- 4. Solicitudes resueltas hace tiempo; sus mensajes se borran en cascada
    DELETE FROM solicitudes WHERE id IN (
        SELECT id FROM solicitudes WHERE estado = 'resuelta' AND resuelta_en < now() - ret_solicitudes
        ORDER BY id LIMIT 50000);
    GET DIAGNOSTICS n_solicitudes = ROW_COUNT;

    resumen := format('%s de %s%s; borradas: %s de bitácora, %s del historial de pg_cron, %s de idempotencia, '
                      '%s solicitudes resueltas.',
                      pg_size_pretty(tamano), pg_size_pretty(limite),
                      CASE WHEN alta THEN ' (OCUPACIÓN ALTA)' ELSE '' END, n_bitacora, n_cron, n_idem,
                      n_solicitudes);

    -- Constancia en la bitácora, visible para gerencia en el panel
    INSERT INTO bitacora (accion, entidad, detalle) VALUES ('mantenimiento', 'base_de_datos', jsonb_build_object(
        'tamano_mb', round(tamano / 1048576.0, 1), 'limite_mb', limite_mb, 'ocupacion_alta', alta,
        'retencion_bitacora_dias', extract(day FROM retencion), 'bitacora', n_bitacora,
        'historial_cron', n_cron, 'idempotencia', n_idem, 'solicitudes', n_solicitudes));
    RETURN resumen;
END;
$$;

REVOKE ALL ON FUNCTION mantenimiento(boolean, integer) FROM PUBLIC;
