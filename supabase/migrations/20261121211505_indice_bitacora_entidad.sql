-- =====================================================================
-- Hotel Soluna: índice para el historial de reservas (esquema "hotel")
-- Igual que db/init/07_gestion.sql. El panel de recepción busca en la
-- bitácora todo lo ocurrido con una reserva por su código (entidad_id).
-- =====================================================================
SET search_path = hotel, extensions;

CREATE INDEX IF NOT EXISTS bitacora_entidad_idx ON bitacora (entidad_id, fecha);
