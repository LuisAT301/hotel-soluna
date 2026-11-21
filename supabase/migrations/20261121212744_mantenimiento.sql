-- =====================================================================
-- Hotel Soluna: mantenimiento automático de la base (esquema "hotel")
-- Igual que db/init/08_mantenimiento.sql, más la programación con
-- pg_cron, que solo existe en Supabase:
--   soluna-vigilar-ocupacion  cada hora, minuto 47: limpia solo si la base
--                             llegó al 70 % de los 500 MB del plan gratuito.
--   soluna-limpieza-diaria    todos los días a las 09:17 UTC (03:17 en
--                             Costa Rica): aplica la retención normal.
-- El resultado de cada corrida queda en cron.job_run_details (Integrations
-- > Cron > History en el panel), y la limpieza diaria, en la bitácora.
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;
GRANT USAGE ON SCHEMA cron TO postgres;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA cron TO postgres;

SET search_path = hotel, extensions;

CREATE FUNCTION mantenimiento(solo_si_alta boolean DEFAULT false, limite_mb integer DEFAULT 500)
RETURNS text
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
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
REVOKE ALL ON FUNCTION hotel.mantenimiento(boolean, integer) FROM PUBLIC;

-- Límites por consulta (ver db/init/08_mantenimiento.sql)
ALTER ROLE app_hotel     SET statement_timeout = '15s';
ALTER ROLE app_hotel     SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE app_simulador SET statement_timeout = '15s';
ALTER ROLE app_simulador SET idle_in_transaction_session_timeout = '60s';

-- Programación (un nombre repetido reemplaza la tarea, así que es idempotente)
SELECT cron.schedule('soluna-vigilar-ocupacion', '47 * * * *', 'SELECT hotel.mantenimiento(true)');
SELECT cron.schedule('soluna-limpieza-diaria',   '17 9 * * *', 'SELECT hotel.mantenimiento()');
