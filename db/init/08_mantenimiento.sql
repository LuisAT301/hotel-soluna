-- =====================================================================
-- Hotel Soluna: mantenimiento de la base de datos
-- Las consultas de lectura no dejan nada guardado en la base; lo que
-- crece con el uso son los registros: la bitácora, el historial de las
-- tareas programadas y las llaves de idempotencia del simulador. Esta
-- función los recorta según una política de retención y aplica una más
-- estricta si la base se acerca al límite del plan (ocupación alta).
--
-- En Supabase la ejecuta pg_cron: cada hora vigila la ocupación y cada
-- día limpia (ver supabase/migrations). En Docker no hay pg_cron ni
-- límite de plan; se puede ejecutar a mano:
--     docker compose exec db psql -U postgres -d hotel -c "SELECT mantenimiento()"
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
CREATE FUNCTION mantenimiento(solo_si_alta boolean DEFAULT false, limite_mb integer DEFAULT 500)
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
-- Los 365 días siguen el mínimo de 12 meses de PCI DSS 4.0 (req. 10.5.1); los 90 días, los 3 meses que
-- esa norma exige mantener disponibles de inmediato. La ocupación alta es una medida de emergencia: evita
-- que la base pase a solo lectura, que detendría las reservas y los pagos.
DECLARE
    tamano       bigint := pg_database_size(current_database());
    limite       bigint := limite_mb::bigint * 1024 * 1024;
    alta         boolean := tamano >= limite * 0.70;
    retencion    interval := CASE WHEN alta THEN interval '90 days' ELSE interval '365 days' END;
    n_bitacora   bigint := 0;
    n_cron       bigint := 0;
    n_idem       bigint := 0;
    resumen      text;
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

    resumen := format('%s de %s%s; borradas: %s de bitácora, %s del historial de pg_cron, %s de idempotencia.',
                      pg_size_pretty(tamano), pg_size_pretty(limite),
                      CASE WHEN alta THEN ' (OCUPACIÓN ALTA)' ELSE '' END, n_bitacora, n_cron, n_idem);

    -- Constancia en la bitácora, visible para gerencia en el panel
    INSERT INTO bitacora (accion, entidad, detalle) VALUES ('mantenimiento', 'base_de_datos', jsonb_build_object(
        'tamano_mb', round(tamano / 1048576.0, 1), 'limite_mb', limite_mb, 'ocupacion_alta', alta,
        'retencion_bitacora_dias', extract(day FROM retencion), 'bitacora', n_bitacora,
        'historial_cron', n_cron, 'idempotencia', n_idem));
    RETURN resumen;
END;
$$;

-- Solo el administrador la ejecuta: la API no puede borrar la bitácora
REVOKE ALL ON FUNCTION mantenimiento(boolean, integer) FROM PUBLIC;

-- ---------------------------------------------------------------------
-- Límites por consulta para los usuarios de las aplicaciones
-- Ninguna consulta de la API puede ocupar la base más de 15 s, ni una
-- transacción quedar abierta e inactiva más de 60 s. Los márgenes cubren
-- la espera más larga legítima: un pago bloquea su reserva mientras la
-- pasarela responde (hasta 12 s). El valor por omisión sería de minutos.
-- ---------------------------------------------------------------------
ALTER ROLE app_hotel SET statement_timeout = '15s';
ALTER ROLE app_hotel SET idle_in_transaction_session_timeout = '60s';
