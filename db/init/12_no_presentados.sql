-- =====================================================================
-- Hotel Soluna: liberación automática de reservas no presentadas
-- Las reservas que se pagan al llegar (recepción o teléfono) se garantizan
-- hasta las 17:00 del día de entrada. Si a esa hora el huésped no registró
-- su ingreso y no pagó ningún adelanto, la reserva se cancela y la
-- habitación vuelve a estar disponible, como anuncia el correo de
-- confirmación. No se tocan las reservas tomadas después de esa hora del
-- mismo día de llegada (no tuvieron plazo que vencer). Queda constancia en
-- la bitácora (sin usuario: lo hizo el sistema). Son las mismas
-- condiciones de garantia_hasta en api/app/routers/reservas.py.
--
-- En Supabase la ejecuta pg_cron cada hora (ver supabase/migrations); la
-- API también la llama cuando recepción pulsa "Liberar no presentados".
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
CREATE FUNCTION liberar_no_presentados(hora_garantia integer DEFAULT 17)
RETURNS TABLE (codigo_reserva text, numero_habitacion text, entrada date)
LANGUAGE plpgsql
SET search_path = public, pg_catalog
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
REVOKE ALL ON FUNCTION liberar_no_presentados(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION liberar_no_presentados(integer) TO app_hotel;
