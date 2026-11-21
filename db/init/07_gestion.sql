-- =====================================================================
-- Hotel Soluna: gestión de reservas en recepción
-- El detalle de una reserva muestra su historial, que se busca en la
-- bitácora por el código de la reserva (entidad_id). Sin este índice, cada
-- consulta recorrería la bitácora completa, que crece con cada acción.
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
CREATE INDEX bitacora_entidad_idx ON bitacora (entidad_id, fecha);
