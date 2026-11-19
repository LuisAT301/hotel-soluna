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
| Correo | Mailpit en Docker; Brevo en la nube |
| Nube | Vercel (sitio, API y simulador), Supabase (PostgreSQL) |
| Prueba de carga | Locust 2.37 (en un contenedor, sin instalar nada) |
| Red del hotel | Cisco Packet Tracer *(bloque 5)* |

## Arquitectura

Los diagramas se encuentran en `docs/diagramas/`. El modelo de datos ya está disponible en PNG, SVG y
draw.io (editable en https://app.diagrams.net): `modelo-er` (entidad-relación, notación de Chen) y
`modelo-relacional` (tablas, columnas, claves y restricciones). Los de red y despliegue llegan con el bloque 6. El despliegue en la nube, sus decisiones de
diseño, la seguridad y los puntos únicos de falla se describen en
[`docs/arquitectura-nube.md`](docs/arquitectura-nube.md).

**En la nube** (lo que usan los huéspedes):

```
Navegador ──► Sitio (CDN de Vercel) ──► API (Vercel Functions) ──► PostgreSQL (Supabase)
                     │                       │
                     └─► Simulador ◄─────────┤   pasarela, Hacienda y OTA (Vercel Functions)
                                             └─► Brevo (correo real)
```

**En Docker** (prototipo para demostrar réplicas, balanceo y redes):

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
- **Migraciones:** el esquema completo está en `supabase/migrations/`. Si cambia el esquema, hay que agregar
  una migración nueva ahí y actualizar también `db/init`.
- **Conexión:** la API entra por el *pooler* de Supabase en modo sesión (funciona con IPv4) y exige TLS.
- **Conexiones:** cada réplica abre como máximo 2 (6 por computadora), porque el plan gratuito admite pocas.
- **Usuarios:** `app_hotel` y `respaldo` tienen los mismos privilegios mínimos que en Docker.

### Estado del proyecto de Supabase del equipo

El esquema ya está aplicado en el proyecto del equipo: las migraciones de `supabase/migrations/`
aparecen en *Database > Migrations* del panel, con las 46 habitaciones, las tarifas y los usuarios de la
base (`app_hotel` y `respaldo`) creados, pero todavía sin inicio de sesión. La tercera migración crea el
esquema `simulador` y su usuario, que usa solo la versión de Vercel (fase 2). Los nombres de los archivos
coinciden con las versiones que registró Supabase, así que la integración con GitHub no intentará
aplicarlas otra vez al fusionar en `main`.

Todo el equipo comparte esa base, por eso la contraseña del usuario de la API es una sola: la genera la
primera persona y los demás usan la misma.

### Primera persona del equipo (una sola vez)

1. **Crear el `.env` en modo Supabase.** Ejecute el script y elija la opción **2**:

   ```bash
   sh crear-env.sh               # en Windows: powershell -ExecutionPolicy Bypass -File .\crear-env.ps1
   ```

   Le pedirá la cadena de conexión: en el panel de Supabase pulse **Connect**, elija **Session pooler**
   y cópiela. No hace falta poner la contraseña. Cuando pregunte por una contraseña compartida, presione Enter.

2. **Activar los usuarios de la base.** El script crea `activar-roles-supabase.sql` con las contraseñas del
   `.env`. Copie su contenido en el *SQL Editor* de Supabase y pulse **Run**. Ese archivo tiene contraseñas:
   Git lo ignora y no debe compartirse.

3. **Compartir la contraseña de la API** (el valor de `DB_APP_PASSWORD` de su `.env`) con el equipo por un
   medio privado, nunca por el repositorio ni por un grupo abierto.

4. **Levantar el sistema y crear las cuentas de demostración.** El primer comando apaga lo que hubiera con la
   base local; `--force-recreate` obliga a crear contenedores nuevos, que tomen la contraseña del `.env` actual
   (Docker no recrea un contenedor solo porque cambió el valor de un secreto):

   ```bash
   docker compose --profile solo-local down
   docker compose up --build -d --force-recreate
   docker compose exec api python -m app.seed
   ```

   El `.env` ya le indica a Docker que use `docker-compose.supabase.yml`, así que el contenedor `db` no se enciende.

5. **Comprobar:** `curl -sk https://localhost/api/salud` debe responder `"base_de_datos": "ok"`.

### Los demás integrantes

1. Ejecute `crear-env`, elija la opción **2**, pegue la misma cadena de conexión y, cuando lo pida, la
   contraseña de la API que le compartieron. No se crea ningún archivo SQL: los usuarios ya están activos.
2. `docker compose --profile solo-local down` y luego `docker compose up --build -d --force-recreate`. No hace
   falta crear las cuentas de demostración otra vez: ya están en la base compartida (contraseña `SolunaDemo2026`).

Si la primera persona vuelve a ejecutar `crear-env` sin pegar la contraseña compartida, se genera una nueva:
habría que repetir el paso 2 y volver a compartirla. Para volver a la base en Docker, ejecute `crear-env` y
elija la opción **1**.

### Si la API no enciende con Supabase ("unhealthy")

Casi siempre es la contraseña: la que tiene la API no coincide con la de `app_hotel` en Supabase. Tras varios
intentos fallidos, Supabase además bloquea nuevas conexiones por unos minutos.

1. Apague todo: `docker compose --profile solo-local down`.
2. Genere una contraseña nueva en el `.env`, guarde el SQL en `activar-roles-supabase.sql` y cópielo (Mac):

   ```bash
   NUEVA=$(od -An -tx1 -N24 /dev/urandom | tr -dc '0-9a-f'); sed -i '' "s/^DB_APP_PASSWORD=.*/DB_APP_PASSWORD=$NUEVA/" .env; printf "ALTER ROLE app_hotel WITH LOGIN PASSWORD '%s';\n" "$NUEVA" > activar-roles-supabase.sql; pbcopy < activar-roles-supabase.sql; unset NUEVA; echo "Listo: SQL copiado y guardado en activar-roles-supabase.sql"
   ```

3. En el *SQL Editor* de Supabase, pegue (debe empezar con `ALTER ROLE app_hotel`) y pulse **Run**.
4. Espere un minuto y encienda con contenedores nuevos: `docker compose up -d --force-recreate`.

Nunca pegue la contraseña en un chat, correo o mensaje. Si ocurre, cámbiela con estos mismos pasos y
compártala de nuevo con el equipo por un medio privado.

### Límites del plan gratuito

- Supabase pausa el proyecto tras una semana sin uso; se reactiva desde el panel.
- El plan admite pocas conexiones simultáneas. Cada computadora abre como máximo 6; si varias encienden el
  sistema a la vez y la API registra un error de conexión del *pooler*, apague el sistema en las que no se usen.
- Los respaldos automáticos y la restauración a un punto en el tiempo dependen del plan de pago, por eso
  se mantiene el respaldo propio del bloque 4.

## Despliegue en Vercel

El sistema está publicado en tres proyectos de Vercel conectados a la base de Supabase. La versión de Docker
sigue siendo la que se usa para las demostraciones de réplicas, balanceo y escalado.

| Proyecto | Dirección | Contenido |
|---|---|---|
| `hotel-soluna-web` | https://hotel-soluna-web.vercel.app | El sitio del hotel: **esta es la dirección para abrir en el navegador** |
| `hotel-soluna` | https://hotel-soluna.vercel.app | La API (en la raíz responde `Not Found`; pruebe `/api/salud`) |
| `hotel-soluna-simulador` | https://hotel-soluna-simulador.vercel.app | Pasarela, Hacienda y OTA |

Cada cambio en una rama crea una vista previa de los tres proyectos; producción solo cambia al fusionar en `main`.

### API en Vercel (fase 1)

- **Proyecto:** `hotel-soluna`, con raíz `api/` y el preset de FastAPI (Vercel encuentra `app/main.py`).
  Python 3.13 (`api/.python-version`); duración máxima y archivos excluidos en `api/vercel.json`.
- **Base de datos:** el pooler de Supabase en **modo transacción** (puerto 6543), que reparte las conexiones
  entre todas las instancias de la función. Con `DB_MODO_TRANSACCION=si`, la API no guarda conexiones
  abiertas ni usa sentencias preparadas, que ese modo no admite.
- **Correo:** con `CORREO_SEGUNDO_PLANO=no` se envía dentro de la misma solicitud, porque en Vercel lo que
  corre después de responder puede quedar congelado. El servicio es Brevo (fase 4); con `SMTP_HOST=ninguno`
  el envío se desactiva.
- **Variables de entorno** (producción y vista previa): `DB_HOST`, `DB_PORT=6543`, `DB_NAME=postgres`,
  `DB_USER=app_hotel.<referencia>`, `DB_PASSWORD`, `DB_SSLMODE=require`, `DB_MODO_TRANSACCION=si`,
  `CORREO_SEGUNDO_PLANO=no`, `SMTP_HOST`, `JWT_SECRET`, `SERVICIOS_LLAVE` y `OTA_SECRETO`.
  Las contraseñas se cargan desde el panel de Vercel, nunca en el repositorio.

### Sitio web en Vercel (fase 3)

El sitio (`web/`) es un segundo proyecto, `hotel-soluna-web`, servido desde la red de distribución de
Vercel: no depende de ninguna computadora, así que deja de ser un punto único de falla. `web/vercel.json`
cumple el papel de Nginx:

- **Reenvío:** `/api/*` va a la API (`hotel-soluna.vercel.app`). El navegador sigue viendo un solo dominio,
  así que la política de contenido del sitio (`connect-src 'self'`) no cambia.
- **Sin caché para la API:** sus respuestas dependen de la sesión de cada usuario.
- **Cabeceras de seguridad:** las mismas que agrega Nginx, más HSTS, porque el certificado de Vercel es real.
- En Docker, Nginx no publica `/vercel.json`.

### Simulador de servicios externos en Vercel (fase 2)

La pasarela de pago, Hacienda y la OTA se publican como un tercer proyecto, `hotel-soluna-simulador`, con raíz
`simulador/` y el preset de FastAPI (`simulador/main.py`). Representan a otros proveedores, por eso viven
aparte de la API, igual que en Docker.

- **Estado compartido:** en Vercel cada solicitud puede atenderla una instancia distinta, así que un token
  creado en una debe poder cobrarse en otra. Cuando existe `SIM_DB_HOST`, el simulador guarda tokens, cobros,
  reembolsos, comprobantes y avisos en el esquema `simulador` de Supabase (`simulador/almacen.py`); sin esa
  variable, como en Docker, los guarda en memoria.
- **Aislamiento:** el esquema tiene su propio usuario, `app_simulador`, que no puede leer el esquema `hotel`;
  la API tampoco puede leer el del simulador. Solo `reembolso` se puede modificar en un cobro, y un token se
  borra en la misma operación que lo usa, así que no puede cobrarse dos veces.
- **Datos de tarjeta:** al crear el token solo se guardan la marca, los últimos cuatro dígitos y el resultado
  del cobro; nunca el número completo ni el CVV.
- **Panel protegido:** con `PANEL_PUBLICO=no`, `/panel`, `/ota/enviar` y la consulta de comprobantes exigen
  la llave de servicios, y la documentación interactiva queda desactivada. En Docker siguen abiertos para la
  demostración.
- **Reenvío:** el sitio envía `/pasarela/tokens` al simulador (`web/vercel.json`), así que la tarjeta sigue
  saliendo del navegador hacia la pasarela sin pasar por la API.
- **Variables** (producción y vista previa): `API_URL`, `PANEL_PUBLICO=no`, `SERVICIOS_LLAVE`, `OTA_SECRETO`
  (los mismos valores que en la API), `SIM_DB_HOST`, `SIM_DB_PORT=6543`, `SIM_DB_NAME=postgres`,
  `SIM_DB_USER=app_simulador.<referencia>`, `SIM_DB_PASSWORD` y `SIM_DB_SSLMODE=require`. En la API,
  `SIMULADOR_URL` apunta a `https://hotel-soluna-simulador.vercel.app`.

Para ver el panel del simulador en Vercel:

```bash
curl -H "Authorization: Bearer <SERVICIOS_LLAVE>" https://hotel-soluna-simulador.vercel.app/panel
```

### Correo real en Vercel (fase 4)

En Docker los correos siguen llegando a Mailpit y no salen de la computadora. En Vercel la API los envía por
**Brevo**, un servicio de envío con plan gratuito (300 correos al día) que no exige un dominio propio: basta
con verificar la dirección del remitente. La API no cambia de mecanismo, porque Brevo acepta SMTP con usuario
y contraseña sobre TLS, igual que los demás proveedores.

- **Sin rebotes:** con `CORREO_OMITIR_PRUEBA=si` no se escribe a dominios reservados para pruebas (`.test`,
  `.example`, `.invalid`...). Las cuentas de demostración y los huéspedes de la OTA usan esos dominios, y
  cada rebote dañaría la reputación del remitente. Para ver un correo real, haga la reserva con una cuenta
  de cliente registrada con una dirección verdadera.
- **Sin abuso del formulario:** la suscripción es pública. Pasado el tope de `CORREO_BIENVENIDAS_HORA`
  (30 por defecto), el correo se guarda, pero no se envía la bienvenida; así nadie puede usar el sitio para
  mandar correo masivo a nombre del hotel.
- **Contraseña siempre cifrada:** la API verifica el certificado del servidor (STARTTLS) y se niega a enviar
  la contraseña si `SMTP_TLS` está apagado.
- **Variables** (producción y vista previa): `SMTP_HOST=smtp-relay.brevo.com`, `SMTP_PORT=587`,
  `SMTP_TLS=si`, `SMTP_USUARIO` (el usuario SMTP que muestra Brevo), `SMTP_PASSWORD` (la clave SMTP, como
  variable sensible), `CORREO_REMITENTE` (la dirección verificada en Brevo), `CORREO_DOMINIO` (el dominio del
  sitio, para los identificadores de mensaje) y `CORREO_OMITIR_PRUEBA=si`.

**Configurar Brevo (una sola vez)**

1. Cree una cuenta gratuita en Brevo.
2. En *Senders, domains & dedicated IPs > Senders*, agregue la dirección que usará como remitente y
   confírmela desde el correo que le llega.
3. En *SMTP & API > SMTP*, anote el **usuario SMTP** (termina en `@smtp-brevo.com`) y pulse
   **Generate a new SMTP key**.
4. En Vercel, proyecto `hotel-soluna`, *Settings > Environment Variables*, agregue `SMTP_PASSWORD` con esa
   clave, marcada como **Sensitive**, para *Production* y *Preview*. La clave nunca se pega en un chat ni
   en el repositorio.

Si el remitente es una dirección de un correo gratuito (Gmail, Outlook), Brevo puede reescribir el remitente
para cumplir las reglas de Gmail y Yahoo. El correo llega igual; con un dominio propio verificado en Brevo,
el remitente se conserva.

### Prueba completa en la nube (fase 5)

`pruebas-nube/prueba_vercel.py` recorre el sistema publicado como lo haría un huésped y mide el tiempo de cada
paso. Comprueba:

- el sitio y sus cabeceras de seguridad;
- la API y la base de Supabase;
- reserva, pago aprobado y rechazado, factura y pago repetido;
- cancelación con reembolso y la protección del panel del simulador.

Cancela al final las reservas que crea, así que puede repetirse antes de la exposición. Solo necesita Python 3.10
o superior, sin instalar nada:

```bash
python3 pruebas-nube/prueba_vercel.py
```

En Windows, use `py pruebas-nube\prueba_vercel.py`. Con la llave de servicios en `SERVICIOS_LLAVE`, también
comprueba el registro en Hacienda y el aviso firmado de la OTA. Esa llave se comparte por un medio privado,
nunca por el repositorio.

## Continuidad: respaldos y nodo de contingencia (bloque 4)

El problema de origen incluía "respaldos nunca probados". En la nube, la base vive en Supabase, en una sola
región y sin restauración a un punto en el tiempo en el plan gratuito. La computadora del hotel cumple dos
funciones de continuidad:

- **Guarda copias de la nube.** Un contenedor copia el esquema `hotel` de Supabase cada 6 horas con `pg_dump`,
  usando el usuario `respaldo`, que solo puede leer. Cada copia se comprueba con `pg_restore` antes de darla por
  buena, se guarda con su huella SHA-256 y se conservan las últimas 28 (7 días).
- **Sirve de nodo de contingencia.** Si la nube o Internet fallan, restaura la última copia en la base de Docker
  y el hotel sigue operando en https://localhost, o en la IP de esa computadora dentro de la red del hotel. No
  necesita Internet: usa las imágenes de Docker que ya están en la computadora.

Todo se maneja con `contingencia.sh`, que requiere el `.env` en modo Supabase. En Windows se ejecuta desde
Git Bash.

| Comando | Qué hace |
|---|---|
| `sh contingencia.sh iniciar` | Enciende los respaldos automáticos; el primero se hace de inmediato |
| `sh contingencia.sh respaldar` | Hace un respaldo ahora |
| `sh contingencia.sh estado` | Muestra las copias guardadas y los últimos eventos |
| `sh contingencia.sh simulacro` | Respalda, restaura en una base aparte, compara con la nube y la borra, sin interrumpir nada |
| `sh contingencia.sh activar` | Restaura la última copia y pasa a operar con la base local |
| `sh contingencia.sh volver` | Genera el reporte de lo hecho en contingencia y regresa a la nube |

**Solo una computadora debe encender los respaldos:** la de la persona que creó el `.env` con la opción 2 y
activó los usuarios en Supabase. En las demás, la contraseña de `respaldo` no coincide, y los intentos
fallidos harían que Supabase bloquee por unos minutos la dirección de esa red.

### Simulacro para la exposición

```bash
sh contingencia.sh simulacro
```

Muestra el respaldo, la restauración con el conteo de registros, la comparación entre la nube y el nodo, y el
tiempo total. En las pruebas tomó menos de 10 segundos con los datos de demostración.

### Procedimiento ante una caída de la nube

1. **Activar:** `sh contingencia.sh activar`. Restaura la copia más reciente y enciende Nginx, las tres
   réplicas de la API, el simulador y Mailpit contra la base local. En las pruebas, el hotel volvió a operar
   unos 20 segundos después.
2. **Operar:** el personal entra en https://localhost con sus cuentas de siempre. Lo registrado en la nube
   después de la última copia no está en el nodo: ese es el **RPO**, de hasta 6 horas con el intervalo por
   defecto, y el comando lo indica al restaurar. Los correos quedan en Mailpit hasta volver.
3. **Volver:** cuando la nube responda, `sh contingencia.sh volver`. Guarda en
   `contingencia-cambios-AAAAMMDD-HHMM.csv` las reservas creadas o modificadas durante la contingencia y
   regresa al modo Supabase. Esas reservas se registran en la nube antes de seguir operando; el archivo tiene
   datos de huéspedes, así que Git lo ignora y debe borrarse después.

`activar` no pisa una contingencia con trabajo hecho: si encuentra reservas sin conciliar, pide ejecutar
`volver` primero. Para restaurar una copia en particular: `sh contingencia.sh activar hotel-AAAAMMDDTHHMMSSZ.dump`.

El intervalo y la cantidad de copias se cambian en el `.env` con `RESPALDO_INTERVALO_MINUTOS` y
`RESPALDO_CONSERVAR`.

### Prueba de carga con Locust

`carga/locustfile.py` simula el tráfico de una temporada alta con tres tipos de usuario:

- **Visitantes** (la mayoría): abren la página, consultan el catálogo y buscan habitaciones libres.
- **Clientes:** inician sesión una vez, revisan sus reservas y, de vez en cuando, reservan y cancelan de
  inmediato. Así se ejercen las escrituras y la regla contra la sobreventa sin dejar habitaciones ocupadas.
- **Monitor:** anota qué réplica respondió cada consulta a `/api/salud`, para mostrar el balanceo.

Locust corre en un contenedor, así que no hay que instalar nada. Contra Docker llega por https://localhost
y valida el certificado del prototipo:

```bash
sh carga.sh docker                 # 30 usuarios por 1 minuto contra el prototipo encendido
sh carga.sh vercel                 # 15 usuarios por 1 minuto contra el sitio publicado
sh carga.sh docker 50 2m           # cantidad de usuarios y duración a elección
```

Al terminar se muestra la tabla de tiempos por operación y el reparto entre réplicas. El reporte con gráficos
queda en `carga/resultados/` (Git lo ignora). Contra Vercel se limita a 50 usuarios para no gastar las cuotas
gratuitas.

**Demostración del escalado horizontal en Docker:**

```bash
docker compose up -d --scale api=5 --no-recreate
```

```bash
sh carga.sh docker
```

Nginx incorpora las réplicas nuevas sin reiniciarse, y el resumen muestra la carga repartida entre las cinco.
En Vercel no hay nada que escalar a mano: la plataforma crea y destruye instancias de la función según la
demanda, y el resumen muestra cuántas respondieron.

Los límites de Nginx siguen activos durante la prueba: 10 inicios de sesión por minuto por dirección. Por eso
los clientes simulados inician sesión una sola vez y la prueba no pide tokens de tarjeta.

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

`api/tests` contiene 64 pruebas automáticas. Cubren:

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
- Simulador protegido (fase 2): panel, OTA y comprobantes exigen la llave; sin documentación pública.
- Correo real (fase 4): TLS verificado, sin contraseña en claro, sin envíos a dominios de prueba y tope de bienvenidas.

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
- En Docker, el simulador guarda todo en memoria: al reiniciarlo se pierden sus registros (no los del hotel). En Vercel los guarda en Supabase.
- En Docker, los avisos de la OTA llegan a la API por la red interna. En Vercel entran por Internet, con HTTPS y firma.
- Los límites de solicitudes de Nginx (inicio de sesión, tarjetas y suscripciones) aún no están replicados en Vercel.

## Estado

- [x] **Bloque 1:** base de datos, API con roles, Compose mínimo.
- [x] **Bloque 2:** Nginx con HTTPS, tres réplicas, límite de intentos, interfaz web.
- [x] **Bloque 3:** simulador de pasarela, OTA y factura, más Mailpit.
- [x] **Nube:** base en Supabase; API (fase 1), simulador (fase 2) y sitio (fase 3) en Vercel; correo real con Brevo (fase 4); documentación y prueba completa (fase 5).
- [x] **Bloque 4:** respaldos automáticos de Supabase, nodo de contingencia, simulacro y regreso a la nube.
- [x] **Bloque 4 (carga):** prueba de carga con Locust contra Docker y Vercel.
- [ ] **Bloque 5:** red en Packet Tracer (configuraciones y guía).
- [ ] **Bloque 6:** diagramas.

## Estructura

```
hotel-soluna/
├── docker-compose.yml
├── docker-compose.supabase.yml   modo Supabase: la API usa la base en la nube
├── docker-compose.contingencia.yml  nodo de contingencia: la API usa la copia restaurada
├── contingencia.sh       respaldos, simulacro, contingencia y regreso a la nube
├── .env.example          plantilla de secretos (el .env real no se sube)
├── crear-env.sh / .ps1   crean el .env con contraseñas al azar (Mac y Linux / Windows)
├── db/init/              esquema, catálogo y usuarios de la base local (Docker)
├── supabase/migrations/  el mismo esquema para Supabase (esquema "hotel")
├── respaldo/             respaldar.sh (pg_dump periódico) y restaurar.sh (pg_restore en el nodo)
├── nginx/                imagen de Nginx: HTTPS, balanceo y cabeceras de seguridad
├── web/                  sitio del hotel y panel del personal (HTML, CSS y JavaScript)
│   └── img/              logo e ilustración de la playa
├── simulador/            pasarela de pago, Hacienda y OTA simuladas
├── pruebas-nube/         prueba de punta a punta contra Vercel
├── carga/                prueba de carga con Locust (carga.sh la ejecuta)
├── docs/                 arquitectura en la nube
│   └── diagramas/        modelos ER y relacional (PNG, SVG y draw.io)
└── api/
    ├── Dockerfile
    ├── requirements.txt
    ├── app/              código de la API
    └── tests/            pruebas automáticas
```
