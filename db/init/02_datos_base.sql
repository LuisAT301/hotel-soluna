-- =====================================================================
-- Hotel Soluna: datos de catálogo
-- 46 habitaciones en tres categorías, como se describe en el Avance 1.
-- Los usuarios de demostración NO se crean aquí, porque sus contraseñas
-- no pueden quedar en el repositorio: los crea app/seed.py a partir
-- del archivo .env (ver README).
-- =====================================================================

INSERT INTO tipos_habitacion (nombre, capacidad, descripcion) VALUES
    ('estándar', 2, 'Cama queen, vista al jardín'),
    ('superior', 3, 'Cama king y sofá cama, balcón con vista parcial al mar'),
    ('suite',    4, 'Dos ambientes, terraza frente al mar');

-- Precios por noche en dólares. Temporada alta: diciembre a abril.
INSERT INTO tarifas (tipo_id, temporada, precio_noche)
SELECT t.id, v.temporada, v.precio
FROM tipos_habitacion t
JOIN (VALUES
        ('estándar', 'alta', 120.00), ('estándar', 'baja',  85.00),
        ('superior', 'alta', 165.00), ('superior', 'baja', 115.00),
        ('suite',    'alta', 260.00), ('suite',    'baja', 180.00)
     ) AS v (tipo, temporada, precio) ON v.tipo = t.nombre;

-- Piso 1: 20 estándar (101-120); piso 2: 18 superior (201-218);
-- piso 3: 8 suites (301-308). Total: 46 habitaciones.
INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'estándar'), 1
FROM generate_series(101, 120) AS n;

INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'superior'), 2
FROM generate_series(201, 218) AS n;

INSERT INTO habitaciones (numero, tipo_id, piso)
SELECT n::text, (SELECT id FROM tipos_habitacion WHERE nombre = 'suite'), 3
FROM generate_series(301, 308) AS n;
