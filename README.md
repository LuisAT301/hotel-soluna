# Hotel Soluna: arquitectura híbrida en la nube

Proyecto final del curso **Arquitectura de computación en la nube** (ULACIT, IIICO 2026).

## Integrantes

- Luis Arce Tencio
- Nicole Benavides Soto
- Cristopher Porras Monge
- Yaret Rodriguez Oviedo

## Problema

El Hotel Soluna (organización ficticia, Playa Sámara, Guanacaste) opera con un programa de escritorio
instalado en la computadora de la recepción, que funciona a la vez como estación de trabajo y servidor
de la base de datos. Esa dependencia, junto con una red sin segmentar, procesos manuales y respaldos
nunca probados, compromete la disponibilidad, la seguridad de la información y el crecimiento del hotel.
La propuesta traslada el sistema a una arquitectura híbrida: los servicios principales en la nube y un
nodo local de contingencia en el hotel.

## Tecnologías

| Componente | Tecnología |
|---|---|
| API | Python 3.13 + FastAPI |
| Base de datos | PostgreSQL 17 |
| Acceso a datos | SQLAlchemy 2 |
| Contraseñas | Argon2id |
| Sesiones | JWT de 30 minutos |
| Contenedores | Docker y Docker Compose |
| Proxy, HTTPS y balanceo | Nginx 1.30 |
| Interfaz web | HTML, CSS y JavaScript sin librerías |
| Correo de prueba | Mailpit *(bloque 3)* |
| Prueba de carga | Locust *(bloque 4)* |
| Red del hotel | Cisco Packet Tracer *(bloque 5)* |

## Arquitectura

Los diagramas se encuentran en `docs/diagramas/` *(bloque 6)*. Resumen del prototipo:

```
Navegador ──► Nginx (HTTPS, balanceo) ──► API x3 (FastAPI) ──► PostgreSQL
                                              │                    │
                                              ├─► Simulador        └─► Respaldo (pg_dump) ──► Nodo de contingencia
                                              └─► Mailpit
```

Redes de Docker:

- `datos` es interna, sin salida a Internet ni acceso desde el equipo. Ahí están la API y PostgreSQL.
- `backend` conecta Nginx con la API y, desde el bloque 3, con los servicios externos simulados.
- Solo Nginx publica puertos (80 y 443). Ni la API ni la base de datos son accesibles directamente.

## Requisitos

- **Docker Desktop**:
  - Mac con Apple Silicon o Intel. OrbStack también sirve.
  - Windows 10/11 con WSL 2.
  - Asignar al menos 4 GB de memoria.
- **Git**.
- No hace falta instalar Python ni PostgreSQL: todo corre en contenedores.

## Cómo ejecutar

```bash
git clone https://github.com/LuisAT301/hotel-soluna.git
cd hotel-soluna

# 1. Crear el archivo de secretos a partir de la plantilla y cambiar los valores
cp .env.example .env          # en PowerShell: Copy-Item .env.example .env

# 2. Construir y levantar los contenedores
docker compose up --build -d

# 3. Crear las cuentas de demostración (una sola vez)
docker compose exec api python -m app.seed
```

Luego abrir:

- Interfaz web: <https://localhost>
- Documentación interactiva de la API: <https://localhost/api/docs>

El certificado es autofirmado, así que el navegador mostrará una advertencia la primera vez:

- **Chrome:** "Configuración avanzada" > "Acceder a localhost".
- **Safari:** "Mostrar detalles" > "visitar este sitio web".

En producción se usaría un certificado emitido por una autoridad.

### Cuentas de demostración

Todas usan la contraseña definida en `DEMO_PASSWORD` dentro de `.env`.

| Correo | Rol |
|---|---|
| gerencia@soluna.test | gerente |
| recepcion@soluna.test | recepcionista |
| limpieza@soluna.test | limpieza |
| mantenimiento@soluna.test | mantenimiento |
| cliente@soluna.test | cliente |

En la interfaz web, use **Iniciar sesión**. En `/api/docs`, use el botón **Authorize**; el campo *username* es el correo.

### Qué ve cada rol en la interfaz

| Rol | Secciones |
|---|---|
| Público | Disponibilidad (para reservar debe iniciar sesión o crear una cuenta) |
| Cliente | Disponibilidad, Mis reservas |
| Recepcionista | Disponibilidad, Reservas, Habitaciones (puede reservar a nombre de un huésped) |
| Limpieza | Habitaciones (cambia el estado de limpieza) |
| Mantenimiento | Habitaciones (solo lectura) |
| Gerente | Todo lo anterior, más Cuentas del personal y Bitácora |

El pie de página muestra qué réplica de la API respondió la última solicitud.

## Demostraciones del bloque 2

```bash
# 1. Balanceo: cada solicitud la atiende una réplica distinta
for i in 1 2 3 4 5 6; do curl -sk https://localhost/api/salud; echo; done

# 2. Falla de una réplica: se detiene una y el servicio sigue respondiendo
docker compose ps api                    # ver los nombres de las réplicas
docker stop hotel-soluna-api-2
for i in 1 2 3 4 5 6; do curl -sk https://localhost/api/salud; echo; done
docker start hotel-soluna-api-2

# 3. Escalar a 5 réplicas sin reiniciar Nginx
docker compose up -d --scale api=5
for i in $(seq 1 10); do curl -sk https://localhost/api/salud; echo; done
docker compose up -d --scale api=3       # volver a 3

# 4. Límite de intentos: después de 6 intentos seguidos, Nginx responde 429
for i in $(seq 1 8); do curl -sk -o /dev/null -w "%{http_code} " -X POST https://localhost/api/auth/login -d "username=x@soluna.test&password=incorrecta"; done; echo

# 5. HTTP redirige a HTTPS
curl -sI http://localhost | head -3
```

### Comandos útiles

```bash
docker compose ps                 # estado y salud de los contenedores
docker compose logs -f api        # registros de las tres réplicas
docker compose logs -f nginx      # registros de Nginx
docker compose down               # detener (los datos se conservan)
docker compose down -v            # detener y BORRAR la base (vuelve a crearse al levantar)
```

Los scripts de `db/init` solo se ejecutan cuando el volumen de datos está vacío.
Si cambian el esquema, hay que usar `docker compose down -v` y volver a levantar.

## Ver la base de datos

La base no publica ningún puerto, por seguridad. Hay dos formas de consultarla.

### Desde la terminal

```bash
docker compose exec db psql -U postgres -d hotel
```

Dentro, por ejemplo:

```sql
\dt
SELECT codigo, nombre_huesped, fecha_entrada, estado FROM reservas;
SELECT fecha, accion, entidad_id FROM bitacora ORDER BY id DESC LIMIT 10;
\q
```

`\dt` lista las tablas y `\q` sale.

### Con Adminer (visor web, solo para desarrollo)

```bash
docker compose up -d adminer        # encender
grep DB_RESPALDO_PASSWORD .env      # ver la contraseña de solo lectura
docker compose stop adminer         # apagar
```

Abra <http://localhost:8081> e ingrese:

| Campo | Valor |
|---|---|
| Sistema | PostgreSQL |
| Servidor | `db` |
| Usuario | `respaldo` |
| Contraseña | el valor de `DB_RESPALDO_PASSWORD` en `.env` |
| Base de datos | `hotel` |

El usuario `respaldo` solo puede leer, así que no hay riesgo de borrar algo por accidente.
Para modificar datos, use el usuario `postgres` con `POSTGRES_PASSWORD`, con cuidado.

Detalles de seguridad:

- Adminer no arranca con `docker compose up -d`; solo se enciende cuando se pide.
- Solo escucha en el propio equipo (`127.0.0.1`).
- En producción no existiría.

## API (bloque 1)

| Método | Ruta | Quién puede usarla |
|---|---|---|
| POST | `/api/auth/registro` | Público (crea siempre una cuenta de cliente) |
| POST | `/api/auth/login` | Público. Bloquea la cuenta 15 minutos tras 5 intentos fallidos |
| GET | `/api/disponibilidad` | Público |
| POST | `/api/reservas` | Cliente, recepcionista, gerente |
| GET | `/api/reservas` | Cliente (solo las suyas), recepcionista, gerente |
| POST | `/api/reservas/{codigo}/cancelar` | Dueño de la reserva, recepcionista, gerente |
| GET | `/api/habitaciones` | Personal del hotel |
| PATCH | `/api/habitaciones/{id}/limpieza` | Limpieza, recepcionista, gerente |
| GET/POST | `/api/usuarios` | Gerente |
| GET | `/api/bitacora` | Gerente |
| GET | `/api/salud` | Público (healthcheck; indica qué réplica respondió) |

Todas las rutas se acceden a través de Nginx: `https://localhost/api/...`.

### Medidas de seguridad ya implementadas

- **Contraseñas:** se guardan con Argon2id y nunca en texto plano.
- **Inicio de sesión:**
  - Los mensajes de error son genéricos.
  - La cuenta se bloquea tras 5 intentos fallidos.
- **Sesiones y permisos:**
  - Los tokens JWT vencen a los 30 minutos y solo se aceptan firmados con HS256.
  - Los permisos se revisan por rol en cada ruta.
  - Una cuenta desactivada pierde el acceso de inmediato.
- **Base de datos:**
  - La regla `sin_traslape` impide la sobreventa incluso con solicitudes simultáneas.
  - La API usa un usuario con privilegios mínimos: no puede borrar reservas, alterar la bitácora ni cambiar tablas.
- **Bitácora:** registra quién hizo qué, cuándo y desde qué réplica.
- **Secretos:**
  - Se leen de `.env`, que no se sube al repositorio.
  - Llegan a los contenedores como archivos en `/run/secrets`.
- **Contenedores:**
  - La API corre con un usuario sin privilegios.
  - La base de datos no publica puertos.
- **Nginx:**
  - Todo el tráfico entra por HTTPS (TLS 1.2 o 1.3), y HTTP redirige a HTTPS.
  - Limita el inicio de sesión a 10 intentos por minuto por dirección IP, con 5 de margen.
  - Agrega cabeceras de seguridad. En la interfaz incluye una política de contenido (CSP) que solo permite código del propio sitio.
  - Si una réplica falla, reintenta en otra.
  - No revela su versión.
- **Interfaz web:** no usa librerías externas e inserta los datos como texto, nunca como HTML, para evitar inyección de código.

## Pruebas

`api/tests` contiene 26 pruebas automáticas. Cubren:

- Contraseñas con Argon2id.
- Bloqueo de cuentas y token alterado.
- Permisos por rol.
- Precios por temporada.
- Sobreventa, incluidas 10 solicitudes simultáneas contra 2 procesos de la API.
- Bitácora.
- Privilegios de la base de datos.

**Importante:** las pruebas vacían las tablas antes de cada caso, así que nunca deben ejecutarse contra la base de la demostración.

## Estado

- [x] **Bloque 1:** base de datos, API con roles, Compose mínimo.
- [x] **Bloque 2:** Nginx con HTTPS, tres réplicas, límite de intentos, interfaz web.
- [ ] **Bloque 3:** simulador de pasarela, OTA y factura, más Mailpit.
- [ ] **Bloque 4:** respaldos automáticos, restauración en el nodo de contingencia, Locust.
- [ ] **Bloque 5:** red en Packet Tracer (configuraciones y guía).
- [ ] **Bloque 6:** diagramas.

## Estructura

```
hotel-soluna/
├── docker-compose.yml
├── .env.example          plantilla de secretos (el .env real no se sube)
├── db/init/              esquema, catálogo y usuarios de la base
├── nginx/                imagen de Nginx: HTTPS, balanceo y cabeceras de seguridad
├── web/                  interfaz web (HTML, CSS y JavaScript)
└── api/
    ├── Dockerfile
    ├── requirements.txt
    ├── app/              código de la API
    └── tests/            pruebas automáticas
```
