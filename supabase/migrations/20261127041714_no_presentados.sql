-- =====================================================================
-- Hotel Soluna: liberación automática de reservas no presentadas
-- (esquema "hotel"). Igual que db/init/12_no_presentados.sql, más la
-- programación con pg_cron, que solo existe en Supabase:
--   soluna-liberar-no-presentados  cada hora, minuto 5: cancela las
--       reservas que se pagan al llegar (recepción o teléfono), confirmadas,
--       sin adelanto y tomadas antes de las 17:00 (hora de Costa Rica) de su
--       día de entrada, cuando esa hora ya pasó. Con la corrida de las
--       17:05 la habitación queda libre a los pocos minutos del plazo.
-- Cada reserva liberada queda en la bitácora sin usuario (acción del
-- sistema) y el resultado de cada corrida, en cron.job_run_details.
-- =====================================================================
SET search_path = hotel, extensions;

CREATE FUNCTION liberar_no_presentados(hora_garantia integer DEFAULT 17)
RETURNS TABLE (codigo_reserva text, numero_habitacion text, entrada date)
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
AS $$
-- Devuelve las reservas liberadas. Es idempotente: una reserva liberada
-- queda cancelada y no vuelve a cumplir las condiciones.
BEGIN
    RETURN QUERY
    WITH liberadas AS (
        UPDATE reservas r
        SET estado = 'cancelada', actualizada_en = now()
        WHERE r.estado = 'confirmada'                                   -- no ha ingresado
          AND r.canal IN ('recepcion', 'telefono')                      -- se paga al llegar
          -- pasó la hora de garantía (17:00 hora de Costa Rica del día de entrada)...
          AND (r.fecha_entrada + make_time(hora_garantia, 0, 0)) AT TIME ZONE 'America/Costa_Rica' <= now()
          -- ...y la reserva se tomó antes de esa hora
          AND r.creada_en < (r.fecha_entrada + make_time(hora_garantia, 0, 0)) AT TIME ZONE 'America/Costa_Rica'
          AND NOT EXISTS (SELECT 1 FROM pagos_caja p WHERE p.reserva_id = r.id)   -- sin adelanto
        RETURNING r.codigo, r.habitacion_id, r.fecha_entrada
    ), constancia AS (
        INSERT INTO bitacora (accion, entidad, entidad_id, detalle)
        SELECT 'liberar_no_presentado', 'reserva', l.codigo,
               jsonb_build_object('fecha_entrada', l.fecha_entrada, 'hora_garantia', hora_garantia)
        FROM liberadas l
    )
    SELECT l.codigo, h.numero, l.fecha_entrada
    FROM liberadas l JOIN habitaciones h ON h.id = l.habitacion_id
    ORDER BY l.fecha_entrada, l.codigo;
END;
$$;

-- La ejecutan el administrador (pg_cron) y la API (botón de recepción)
REVOKE ALL ON FUNCTION hotel.liberar_no_presentados(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION hotel.liberar_no_presentados(integer) TO app_hotel;

-- Programación (un nombre repetido reemplaza la tarea, así que es idempotente).
-- pg_cron usa UTC; el minuto 5 de cada hora cubre las 17:05 de Costa Rica (23:05 UTC).
SELECT cron.schedule('soluna-liberar-no-presentados', '5 * * * *',
                     'SELECT count(*) FROM hotel.liberar_no_presentados()');
