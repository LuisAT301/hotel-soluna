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
| Base de datos | PostgreSQL 17, en Docker o en Supabase |
| Acceso a datos | SQLAlchemy 2 |
| Contraseñas | Argon2id |
| Sesiones | JWT de 30 minutos |
| Contenedores | Docker y Docker Compose |
| Proxy, HTTPS y balanceo | Nginx 1.30 |
| Interfaz web | HTML, CSS y JavaScript sin librerías |
| Servicios externos simulados | FastAPI: pasarela de pago, Hacienda y agencia de viajes en línea (OTA) |
| Correo de prueba | Mailpit |
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
- `backend` conecta Nginx, la API, el simulador de servicios externos y Mailpit.
- Hacia Internet solo Nginx publica puertos (80 y 443). Ni la API ni la base de datos son accesibles directamente.
- El simulador (8090) y Mailpit (8025) publican sus paneles solo en el propio equipo (`127.0.0.1`), para la demostración.

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

# 1. Crear el archivo .env con todas las contraseñas (no hay que editarlo)
sh crear-env.sh               # Mac y Linux
# En Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File .\crear-env.ps1

# 2. Construir y levantar los contenedores
docker compose up --build -d

# 3. Crear las cuentas de demostración (una sola vez)
docker compose exec api python -m app.seed
```

Luego abrir:

- Interfaz web: <https://localhost>
- Documentación interactiva de la API: <https://localhost/api/docs>
- Correos enviados por el sistema (Mailpit): <http://localhost:8025>
- Panel del simulador de servicios externos: <http://localhost:8090/docs>

El script llena el `.env` con contraseñas al azar y deja la de las cuentas de demostración en `SolunaDemo2026`.
Si ya existía un `.env`, guarda una copia en `.env.anterior`. Quien prefiera hacerlo a mano puede copiar
`.env.example` como `.env` y cambiar los valores.

**Si ya tenían el proyecto del bloque 2 funcionando:** ejecuten de nuevo el script (agrega las variables nuevas
del bloque 3) y recreen la base, porque hay tablas nuevas: `docker compose down -v`, luego `docker compose up --build -d`
y de nuevo el paso 3.

El certificado es autofirmado, así que el navegador mostrará una advertencia la primera vez:

- **Chrome:** "Configuración avanzada" > "Acceder a localhost".
- **Safari:** "Mostrar detalles" > "visitar este sitio web".

En producción se usaría un certificado emitido por una autoridad.

### Cuentas de demostración

Todas usan la contraseña definida en `DEMO_PASSWORD` dentro de `.env` (`SolunaDemo2026` si lo creó el script).

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
| Público | Página de inicio completa: ubicación, habitaciones, amenidades, reseñas, disponibilidad, suscripción por correo y contacto (para reservar debe iniciar sesión o crear una cuenta) |
| Cliente | La misma página de inicio, más Mis reservas (paga en línea y consulta su factura) |
| Recepcionista | Disponibilidad, Reservas, Habitaciones (puede reservar a nombre de un huésped) |
| Limpieza | Habitaciones (cambia el estado de limpieza) |
| Mantenimiento | Habitaciones (solo lectura) |
| Gerente | Todo lo anterior, más Cuentas del personal, Bitácora y Correos suscritos |

El personal entra directo a su panel de trabajo, sin la página de inicio.
El pie de página muestra qué réplica de la API respondió la última solicitud.

### Página de inicio

- **Foto de fondo:** hoy es una ilustración de Playa Sámara (`web/img/playa-samara.svg`). Para usar una foto
  real, guárdela como `web/img/playa-samara.jpg` (ancho recomendado: 1920 px) y recargue la página: reemplaza
  a la ilustración sin tocar el código. Use una foto propia o con licencia que permita su uso.
- **Logo:** `web/img/logo.svg`, un círculo mitad sol y mitad luna sobre el mar. También es el ícono de la pestaña.
- **Suscripción por correo:** el campo de "Ofertas y novedades" guarda el correo en la tabla `suscriptores`
  y envía una bienvenida. Gerencia ve la lista en su panel; el mismo correo no se repite y la respuesta no revela
  si ya estaba suscrito. Nginx limita la ruta a 5 intentos por minuto por IP.
- **Envío real de correos:** hoy todo lo captura Mailpit. Para usar un servicio de envío (Brevo, SendGrid,
  Amazon SES, Resend u otro con SMTP), basta con definir en el servicio `api` de `docker-compose.yml`:
  `SMTP_HOST`, `SMTP_PORT` (normalmente 587), `SMTP_USUARIO`, `SMTP_PASSWORD_FILE` (como secreto de Docker),
  `SMTP_TLS: "si"` y `CORREO_REMITENTE` con un dominio verificado en el servicio.
- **Datos ficticios:** el hotel, el teléfono, la dirección y las reseñas son de demostración.

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

## Demostraciones del bloque 3

El bloque 3 conecta el hotel con tres proveedores externos, que en el prototipo
simula el contenedor `simulador`:

| Proveedor | Qué hace en el prototipo |
|---|---|
| Pasarela de pago | Recibe la tarjeta desde el navegador, cobra y reembolsa |
| Hacienda | Recibe la factura electrónica y la acepta o la rechaza |
| OTA (agencia de viajes en línea) | Envía reservas al hotel con un aviso firmado |

Todos los correos que envía el sistema quedan en Mailpit (<http://localhost:8025>) y no llegan a nadie.

### 1. Pago en línea y factura electrónica

1. En <https://localhost>, inicie sesión como `cliente@soluna.test`, busque fechas y pulse **Reservar**.
2. Se abre el formulario de pago con el hospedaje, el IVA (13 %) y el total.
3. Pruebe primero la tarjeta rechazada y luego la aprobada:

| Tarjeta de prueba | Resultado |
|---|---|
| 4242 4242 4242 4242 | Aprobada (Visa) |
| 5555 5555 5555 4444 | Aprobada (Mastercard) |
| 4000 0000 0000 0002 | Rechazada por fondos insuficientes |
| 4000 0000 0000 0119 | La pasarela falla (la reserva sigue pendiente) |

Cualquier vencimiento futuro (por ejemplo, `12/30`) y cualquier CVV de 3 dígitos.

4. La reserva pasa a **Confirmada** y aparece el botón **Factura**, con la clave numérica de 50 dígitos.
5. En Mailpit llega el correo de confirmación con los datos de la factura.
6. Si se cancela la reserva, el pago se reembolsa y llega otro correo.

### 2. Reservas desde una agencia de viajes en línea (OTA)

```bash
# Una reserva al azar (también se puede desde http://localhost:8090/docs)
curl -s -X POST http://localhost:8090/ota/enviar

# Una reserva con referencia fija; repetirla devuelve la misma reserva (200), no una nueva
curl -s -X POST http://localhost:8090/ota/enviar -H "Content-Type: application/json" -d '{"referencia":"OTA-DEMO1","tipo":"suite"}'
curl -s -X POST http://localhost:8090/ota/enviar -H "Content-Type: application/json" -d '{"referencia":"OTA-DEMO1","tipo":"suite"}'

# Un aviso con firma falsa y uno repetido una hora después: el hotel responde 401
curl -s -X POST http://localhost:8090/ota/enviar -H "Content-Type: application/json" -d '{"firma_invalida":true}'
curl -s -X POST http://localhost:8090/ota/enviar -H "Content-Type: application/json" -d '{"fecha_vieja":true}'
```

La reserva aparece en la sección **Reservas** (recepción o gerencia) con el canal `ota`, y el huésped recibe el correo.

### 3. Falla de la pasarela

```bash
docker compose stop simulador
# Intente pagar en la interfaz: la reserva queda pendiente y el resto del sitio sigue funcionando
docker compose start simulador
```

### 4. Lo que quedó registrado

```bash
docker compose exec db psql -U postgres -d hotel -c "SELECT tipo, estado, monto, marca, ultimos4 FROM pagos;"
docker compose exec db psql -U postgres -d hotel -c "SELECT consecutivo, estado, total FROM facturas;"
curl -s http://localhost:8090/panel      # lo que vio el simulador: cobros, facturas y avisos de la OTA
```

La tabla `pagos` solo guarda la marca y los últimos cuatro dígitos de la tarjeta.

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

## Base de datos en Supabase (opcional)

En lugar del contenedor `db`, la base puede vivir en Supabase: un servicio administrado de PostgreSQL,
separado del resto del sistema, con panel de administración, conexiones cifradas y respaldos a cargo
del proveedor. La API, Nginx, el simulador y Mailpit siguen corriendo en Docker.

### Qué cambia respecto de la base en Docker

- **Esquema `hotel`:** las tablas no están en `public`. Supabase publica `public` como API REST abierta;
  en `hotel`, los datos de huéspedes y pagos no quedan expuestos.
- **Migración:** el esquema completo está en `supabase/migrations/`. Si cambia el esquema, hay que actualizar
  también `db/init`.
- **Conexión:** la API entra por el *pooler* de Supabase en modo sesión (funciona con IPv4) y exige TLS.
- **Conexiones:** cada réplica abre como máximo 4, porque el plan gratuito admite pocas.
- **Usuarios:** `app_hotel` y `respaldo` tienen los mismos privilegios mínimos que en Docker.

### Pasos (una sola vez)

1. **Crear el esquema.** Con la integración de GitHub activa en Supabase, la migración se aplica sola al
   fusionar en `main`. Verifíquelo en *Database > Migrations* del panel. Si no aparece, abra
   `supabase/migrations/20261110120000_esquema_hotel.sql`, copie todo en el *SQL Editor* y pulse **Run**.

   En la configuración de la integración, *Supabase directory* debe apuntar a la raíz del repositorio
   (donde está la carpeta `supabase/`) y *Deploy to production* debe estar activado.

2. **Crear el `.env` en modo Supabase.** Ejecute el script y elija la opción **2**:

   ```bash
   sh crear-env.sh               # en Windows: powershell -ExecutionPolicy Bypass -File .\crear-env.ps1
   ```

   Le pedirá la cadena de conexión: en el panel de Supabase pulse **Connect**, elija **Session pooler**
   y cópiela. No hace falta poner la contraseña.

3. **Activar los usuarios de la base.** El script crea `activar-roles-supabase.sql` con las contraseñas del
   `.env`. Copie su contenido en el *SQL Editor* de Supabase y pulse **Run**. Ese archivo tiene contraseñas:
   Git lo ignora y no debe compartirse.

4. **Levantar el sistema y crear las cuentas de demostración:**

   ```bash
   docker compose up --build -d
   docker compose exec api python -m app.seed
   ```

   El `.env` ya le indica a Docker que use `docker-compose.supabase.yml`, así que el contenedor `db` no se enciende.

5. **Comprobar:** `curl -sk https://localhost/api/salud` debe responder `"base_de_datos": "ok"`.

Si vuelve a ejecutar `crear-env`, las contraseñas cambian: repita el paso 3.
Para volver a la base en Docker, ejecute `crear-env` y elija la opción **1**.

### Límites del plan gratuito

- Supabase pausa el proyecto tras una semana sin uso; se reactiva desde el panel.
- Los respaldos automáticos y la restauración a un punto en el tiempo dependen del plan de pago, por eso
  se mantiene el respaldo propio del bloque 4.

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
| POST | `/api/reservas/{codigo}/pago` | Dueño de la reserva, recepcionista, gerente *(bloque 3)* |
| GET | `/api/reservas/{codigo}/factura` | Dueño de la reserva, recepcionista, gerente *(bloque 3)* |
| POST | `/api/integraciones/ota/reservas` | Solo la OTA, con un aviso firmado *(bloque 3)* |
| GET | `/api/tipos-habitacion` | Público: tipos de habitación con su precio más bajo, para la página de inicio |
| POST | `/api/suscripciones` | Público: guarda un correo para ofertas y novedades (5 por minuto por IP) |
| GET | `/api/suscripciones` | Gerente |

Todas las rutas se acceden a través de Nginx: `https://localhost/api/...`.
Además, Nginx publica `https://localhost/pasarela/tokens`, la única ruta del simulador accesible desde fuera.

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
- **Pagos (bloque 3):**
  - El navegador envía la tarjeta directamente a la pasarela y recibe un token de un solo uso. La API solo recibe ese token, así que el número de tarjeta y el CVV nunca llegan al hotel.
  - La base guarda únicamente la marca y los últimos cuatro dígitos.
  - La API se identifica ante la pasarela y Hacienda con una llave de comercio (secreto de Docker).
  - Cada cobro lleva una llave de idempotencia: si la conexión se corta y la API reintenta, no se cobra dos veces.
  - La reserva se bloquea durante el pago, así que dos pagos simultáneos no pueden confirmarla dos veces.
  - Si la pasarela no responde, la reserva sigue pendiente; una reserva pagada solo se cancela si el reembolso se completa.
  - Nginx limita la ruta de tarjetas a 10 intentos por minuto por IP, para frenar la prueba de tarjetas robadas.
  - La API no puede modificar ni borrar pagos, ni cambiar los montos de una factura.
- **OTA (bloque 3):**
  - Cada aviso viaja firmado con HMAC-SHA256 y un secreto compartido. Se rechaza si la firma no coincide, si el cuerpo fue alterado o si tiene más de 5 minutos.
  - La referencia de la OTA es única: un aviso repetido no duplica la reserva.
- **Correo:** se envía después de responder al usuario; si el servidor de correo falla, la reserva o el pago no se pierden.

## Pruebas

`api/tests` contiene 48 pruebas automáticas. Cubren:

- Contraseñas con Argon2id.
- Bloqueo de cuentas y token alterado.
- Permisos por rol.
- Precios por temporada.
- Sobreventa, incluidas 10 solicitudes simultáneas contra 2 procesos de la API.
- Bitácora.
- Privilegios de la base de datos.
- Bloque 3, contra el simulador real:
  - Pago aprobado, rechazado y con la pasarela caída.
  - Doble pago y token reutilizado.
  - Factura aceptada por Hacienda, con clave de 50 dígitos e IVA del 13 %.
  - Reembolso al cancelar una reserva pagada.
  - Avisos de la OTA: firma válida, firma falsa, cuerpo alterado, aviso viejo, aviso repetido y sin disponibilidad.
  - Correos de confirmación y cancelación.
- Página de inicio: catálogo público y suscripción por correo (sin duplicados, correo inválido y acceso solo de gerencia).

**Importante:** las pruebas vacían las tablas antes de cada caso, así que nunca deben ejecutarse contra la base de la demostración.

## Solución de problemas

### Algunos contenedores no encienden (quedan en "Created")

Si `docker compose up` solo enciende `db` y `mailpit`, y la API, el simulador y Nginx quedan en estado `Created`,
casi siempre falta un secreto en `.env`. Docker lo indica al final de la salida, por ejemplo:

```
environment variable "SERVICIOS_LLAVE" required by secret "hotel-soluna_servicios_llave" is not set
```

Si la variable que falta es `POSTGRES_PASSWORD`, Docker no está encontrando el `.env`: no existe en la carpeta
donde ejecutó el comando, o se guardó con otro nombre (por ejemplo, `.env.txt`).

Solución en ambos casos: cree el `.env` de nuevo con el script del paso 1 de "Cómo ejecutar" y vuelva a levantar:

```bash
sh crear-env.sh               # en Windows: powershell -ExecutionPolicy Bypass -File .\crear-env.ps1
docker compose down -v
docker compose up --build -d
docker compose exec api python -m app.seed
```

### Todo enciende, pero reservar o pagar da error

La base se creó con una versión anterior y no tiene las tablas nuevas. Lo confirma la salud de la API:

```bash
curl -sk https://localhost/api/salud
```

Si `base_de_datos` dice `desactualizada`, recree la base (borra los datos de prueba):

```bash
docker compose down -v
docker compose up --build -d
docker compose exec api python -m app.seed
```

### Otro programa usa un puerto

Si Docker dice `port is already allocated`, otro programa usa el puerto 80, 443, 8025 o 8090. Ciérrelo, o vea cuál es con
`docker ps` (otro proyecto de Docker) o, en Mac, `lsof -i :8025`.

### Ver por qué falla un contenedor

```bash
docker compose ps -a                 # estado de todos, incluidos los detenidos
docker compose logs simulador        # cambie "simulador" por el servicio que falla
```

## Límites conocidos del prototipo

- Al cancelar una reserva pagada se reembolsa el dinero, pero todavía no se emite la nota de crédito electrónica que anula la factura.
- Una reserva en línea que nunca se paga mantiene ocupada la habitación hasta que alguien la cancela; falta un vencimiento automático.
- El simulador guarda todo en memoria: al reiniciarlo se pierden sus registros (no los del hotel).
- Los avisos de la OTA llegan a la API por la red interna de Docker. En producción entrarían por Internet a través de Nginx y HTTPS.

## Estado

- [x] **Bloque 1:** base de datos, API con roles, Compose mínimo.
- [x] **Bloque 2:** Nginx con HTTPS, tres réplicas, límite de intentos, interfaz web.
- [x] **Bloque 3:** simulador de pasarela, OTA y factura, más Mailpit.
- [ ] **Bloque 4:** respaldos automáticos, restauración en el nodo de contingencia, Locust.
- [ ] **Bloque 5:** red en Packet Tracer (configuraciones y guía).
- [ ] **Bloque 6:** diagramas.

## Estructura

```
hotel-soluna/
├── docker-compose.yml
├── docker-compose.supabase.yml   modo Supabase: la API usa la base en la nube
├── .env.example          plantilla de secretos (el .env real no se sube)
├── crear-env.sh / .ps1   crean el .env con contraseñas al azar (Mac y Linux / Windows)
├── db/init/              esquema, catálogo y usuarios de la base local (Docker)
├── supabase/migrations/  el mismo esquema para Supabase (esquema "hotel")
├── nginx/                imagen de Nginx: HTTPS, balanceo y cabeceras de seguridad
├── web/                  sitio del hotel y panel del personal (HTML, CSS y JavaScript)
│   └── img/              logo e ilustración de la playa
├── simulador/            pasarela de pago, Hacienda y OTA simuladas
└── api/
    ├── Dockerfile
    ├── requirements.txt
    ├── app/              código de la API
    └── tests/            pruebas automáticas
```
