-- =====================================================================
-- Hotel Soluna: historial simulado (solo en Supabase)
-- Huéspedes ficticios que llegan, se hospedan y se van solos, para que el
-- sistema publicado acumule un historial realista de reservas, cobros,
-- facturas y limpieza. Todo vive en el esquema "simulacion", que el
-- respaldo no copia (solo copia "hotel"), y solo toca las estadías que
-- están registradas en simulacion.estadias: las reservas reales y las de
-- prueba del personal no se ven afectadas.
--
--   simulacion.nuevo_lote(cantidad, dias)  crea huéspedes que llegan hoy,
--       con salida al azar en los próximos "dias" días.
--   simulacion.registrar_salidas()        registra la salida de las
--       estadías simuladas cuya fecha y hora de salida ya pasaron: cobra el
--       saldo, emite la factura final y deja la habitación sucia.
--   simulacion.limpiar_habitaciones()     en horario de limpieza, deja
--       limpias las habitaciones que una estadía simulada desocupó hace
--       al menos dos horas.
--   simulacion.borrar()                   elimina toda la simulación.
--
-- pg_cron ejecuta las salidas y la limpieza cada hora (minuto 20). Los
-- correos son de dominios .test, que la API nunca envía.
-- =====================================================================
CREATE SCHEMA simulacion;
REVOKE ALL ON SCHEMA simulacion FROM PUBLIC;

-- Estadías simuladas y la hora a la que cada huésped deja la habitación
CREATE TABLE simulacion.estadias (
    reserva_id  bigint      PRIMARY KEY REFERENCES hotel.reservas (id) ON DELETE CASCADE,
    hora_salida time        NOT NULL DEFAULT '10:00' CHECK (hora_salida BETWEEN '06:00' AND '12:00'),
    agregada_en timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Salidas: lo mismo que hace recepción con "Registrar salida"
-- ---------------------------------------------------------------------
CREATE FUNCTION simulacion.registrar_salidas()
RETURNS integer
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
AS $$
-- Algoritmo, por cada estadía simulada en curso cuya salida ya pasó:
--   1. Calcula la cuenta como la API: hospedaje (solo si se paga en el
--      hotel) + consumos vigentes + IVA del 13 % - pagos en caja.
--   2. Si queda saldo, lo cobra con un método al azar.
--   3. Si hubo algo que cobrar en el hotel, emite la factura final con una
--      línea por concepto, aceptada.
--   4. Cierra las solicitudes abiertas, deja la habitación sucia, finaliza
--      la reserva y deja constancia en la bitácora a nombre de recepción.
DECLARE
    r          record;
    recepcion  bigint;
    hospedaje  numeric(10,2);
    consumos   numeric(10,2);
    subtotal   numeric(10,2);
    impuesto   numeric(10,2);
    saldo      numeric(10,2);
    noches     integer;
    metodo     text;
    lineas     jsonb;
    consec     text;
    detalle    jsonb;
    hechas     integer := 0;
BEGIN
    SELECT u.id INTO recepcion FROM usuarios u WHERE u.correo = 'recepcion@soluna.test';
    FOR r IN
        SELECT res.id, res.codigo, res.canal, res.total, res.fecha_entrada, res.fecha_salida, res.habitacion_id,
               h.numero, t.nombre AS tipo
        FROM simulacion.estadias e
        JOIN reservas res ON res.id = e.reserva_id
        JOIN habitaciones h ON h.id = res.habitacion_id
        JOIN tipos_habitacion t ON t.id = h.tipo_id
        WHERE res.estado = 'en_curso'
          AND (res.fecha_salida + e.hora_salida) AT TIME ZONE 'America/Costa_Rica' <= now()
        ORDER BY res.fecha_salida, e.hora_salida
        FOR UPDATE OF res
    LOOP
        hospedaje := CASE WHEN r.canal IN ('recepcion', 'telefono') THEN r.total ELSE 0 END;
        SELECT coalesce(sum(c.total), 0) INTO consumos FROM cargos c WHERE c.reserva_id = r.id AND c.anulado_en IS NULL;
        subtotal := hospedaje + consumos;
        impuesto := round(subtotal * 0.13, 2);
        SELECT subtotal + impuesto - coalesce(sum(p.monto), 0) INTO saldo FROM pagos_caja p WHERE p.reserva_id = r.id;
        detalle := jsonb_build_object('habitacion', r.numero, 'replica', 'simulacion');

        IF saldo > 0 THEN
            metodo := (ARRAY['tarjeta', 'tarjeta', 'efectivo', 'sinpe'])[1 + floor(random() * 4)::int];
            INSERT INTO pagos_caja (reserva_id, metodo, monto, recibido_por) VALUES (r.id, metodo, saldo, recepcion);
            detalle := detalle || jsonb_build_object('cobrado', saldo::text, 'metodo_pago', metodo);
        END IF;

        IF subtotal > 0 AND NOT EXISTS (SELECT 1 FROM facturas f WHERE f.reserva_id = r.id AND f.concepto = 'cuenta_final') THEN
            lineas := '[]'::jsonb;
            IF hospedaje > 0 THEN
                noches := r.fecha_salida - r.fecha_entrada;
                lineas := jsonb_build_array(jsonb_build_object(
                    'detalle', format('Hospedaje en habitación %s, %s %s, del %s al %s (reserva %s)', r.tipo, noches,
                                      CASE WHEN noches = 1 THEN 'noche' ELSE 'noches' END,
                                      to_char(r.fecha_entrada, 'DD/MM/YYYY'), to_char(r.fecha_salida, 'DD/MM/YYYY'), r.codigo),
                    'cantidad', 1, 'precio_unitario', r.total::text, 'subtotal', r.total::text));
            END IF;
            lineas := lineas || coalesce((
                SELECT jsonb_agg(jsonb_build_object(
                           'detalle', format('%s (%s)', c.descripcion,
                                             to_char(c.creado_en AT TIME ZONE 'America/Costa_Rica', 'DD/MM/YYYY')),
                           'cantidad', c.cantidad, 'precio_unitario', c.precio_unitario::text, 'subtotal', c.total::text)
                       ORDER BY c.id)
                FROM cargos c WHERE c.reserva_id = r.id AND c.anulado_en IS NULL), '[]'::jsonb);
            consec := '0010000101' || lpad(nextval('consecutivo_factura')::text, 10, '0');
            INSERT INTO facturas (reserva_id, clave, consecutivo, subtotal, impuesto, total, estado, mensaje,
                                  respondida_en, concepto, lineas)
            VALUES (r.id,
                    '506' || to_char(now() AT TIME ZONE 'America/Costa_Rica', 'DDMMYY') || '003101999999' || consec
                        || '1' || lpad(floor(random() * 100000000)::bigint::text, 8, '0'),
                    consec, subtotal, impuesto, subtotal + impuesto, 'aceptada', 'Comprobante aceptado',
                    now(), 'cuenta_final', lineas);
            detalle := detalle || jsonb_build_object('factura_final', consec);
        END IF;

        UPDATE habitaciones SET estado_limpieza = 'sucia' WHERE id = r.habitacion_id;
        UPDATE solicitudes SET estado = 'resuelta', resuelta_en = now(), pendiente_desde = NULL, actualizada_en = now()
        WHERE reserva_id = r.id AND estado <> 'resuelta';
        UPDATE reservas SET estado = 'finalizada', actualizada_en = now() WHERE id = r.id;
        INSERT INTO bitacora (usuario_id, accion, entidad, entidad_id, detalle)
        VALUES (recepcion, 'check_out', 'reserva', r.codigo, detalle);
        hechas := hechas + 1;
    END LOOP;
    RETURN hechas;
END;
$$;

-- ---------------------------------------------------------------------
-- Limpieza: lo mismo que hace el personal al marcar la habitación limpia
-- ---------------------------------------------------------------------
CREATE FUNCTION simulacion.limpiar_habitaciones(cualquier_hora boolean DEFAULT false)
RETURNS integer
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
AS $$
-- Solo trabaja en el turno de limpieza (7:00 a 16:59, hora de Costa Rica),
-- salvo que se pida con cualquier_hora (para probarla a mano).
-- Limpia una habitación sucia si nadie está hospedado en ella, si su
-- última salida fue de una estadía simulada hace al menos dos horas y si
-- nadie del personal cambió su estado de limpieza después de esa salida.
DECLARE
    limpieza bigint;
    hechas   integer;
BEGIN
    IF NOT cualquier_hora AND extract(hour FROM now() AT TIME ZONE 'America/Costa_Rica') NOT BETWEEN 7 AND 16 THEN
        RETURN 0;
    END IF;
    SELECT u.id INTO limpieza FROM usuarios u WHERE u.correo = 'limpieza@soluna.test';
    WITH limpias AS (
        UPDATE habitaciones h SET estado_limpieza = 'limpia'
        FROM (
            SELECT DISTINCT ON (res.habitacion_id) res.habitacion_id, res.id, res.actualizada_en
            FROM reservas res
            WHERE res.estado = 'finalizada'
            ORDER BY res.habitacion_id, res.actualizada_en DESC
        ) ultima
        WHERE ultima.habitacion_id = h.id
          AND h.estado_limpieza = 'sucia'
          AND ultima.actualizada_en <= now() - interval '2 hours'
          AND EXISTS (SELECT 1 FROM simulacion.estadias e WHERE e.reserva_id = ultima.id)
          AND NOT EXISTS (SELECT 1 FROM reservas o WHERE o.habitacion_id = h.id AND o.estado = 'en_curso')
          AND NOT EXISTS (SELECT 1 FROM bitacora b
                          WHERE b.entidad = 'habitacion' AND b.entidad_id = h.numero
                            AND b.accion = 'cambiar_limpieza' AND b.fecha > ultima.actualizada_en)
        RETURNING h.numero
    ), constancia AS (
        INSERT INTO bitacora (usuario_id, accion, entidad, entidad_id, detalle)
        SELECT limpieza, 'cambiar_limpieza', 'habitacion', l.numero,
               jsonb_build_object('de', 'sucia', 'a', 'limpia', 'replica', 'simulacion')
        FROM limpias l
    )
    SELECT count(*) INTO hechas FROM limpias;
    RETURN hechas;
END;
$$;

-- ---------------------------------------------------------------------
-- Nuevos huéspedes simulados
-- ---------------------------------------------------------------------
CREATE FUNCTION simulacion.nuevo_lote(cantidad integer, dias integer DEFAULT 14)
RETURNS TABLE (codigo text, habitacion text, canal text, huesped text, salida date)
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
AS $$
-- Crea hasta "cantidad" huéspedes ficticios que llegaron hoy (en las
-- últimas horas) y se van en un día al azar de los próximos "dias" días,
-- a una hora al azar entre las 7:00 y las 11:45. Cada uno ocupa una
-- habitación libre y lista para huéspedes, elegida al azar; si no hay
-- suficientes, crea los que quepan. El canal sale al azar (40 % en línea,
-- 20 % agencia, 20 % mostrador, 20 % teléfono) y cada canal deja la misma
-- huella que en el sistema real: las reservas en línea tienen su pago
-- aprobado y su factura del hospedaje, las de agencia su referencia y las
-- de mostrador y teléfono, su teléfono de contacto. Nombres, códigos y
-- correos (siempre .test) son al azar y no se repiten dentro del lote.
DECLARE
    zona        constant text := 'America/Costa_Rica';
    alfabeto    constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    hoy         date := (now() AT TIME ZONE 'America/Costa_Rica')::date;
    nombres_cr  text[];
    apellidos   text[];
    nombres_ext text[];
    apell_ext   text[];
    recepcion   bigint;
    i           integer;
    hab         record;
    cod         text;
    can         text;
    nombre      text;
    apellido    text;
    correo_h    text;
    telefono    text;
    extranjero  boolean;
    personas    integer;
    sal         date;
    total       numeric(10,2);
    impuesto    numeric(10,2);
    ingreso     timestamptz;
    creada      timestamptz;
    rid         bigint;
    consec      text;
    transaccion text;
    referencia  text;
    sorteo      double precision;
BEGIN
    IF cantidad < 1 OR cantidad > 46 OR dias < 1 OR dias > 30 THEN
        RAISE EXCEPTION 'cantidad debe estar entre 1 y 46, y dias entre 1 y 30';
    END IF;
    SELECT u.id INTO recepcion FROM usuarios u WHERE u.correo = 'recepcion@soluna.test';
    -- Listas barajadas: se recorren en orden para no repetir nombres dentro del lote
    SELECT array_agg(x ORDER BY random()) INTO nombres_cr FROM unnest(ARRAY[
        'María José', 'Andrés', 'Valeria', 'Diego', 'Sofía', 'Esteban', 'Camila', 'José Pablo', 'Daniela',
        'Luis Diego', 'Fernanda', 'Sebastián', 'Mariana', 'Gabriel', 'Natalia', 'Adrián', 'Paula', 'Kevin',
        'Melissa', 'Ricardo', 'Ana Lucía', 'Mauricio', 'Karla', 'Óscar', 'Laura', 'Javier', 'Raquel', 'Marco Antonio',
        'Silvia', 'Rodrigo', 'Tatiana', 'Allan', 'Gloriana', 'Fabián', 'Priscila', 'Esteban José']) x;
    SELECT array_agg(x ORDER BY random()) INTO apellidos FROM unnest(ARRAY[
        'Vargas', 'Rojas', 'Jiménez', 'Mora', 'Solano', 'Araya', 'Chaves', 'Quesada', 'Arias', 'Castro', 'Ulate',
        'Brenes', 'Zúñiga', 'Calderón', 'Méndez', 'Salazar', 'Villalobos', 'Campos', 'Sibaja', 'Porras', 'Herrera',
        'Montero', 'Cordero', 'Navarro', 'Alfaro', 'Murillo', 'Segura', 'Fallas', 'Monge', 'Elizondo', 'Barrantes',
        'Corrales', 'Guzmán', 'Badilla', 'Leiva', 'Picado', 'Umaña', 'Hidalgo', 'Esquivel', 'Valverde']) x;
    SELECT array_agg(x ORDER BY random()) INTO nombres_ext FROM unnest(ARRAY[
        'Emily', 'James', 'Hannah', 'Lukas', 'Chloé', 'Marco', 'Sarah', 'Thomas', 'Olivia', 'Noah', 'Elena', 'Jonas',
        'Léa', 'Matteo', 'Grace', 'Daniel', 'Anna', 'Liam', 'Clara', 'Ethan', 'Sophie', 'Felix', 'Isabella', 'Oliver',
        'Mia', 'Hugo', 'Charlotte', 'Leon', 'Ava', 'Samuel']) x;
    SELECT array_agg(x ORDER BY random()) INTO apell_ext FROM unnest(ARRAY[
        'Smith', 'Müller', 'Dubois', 'Rossi', 'Johnson', 'Becker', 'Miller', 'Fischer', 'Martin', 'Bianchi',
        'Taylor', 'Schneider', 'Bernard', 'Wilson', 'Novak', 'Larsen', 'Kowalski', 'Brown', 'Weber', 'Moreau',
        'Ricci', 'Anderson', 'Hoffmann', 'Lefebvre', 'Jensen', 'Davies', 'Clark', 'Wagner']) x;

    FOR i IN 1..cantidad LOOP
        sal := hoy + 1 + floor(random() * dias)::int;
        -- Habitación libre en todas las noches de la estadía, en servicio y lista para huéspedes
        SELECT h.id, h.numero, h.tipo_id, t.capacidad INTO hab
        FROM habitaciones h JOIN tipos_habitacion t ON t.id = h.tipo_id
        WHERE NOT h.fuera_de_servicio
          AND h.estado_limpieza IN ('limpia', 'inspeccionada')
          AND NOT EXISTS (SELECT 1 FROM reservas o
                          WHERE o.habitacion_id = h.id AND o.estado <> 'cancelada'
                            AND daterange(o.fecha_entrada, o.fecha_salida) && daterange(hoy, sal))
          AND NOT EXISTS (SELECT 1 FROM reservas o WHERE o.habitacion_id = h.id AND o.estado = 'en_curso')
        ORDER BY random() LIMIT 1;
        EXIT WHEN hab.id IS NULL;

        LOOP
            cod := 'SOL-' || (SELECT string_agg(substr(alfabeto, 1 + floor(random() * 32)::int, 1), '')
                              FROM generate_series(1, 6));
            EXIT WHEN NOT EXISTS (SELECT 1 FROM reservas o WHERE o.codigo = cod);
        END LOOP;

        sorteo := random();
        can := CASE WHEN sorteo < 0.4 THEN 'web' WHEN sorteo < 0.6 THEN 'ota'
                    WHEN sorteo < 0.8 THEN 'recepcion' ELSE 'telefono' END;
        extranjero := can IN ('web', 'ota') AND random() < 0.6;
        IF extranjero THEN
            nombre := nombres_ext[1 + (i - 1) % array_length(nombres_ext, 1)];
            apellido := apell_ext[1 + (i - 1) % array_length(apell_ext, 1)];
        ELSE
            nombre := nombres_cr[1 + (i - 1) % array_length(nombres_cr, 1)];
            apellido := apellidos[1 + (2 * i - 2) % array_length(apellidos, 1)];
            IF random() < 0.7 THEN
                apellido := apellido || ' ' || apellidos[1 + (2 * i - 1) % array_length(apellidos, 1)];
            END IF;
        END IF;
        correo_h := translate(lower(split_part(nombre, ' ', 1) || '.' || split_part(apellido, ' ', 1)),
                            'áéíóúüñçèëï', 'aeiouuncei')
                  || '@' || (SELECT string_agg(chr(97 + floor(random() * 26)::int), '')
                             FROM generate_series(1, 5 + floor(random() * 4)::int)) || '.test';
        telefono := NULL;
        IF can = 'telefono' OR (can = 'recepcion' AND random() < 0.7) OR (can = 'ota' AND random() < 0.5) THEN
            telefono := CASE WHEN extranjero
                             THEN '+1 ' || (ARRAY['212', '305', '415', '512', '617'])[1 + floor(random() * 5)::int]
                                  || '-555-01' || lpad(floor(random() * 100)::int::text, 2, '0')
                             ELSE '+506 ' || (ARRAY['6', '7', '8'])[1 + floor(random() * 3)::int]
                                  || lpad(floor(random() * 1000)::int::text, 3, '0') || '-'
                                  || lpad(floor(random() * 10000)::int::text, 4, '0') END;
        END IF;
        personas := least(hab.capacidad, (ARRAY[1, 2, 2, 2, 2, 3, 4])[1 + floor(random() * 7)::int]);

        -- Precio de cada noche según su temporada (alta de diciembre a abril), como calcular_total de la API
        SELECT sum(t.precio_noche) INTO total
        FROM generate_series(hoy, sal - 1, interval '1 day') AS d
        JOIN tarifas t ON t.tipo_id = hab.tipo_id
                      AND t.temporada = CASE WHEN extract(month FROM d) IN (12, 1, 2, 3, 4) THEN 'alta' ELSE 'baja' END;
        impuesto := round(total * 0.13, 2);

        -- Llegó en las últimas horas (nunca antes de las 6:00 de hoy)
        ingreso := greatest(now() - (5 + random() * 235) * interval '1 minute', (hoy + time '06:00') AT TIME ZONE zona);
        IF ingreso > now() THEN
            ingreso := now();
        END IF;
        creada := CASE
            WHEN can = 'recepcion' AND random() < 0.5 THEN ingreso - (8 + random() * 17) * interval '1 minute'
            WHEN can IN ('recepcion', 'telefono') THEN ingreso - (1 + random() * 20) * interval '1 day'
            ELSE ingreso - (3 + random() * 42) * interval '1 day' END;
        referencia := CASE WHEN can = 'ota' THEN 'OTA-' || upper(lpad(to_hex(floor(random() * 4294967295)::bigint), 8, '0')) END;

        INSERT INTO reservas (codigo, habitacion_id, nombre_huesped, correo_huesped, telefono_huesped, personas,
                              fecha_entrada, fecha_salida, canal, estado, total, creada_por, creada_en, actualizada_en,
                              referencia_externa)
        VALUES (cod, hab.id, nombre || ' ' || apellido, correo_h, telefono, personas, hoy, sal, can, 'en_curso', total,
                CASE WHEN can IN ('recepcion', 'telefono') THEN recepcion END, creada, ingreso, referencia)
        RETURNING id INTO rid;
        INSERT INTO simulacion.estadias (reserva_id, hora_salida)
        VALUES (rid, time '07:00' + floor(random() * 20) * interval '15 minutes');

        IF can = 'web' THEN
            transaccion := 'ch_' || substr(md5(random()::text || clock_timestamp()::text), 1, 20);
            INSERT INTO pagos (reserva_id, tipo, estado, transaccion, monto, marca, ultimos4, creado_en)
            VALUES (rid, 'cobro', 'aprobado', transaccion, total + impuesto,
                    (ARRAY['Visa', 'Visa', 'Mastercard', 'American Express'])[1 + floor(random() * 4)::int],
                    lpad(floor(random() * 10000)::int::text, 4, '0'), creada + interval '2 minutes');
            consec := '0010000101' || lpad(nextval('consecutivo_factura')::text, 10, '0');
            INSERT INTO facturas (reserva_id, clave, consecutivo, subtotal, impuesto, total, estado, mensaje,
                                  emitida_en, respondida_en, concepto)
            VALUES (rid,
                    '506' || to_char((creada + interval '2 minutes') AT TIME ZONE zona, 'DDMMYY') || '003101999999'
                        || consec || '1' || lpad(floor(random() * 100000000)::bigint::text, 8, '0'),
                    consec, total, impuesto, total + impuesto, 'aceptada', 'Comprobante aceptado',
                    creada + interval '2 minutes', creada + interval '2 minutes 1 second', 'hospedaje');
            INSERT INTO bitacora (fecha, usuario_id, accion, entidad, entidad_id, detalle)
            VALUES (creada + interval '2 minutes', NULL, 'pago_aprobado', 'reserva', cod,
                    jsonb_build_object('transaccion', transaccion, 'monto', (total + impuesto)::text, 'factura', consec,
                                       'replica', 'simulacion'));
        ELSIF can = 'ota' THEN
            INSERT INTO bitacora (fecha, usuario_id, accion, entidad, entidad_id, detalle)
            VALUES (creada, NULL, 'reserva_ota', 'reserva', cod,
                    jsonb_build_object('referencia', referencia, 'habitacion', hab.id, 'entrada', hoy::text,
                                       'salida', sal::text, 'replica', 'simulacion'));
        ELSE
            INSERT INTO bitacora (fecha, usuario_id, accion, entidad, entidad_id, detalle)
            VALUES (creada, recepcion, 'crear_reserva', 'reserva', cod,
                    jsonb_build_object('habitacion', hab.numero, 'entrada', hoy::text, 'salida', sal::text,
                                       'canal', can, 'replica', 'simulacion'));
        END IF;
        INSERT INTO bitacora (fecha, usuario_id, accion, entidad, entidad_id, detalle)
        VALUES (ingreso, recepcion, 'check_in', 'reserva', cod,
                jsonb_build_object('habitacion', hab.numero, 'replica', 'simulacion'));

        codigo := cod; habitacion := hab.numero; canal := can; huesped := nombre || ' ' || apellido; salida := sal;
        RETURN NEXT;
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------
-- Borrar la simulación completa (reservas, cobros, facturas, consumos,
-- solicitudes y bitácora), sin tocar nada real
-- ---------------------------------------------------------------------
CREATE FUNCTION simulacion.borrar()
RETURNS integer
LANGUAGE plpgsql
SET search_path = hotel, pg_catalog
AS $$
DECLARE
    borradas integer;
BEGIN
    CREATE TEMP TABLE simuladas ON COMMIT DROP AS
        SELECT r.id, r.codigo FROM reservas r JOIN simulacion.estadias e ON e.reserva_id = r.id;
    DELETE FROM mensajes WHERE solicitud_id IN (SELECT s.id FROM solicitudes s WHERE s.reserva_id IN (SELECT id FROM simuladas));
    DELETE FROM solicitudes WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM cargos WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM pagos_caja WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM facturas WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM pagos WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM resenas WHERE reserva_id IN (SELECT id FROM simuladas);
    DELETE FROM bitacora WHERE entidad = 'reserva' AND entidad_id IN (SELECT codigo FROM simuladas);
    DELETE FROM bitacora WHERE entidad = 'habitacion' AND detalle->>'replica' = 'simulacion';
    DELETE FROM simulacion.estadias;
    DELETE FROM reservas WHERE id IN (SELECT id FROM simuladas);
    GET DIAGNOSTICS borradas = ROW_COUNT;
    DROP TABLE simuladas;
    RETURN borradas;
END;
$$;

-- Solo el administrador (y pg_cron, que corre como administrador) ejecuta la simulación
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA simulacion FROM PUBLIC;

-- Programación (un nombre repetido reemplaza la tarea, así que es idempotente)
SELECT cron.schedule('soluna-simulacion', '20 * * * *',
                     'SELECT simulacion.registrar_salidas(), simulacion.limpiar_habitaciones()');
