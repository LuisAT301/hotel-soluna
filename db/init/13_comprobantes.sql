-- =====================================================================
-- Hotel Soluna: comprobantes de pago por SINPE Móvil o transferencia
-- El cliente que no paga con tarjeta sube el comprobante (número y, si
-- quiere, una imagen o PDF) y recepción lo revisa: al aceptarlo se
-- registra el pago, se confirma la reserva y se emite la factura; al
-- rechazarlo queda el motivo y el cliente puede enviar otro. La imagen se
-- comprime en el navegador y se borra 90 días después de revisada; el
-- registro se conserva como respaldo del pago.
-- Si cambia este archivo, actualice también supabase/migrations.
-- =====================================================================
CREATE TABLE comprobantes (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserva_id   bigint        NOT NULL REFERENCES reservas (id),
    metodo       text          NOT NULL CHECK (metodo IN ('sinpe', 'transferencia')),
    numero       text          NOT NULL CHECK (numero ~ '^[A-Z0-9-]{4,40}$'),   -- en mayúsculas
    monto        numeric(10,2) NOT NULL CHECK (monto > 0),                     -- lo que el cliente dice que pagó
    archivo      bytea         CHECK (octet_length(archivo) <= 1572864),       -- 1,5 MB como máximo
    tipo_archivo text          CHECK (tipo_archivo IN ('image/jpeg', 'image/png', 'application/pdf')),
    estado       text          NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aceptado', 'rechazado')),
    motivo       text          CHECK (char_length(motivo) BETWEEN 3 AND 200),
    enviado_por  bigint        NOT NULL REFERENCES usuarios (id),
    enviado_en   timestamptz   NOT NULL DEFAULT now(),
    revisado_por bigint        REFERENCES usuarios (id),
    revisado_en  timestamptz,
    -- Un archivo siempre dice qué es; tipo_archivo se conserva cuando la retención borra el archivo
    CHECK (archivo IS NULL OR tipo_archivo IS NOT NULL),
    -- Una revisión siempre dice quién y cuándo; un rechazo, además, por qué
    CHECK ((estado = 'pendiente') = (revisado_por IS NULL)),
    CHECK ((estado = 'pendiente') = (revisado_en IS NULL)),
    CHECK ((estado = 'rechazado') = (motivo IS NOT NULL))
);
-- Un solo comprobante en revisión por reserva
CREATE UNIQUE INDEX comprobantes_un_pendiente ON comprobantes (reserva_id) WHERE estado = 'pendiente';
-- Un mismo comprobante no puede respaldar dos pagos (un rechazado sí puede volver a enviarse)
CREATE UNIQUE INDEX comprobantes_numero_unico ON comprobantes (metodo, numero) WHERE estado <> 'rechazado';
CREATE INDEX comprobantes_reserva_idx ON comprobantes (reserva_id);
-- La bandeja de recepción lee solo los pendientes, del más antiguo al más reciente
CREATE INDEX comprobantes_pendientes_idx ON comprobantes (enviado_en) WHERE estado = 'pendiente';

-- Permisos de la API: crea y lee comprobantes; de uno ya enviado solo escribe la revisión.
-- No puede borrarlos ni cambiar el número, el monto o el archivo.
GRANT SELECT, INSERT ON comprobantes TO app_hotel;
GRANT UPDATE (estado, motivo, revisado_por, revisado_en) ON comprobantes TO app_hotel;
GRANT SELECT ON comprobantes TO respaldo;

-- ---------------------------------------------------------------------
-- Mantenimiento: se agrega la retención de las imágenes de comprobantes
-- (reemplaza la función de 09_solicitudes.sql)
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
--   imágenes de comprobantes revisados  90 días   30 días (se conserva el resto del registro)
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
    n_archivos      bigint := 0;
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

    -- 5. Imágenes de comprobantes de pago ya revisados: se borra el archivo y queda el registro
    --    (método, número, monto, quién lo revisó y cuándo), que es lo que respalda el pago
    UPDATE comprobantes SET archivo = NULL WHERE id IN (
        SELECT id FROM comprobantes WHERE archivo IS NOT NULL AND revisado_en < now() - ret_solicitudes
        ORDER BY id LIMIT 50000);
    GET DIAGNOSTICS n_archivos = ROW_COUNT;

    resumen := format('%s de %s%s; borradas: %s de bitácora, %s del historial de pg_cron, %s de idempotencia, '
                      '%s solicitudes resueltas, %s imágenes de comprobantes.',
                      pg_size_pretty(tamano), pg_size_pretty(limite),
                      CASE WHEN alta THEN ' (OCUPACIÓN ALTA)' ELSE '' END, n_bitacora, n_cron, n_idem,
                      n_solicitudes, n_archivos);

    -- Constancia en la bitácora, visible para gerencia en el panel
    INSERT INTO bitacora (accion, entidad, detalle) VALUES ('mantenimiento', 'base_de_datos', jsonb_build_object(
        'tamano_mb', round(tamano / 1048576.0, 1), 'limite_mb', limite_mb, 'ocupacion_alta', alta,
        'retencion_bitacora_dias', extract(day FROM retencion), 'bitacora', n_bitacora,
        'historial_cron', n_cron, 'idempotencia', n_idem, 'solicitudes', n_solicitudes,
        'imagenes_comprobantes', n_archivos));
    RETURN resumen;
END;
$$;

REVOKE ALL ON FUNCTION mantenimiento(boolean, integer) FROM PUBLIC;
