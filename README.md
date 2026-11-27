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

**Para probar las reseñas** hace falta una estadía ya cumplida, y el sistema no permite reservar fechas pasadas.
Este comando crea una para la cuenta de cliente, con el código `SOL-DEMO01` (terminó hace una semana):

```bash
docker compose exec api python -m app.seed estadia
```

En la base compartida de Supabase ya existe, así que en modo Supabase y en el sitio de Vercel basta con iniciar
sesión como `cliente@soluna.test` y opinar sobre `SOL-DEMO01`. Cada estadía admite una sola reseña.

### Qué ve cada rol en la interfaz

| Rol | Secciones |
|---|---|
| Público | Página de inicio completa: ubicación, habitaciones, amenidades, reseñas, disponibilidad, suscripción por correo y contacto (para reservar debe iniciar sesión o crear una cuenta) |
| Cliente | La misma página de inicio, más Mis reservas (paga en línea, consulta su factura, ve su cuenta de consumos y, durante la estadía, escribe al hotel) |
| Recepcionista | Habitaciones hoy (tablero por piso), Solicitudes de huéspedes (todas las áreas), Recepción (llegadas, salidas, huéspedes en casa y gestión de cada reserva), Disponibilidad, Reservas y Habitaciones (puede reservar a nombre de un huésped) |
| Limpieza | Solicitudes de huéspedes de limpieza, Habitaciones (cambia el estado de limpieza) |
| Mantenimiento | Solicitudes de huéspedes de mantenimiento, Habitaciones (solo lectura) |
| Gerente | Todo lo anterior, más Cuentas del personal, Catálogo de servicios, Bitácora y Correos suscritos |

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
- **Reseñas verificadas:** el botón "Escribir una reseña" pide iniciar sesión y, ya dentro, el código de una
  reservación propia ya cumplida, una calificación de 1 a 5 estrellas y el comentario. La API solo acepta la
  reseña si se cumplen cuatro reglas:
  - la cuenta está activa;
  - la reservación es del usuario: la hizo con su cuenta, o está a nombre de su mismo correo, como las de
    recepción o de la agencia cuando el huésped crea su cuenta después;
  - la estadía está cumplida: no se canceló, no quedó sin pagar y su fecha de salida ya llegó;
  - esa reservación no tiene ya una reseña.

  Un código inexistente y uno ajeno dan la misma respuesta, para no revelar qué códigos existen. Se publica el
  nombre con la inicial del apellido ("Ana S.") y el tipo de habitación, nunca el correo. Mientras no haya
  reseñas reales, la sección muestra las de ejemplo; en "Mis reservas", cada estadía cumplida tiene el botón
  **Opinar** con el código ya escrito.
- **Datos ficticios:** el hotel, el teléfono, la dirección y las reseñas de ejemplo son de demostración.

### Tablero de habitaciones (panel del personal)

Recepción y gerencia ven primero la tarjeta **Habitaciones hoy**: las 46 habitaciones agrupadas por piso, cada
una con su número, su estado de limpieza, su situación y el código de la reserva activa. Pulsar el código abre
la gestión de esa reserva (ingreso, salida, cambios).

| Situación | Cuándo |
|---|---|
| Libre | Nadie alojado ni por llegar hoy |
| Llega hoy | Una reserva confirmada o pendiente de pago empieza hoy ("Sin pagar" si aún no se pagó) |
| Llegada atrasada | La estadía empezó un día anterior y nadie registró el ingreso |
| Ocupada | Hay un huésped alojado |
| Sale hoy | El huésped alojado debe salir hoy ("Salida atrasada" si debió salir antes); si además llega otro, la tarjeta muestra las dos reservas |
| Fuera de servicio | La habitación no se ofrece; si tenía una llegada, avisa que hay que asignar otra |

Arriba se resumen la ocupación, las llegadas y salidas pendientes, las habitaciones libres y listas, las que
faltan por limpiar y las fuera de servicio. La leyenda funciona como filtro: al pulsar una situación se
resaltan solo esas habitaciones. Cada situación lleva además su nombre escrito, para no depender del color.

**Consumo de la base:** el tablero se actualiza solo una vez por minuto, y únicamente mientras la pestaña está
visible y el tablero en pantalla; al volver a la pestaña se actualiza enseguida si los datos tienen más de un
minuto. Cada actualización cuesta tres consultas (sesión, habitaciones y reservas del día), sin importar
cuántas reservas haya. Una pantalla abierta durante un turno de 8 horas hace unas 1440 consultas pequeñas.

### Solicitudes de huéspedes (chat)

Un huésped alojado escribe al hotel desde **Mis reservas** con el botón **Contactar al hotel** (en la estadía en
curso) o, si la reserva la hizo recepción a nombre de su correo, desde el mismo botón arriba de la lista,
escribiendo su código. Solo puede escribir durante la estadía, entre el ingreso y la salida, y hasta 5 mensajes
por minuto. Al primer mensaje elige el tema: recepción y otros, limpieza y amenidades, o algo que no funciona.

Cada conversación es una **solicitud**, que atiende un área:

| Estado | Qué significa |
|---|---|
| Abierta | El huésped escribió y nadie la ha tomado |
| En atención | Alguien la tomó o respondió |
| Resuelta | Se marcó como resuelta, o el huésped registró su salida |

Mientras una solicitud siga abierta, los mensajes nuevos del huésped se suman a ella; después de resuelta, el
siguiente mensaje abre otra. La base garantiza que haya una sola abierta por reserva.

El personal ve la tarjeta **Solicitudes de huéspedes**, con la bandeja a la izquierda y la conversación elegida a
la derecha. Primero aparecen las que esperan respuesta, con el tiempo de espera, y un contador rojo indica
cuántas faltan por responder. Cada área ve lo suyo: limpieza solo lo de limpieza, mantenimiento solo lo de
mantenimiento; recepción y gerencia, todo. Desde la conversación se responde, se toma la solicitud, se pasa a
otra área o se marca resuelta. El huésped no ve el nombre de quien le responde: ve "Hotel Soluna".

**Simulador de huéspedes:** recepción y gerencia tienen el botón **Simular un pedido**, que elige al azar a un
huésped alojado y envía un pedido típico ("El aire acondicionado no enfría", "¿Nos traen dos toallas más?",
"Quisiéramos un taxi al aeropuerto"). Requiere al menos un huésped con el ingreso registrado.

**Consumo de la base:** las pantallas preguntan solo mientras están visibles y piden únicamente lo nuevo: las
solicitudes que cambiaron desde la consulta anterior y los mensajes posteriores al último que ya tienen.

| Pantalla | Frecuencia | Sentencias SQL por consulta |
|---|---|---|
| Bandeja del personal | Cada 30 s | 2 |
| Bandeja con una conversación abierta | Cada 10 s | 4 como máximo |
| Chat del huésped abierto | Cada 10 s | 4 como máximo |

Con la pestaña en segundo plano o el chat cerrado, no hay consultas. Las solicitudes resueltas se borran,
con sus mensajes, a los 90 días (30 con ocupación alta), como parte del mantenimiento automático.

Para probarlo en el sitio:
1. Entre como `recepcion@soluna.test`, registre el ingreso de alguna reserva y pulse **Simular un pedido**.
2. Para el lado del huésped, reserve con entrada hoy a nombre de `cliente@soluna.test` y registre su ingreso.
3. Entre como `cliente@soluna.test`, pulse **Contactar al hotel** y escriba el código de la reserva.

### Recepción (panel del personal)

Debajo del tablero está la tarjeta **Recepción**, con cinco vistas:

| Vista | Qué muestra |
|---|---|
| Llegadas | Reservas confirmadas cuya estadía ya empezó y que aún no ingresan; las de días anteriores aparecen como "Llegada atrasada" |
| Salidas | Huéspedes alojados cuya salida es hoy o ya pasó |
| En casa | Huéspedes alojados ahora mismo |
| Activas | Pendientes de pago, confirmadas y en curso |
| Todas | Sin filtro; es la vista que se usa al buscar por código, nombre, correo o número de habitación |

El botón **Gestionar** abre la reserva con sus datos, el estado de limpieza de la habitación, las acciones
posibles hoy y su historial (tomado de la bitácora, con quién hizo cada cosa):

- **Registrar ingreso (check-in):** la reserva pasa de confirmada a en curso. Se rechaza si está pendiente de
  pago, si todavía no es la fecha de entrada, si la habitación está fuera de servicio o sin limpiar, o si el
  huésped anterior no ha registrado su salida.
- **Registrar salida (check-out):** la reserva pasa a finalizada, la habitación queda sucia para limpieza y el
  huésped recibe un correo de agradecimiento que lo invita a dejar una reseña. Si se va antes de lo previsto,
  las noches restantes se liberan y el monto no cambia.
- **Modificar:** cambia la habitación, las fechas o las personas. Ofrece solo las habitaciones libres, con el
  total recalculado y la diferencia respecto del actual, y avisa al huésped por correo si cambian las fechas o
  la habitación. Si el huésped ya ingresó, la entrada no cambia y la habitación nueva debe estar lista; la
  anterior queda sucia. Una reserva pagada en línea solo admite cambios que no alteran el monto, porque ya
  tiene factura; las noches adicionales se registran como una reserva nueva.
- **Cancelar:** la misma cancelación de siempre, con reembolso si hubo pago en línea.

Para probarlo en el sitio de Vercel o en Docker: entre como `recepcion@soluna.test`, cree una reserva con
entrada hoy con **Nueva reserva** y búsquela en **Llegadas**. Las reservas de recepción nacen confirmadas, así que
admiten el ingreso de inmediato.

### Nueva reserva por teléfono o en el mostrador

Cuando alguien llama para reservar, recepción pulsa **Nueva reserva** (tarjeta Recepción) y completa tres pasos:

1. **Fechas y personas.** Empieza con entrada hoy y salida mañana.
2. **Habitación.** Muestra los tipos libres para esas fechas, con cuántas quedan y el total sin IVA, y deja
   elegir el número de habitación.
3. **Huésped.** Nombre, correo y teléfono de contacto, y cómo llegó la reserva: **por teléfono** (el teléfono
   es obligatorio) o **en el mostrador** (opcional).

Antes de confirmar, el formulario muestra el total con IVA a pagar al llegar y la hora de garantía. El botón
**Reservar** de Disponibilidad abre el mismo formulario, con las fechas y el tipo ya elegidos. Al crearla, la
reserva queda confirmada con su código y se abre en la gestión de reservas.

El huésped recibe un correo con el código, la habitación, las fechas, el teléfono registrado, el desglose del
monto a pagar en la recepción (hospedaje, IVA del 13 % y total) y la política de garantía:

> Le guardamos la habitación y la tarifa acordada hasta las 5:00 p. m. del día de llegada. Si no se presenta
> antes de esa hora, la reserva se liberará automáticamente: no podremos conservar el precio acordado y su
> estadía dependerá de las habitaciones disponibles en ese momento. Si ya pagó un adelanto, la reserva se
> mantiene.

La garantía aplica a las reservas que se pagan al llegar (por teléfono o en el mostrador) mientras el huésped no
ha ingresado; las reservas en línea ya están pagadas y las de la agencia las garantiza la agencia. No aplica si
el huésped pagó un adelanto en la recepción, ni si la reserva se tomó después de la hora de garantía de su mismo
día de llegada (por ejemplo, una llamada a las 7 p. m. para llegar esa noche): en ese caso el correo explica que
la habitación queda a su nombre para esa noche y no se libera sola. La hora se configura con la variable
`HORA_GARANTIA` (17 por omisión) y el teléfono del hotel que aparece en el correo, con `TELEFONO_HOTEL`. Si se
modifican las fechas o la habitación, el correo de cambio repite el monto y la nueva garantía.

#### Liberación automática de las reservas no presentadas

Cuando vence la garantía, la reserva se cancela sola y la habitación vuelve a estar disponible. La regla vive en
una función de la base, `liberar_no_presentados()`, que cancela las reservas confirmadas que se pagan al llegar,
sin adelanto, tomadas antes de la hora de garantía y cuya hora de garantía ya pasó. La ejecutan dos caminos que
hacen exactamente lo mismo:

- **`pg_cron`, cada hora en el minuto 5** (tarea `soluna-liberar-no-presentados`). La corrida de las 5:05 p. m.
  libera las llegadas del día pocos minutos después del plazo.
- **El botón Liberar no presentados** de Recepción, para no esperar a la siguiente corrida. Pide confirmación
  y avisa qué reservas liberó (o que no había ninguna).

Entre el vencimiento y la liberación, el tablero y la lista de recepción muestran **Garantía vencida**. Cada
reserva liberada queda en su historial como *Liberada: no se presentó antes de la hora de garantía*, hecha por
el sistema; si la liberación la pidió una persona con el botón, la bitácora también registra quién. La función
es idempotente: una reserva liberada queda cancelada y no vuelve a cumplir las condiciones. No envía correo,
porque la confirmación ya anunció la política. En Docker no hay `pg_cron`; ahí se usa el botón o
`docker compose exec db psql -U postgres -d hotel -c "SELECT * FROM liberar_no_presentados()"`.

### Cuenta de la habitación: consumos y factura final

Cada reserva tiene una **cuenta de la habitación**, que se ve en la gestión de la reserva (**Gestionar**). Ahí
se cargan los consumos del huésped mientras está alojado: room service, restaurante, bar, minibar, spa,
lavandería, transporte, tours u otros servicios que la habitación no incluye. Se cargan del **catálogo de
servicios** o como cargo libre, con descripción, categoría y precio.

| Concepto | Cómo se calcula |
|---|---|
| Hospedaje | El total de la estadía si se paga en el hotel (recepción o teléfono); si se pagó en línea o lo paga la agencia, no suma |
| Consumos | Los cargos vigentes (los anulados quedan a la vista, tachados, con su motivo) |
| IVA | 13 % del subtotal, igual que en la factura |
| Pagado | Pagos recibidos en recepción: al llegar, adelantos o al salir (efectivo, tarjeta, SINPE Móvil o transferencia) |
| **Por pagar a la salida** | Total menos lo pagado; se muestra también en la ficha de la reserva |

- **Al registrar la salida:** si queda saldo, el botón pasa a ser **Cobrar USD X y registrar salida**. Cobra el
  saldo exacto con el método elegido y emite la **factura electrónica final**, con una línea por concepto
  (hospedaje y cada consumo), que se envía al simulador de Hacienda. Sin método de pago, la API rechaza la salida.
- **Correo de salida:** incluye el resumen de la cuenta (cada consumo, IVA, total, pagos) y el número de la
  factura final.
- **El huésped** ve su cuenta desde **Mis reservas > Mi cuenta**, sin los nombres del personal.
- **Gerencia** administra el **Catálogo de servicios**: agrega, cambia precios, activa y desactiva. Un cambio de
  precio no altera lo ya cargado, porque cada cargo copia el precio del momento.
- **Nada se borra:** un cargo equivocado se anula con motivo, un pago no se edita y los montos de una factura
  nunca cambian. Cada carga, anulación y pago queda en la bitácora y en el historial de la reserva.

Una reserva puede tener dos facturas: la del hospedaje pagado en línea y la de la cuenta final.

### Pago por SINPE Móvil o transferencia con comprobante

Ninguna pasarela confirma un SINPE Móvil o una transferencia: los confirma una persona que revisa la cuenta del
hotel. Por eso, además de la tarjeta, el cliente puede pagar por su cuenta y enviar el comprobante, que recepción
revisa:

1. **El cliente**, en **Mis reservas**, pulsa **SINPE o transferencia** en una reserva pendiente de pago. Ve el
   monto exacto con IVA y los datos del hotel, que son de demostración (`SINPE_HOTEL`, `CUENTA_HOTEL`,
   `TITULAR_CUENTA_HOTEL`), y envía el número del comprobante, el monto y, si quiere, una imagen o un PDF. El
   navegador comprime la imagen: una foto de 8 MB queda en unos 400 KB. La reserva muestra **Comprobante en
   revisión** y no se puede pagar con tarjeta mientras tanto.
2. **Recepción** ve la sección **Comprobantes de pago**, con un contador, la reserva, el monto esperado y el
   archivo. **Aceptar** registra el pago, confirma la reserva y emite la factura electrónica, igual que un pago
   con tarjeta. **Rechazar** pide un motivo; el cliente lo ve en Mis reservas y puede enviar otro comprobante.

Cada paso queda respaldado con un correo:

| Momento | Destinatario | Asunto |
|---|---|---|
| El cliente envía el comprobante | Cliente | Recibimos su comprobante de pago |
| El cliente envía el comprobante | Buzón de recepción (`CORREO_RECEPCION`; por omisión, el remitente) | Comprobante por revisar |
| Recepción lo acepta | Cliente | Reserva confirmada, con la factura |
| Recepción lo rechaza | Cliente | No pudimos confirmar su pago, con el motivo |

Además, cada paso queda en la bitácora y en el historial de la reserva. Reglas que aplica la API y, varias, la
base de datos:

- **Un comprobante en revisión por reserva**, con el monto exacto de la reserva con IVA.
- **Número único por método:** un mismo comprobante no respalda dos pagos; uno rechazado sí puede reenviarse.
- **Archivo verificado por su contenido**, no por su nombre: solo JPG, PNG o PDF, de 1,5 MB como máximo. Recepción
  lo ve desde el panel, sin que quede guardado en la caché del navegador.
- **Nada se borra:** la API no puede borrar comprobantes ni cambiar lo que envió el cliente. El mantenimiento
  borra la imagen 90 días después de revisada y conserva el registro como respaldo del pago.
- **Cancelación:** si el cliente cancela antes de la revisión, el comprobante queda sin efecto. Si ya estaba
  pagada, la devolución no pasa por la pasarela: queda registrada y el correo indica que se hará por el mismo
  medio.

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
- Si la base supera los 500 MB, Supabase la pasa a solo lectura: no se podría reservar ni pagar. Para
  evitarlo hay un mantenimiento automático (siguiente sección).

### Mantenimiento automático de la base

Las consultas de lectura, como las del panel de recepción, no dejan nada guardado en la base. Lo que crece con
el uso son los registros: la bitácora, el historial de las tareas programadas y las llaves de idempotencia del
simulador. La función `hotel.mantenimiento()` los recorta con esta política:

| Qué se limpia | Ocupación normal | Ocupación alta (70 % de los 500 MB o más) |
|---|---|---|
| Bitácora | Registros de más de 365 días | Registros de más de 90 días |
| Historial de `pg_cron` (`cron.job_run_details`) | Más de 7 días | Más de 3 días |
| Llaves de idempotencia y tokens vencidos del simulador | Más de 7 días | Más de 7 días |
| Solicitudes de huéspedes resueltas, con sus mensajes | Más de 90 días | Más de 30 días |
| Imágenes de comprobantes de pago ya revisados (el registro se conserva) | Más de 90 días | Más de 30 días |

`pg_cron` la ejecuta en Supabase con dos tareas. La tabla incluye otras dos tareas programadas que no limpian la
base: una libera las reservas no presentadas (ver *Liberación automática de las reservas no presentadas*) y la
otra mueve la simulación de huéspedes (ver *Historial simulado*).

| Tarea | Cuándo | Qué hace |
|---|---|---|
| `soluna-vigilar-ocupacion` | Cada hora (minuto 47) | Mide la base; si la ocupación es alta, limpia de inmediato |
| `soluna-limpieza-diaria` | Todos los días a las 03:17 de Costa Rica | Aplica la retención normal y deja constancia en la bitácora |
| `soluna-liberar-no-presentados` | Cada hora (minuto 5) | Cancela las reservas que se pagan al llegar cuya garantía venció |
| `soluna-simulacion` | Cada hora (minuto 20) | Registra la salida de los huéspedes simulados y limpia las habitaciones que dejaron |

Los 365 días siguen el mínimo de 12 meses de conservación de la bitácora de PCI DSS 4.0 (requisito 10.5.1), y
los 90 días, los 3 meses que esa norma pide mantener disponibles de inmediato. La ocupación alta es una medida
de emergencia: antes de llegar ahí convendría exportar la bitácora antigua o pasar al plan Pro.

Además, ninguna consulta de la API o del simulador puede ocupar la base más de 15 segundos, ni dejar una
transacción abierta e inactiva más de 60. La espera legítima más larga es la de un pago, que bloquea su
reserva mientras la pasarela responde (hasta 12 segundos). Por omisión, PostgreSQL permitiría minutos.

Para revisar el mantenimiento:

- **Panel de Supabase:** *Integrations > Cron > History* muestra el resultado de cada corrida (por ejemplo,
  `12 MB de 500 MB; borradas: 0 de bitácora...`).
- **Bitácora del hotel:** gerencia ve una entrada `mantenimiento` por día, con el tamaño de la base y lo borrado.
- **A mano:** `SELECT hotel.mantenimiento();` en el editor SQL de Supabase. En Docker, donde no hay
  `pg_cron` ni límite de plan, `docker compose exec db psql -U postgres -d hotel -c "SELECT mantenimiento()"`.

## Historial simulado (solo en Supabase)

Para que el sistema publicado tenga movimiento y acumule un historial realista, Supabase aloja huéspedes
ficticios que llegan, se hospedan y se van solos. Cada estadía simulada deja la misma huella que una real:

- **Reserva y bitácora:** código, canal y su historial completo (creación o pago, ingreso y salida).
- **Cobros y facturas:** las reservas en línea tienen su pago aprobado y su factura del hospedaje. Al salir, las
  que se pagan en el hotel cobran el saldo y emiten la factura final, con una línea por concepto.
- **Limpieza:** la habitación queda sucia al salir el huésped y, en el turno de limpieza (7:00 a 17:00), se marca
  limpia unas dos horas después.

Los nombres, los códigos y los correos son al azar, y los correos son siempre de dominios `.test`, a los que la API
nunca escribe. La simulación vive en el esquema `simulacion`
(`supabase/migrations/20261127175721_simulacion.sql`): el respaldo no lo copia, porque solo copia `hotel`. Solo
actúa sobre las estadías registradas en `simulacion.estadias`, así que no toca las reservas reales ni las de
prueba del personal. Si recepción registra a mano la salida de un huésped simulado, la simulación ya no lo toca;
y si el personal cambia el estado de limpieza de una habitación, la simulación deja de limpiarla.

En el editor SQL de Supabase:

| Qué hacer | Instrucción |
|---|---|
| Agregar huéspedes que llegan hoy (por ejemplo, 8 que se van en los próximos 14 días) | `SELECT * FROM simulacion.nuevo_lote(8, 14);` |
| Registrar ya las salidas vencidas, sin esperar la corrida horaria | `SELECT simulacion.registrar_salidas();` |
| Ver las estadías simuladas en curso | `SELECT r.codigo, r.fecha_salida, e.hora_salida FROM hotel.reservas r JOIN simulacion.estadias e ON e.reserva_id = r.id WHERE r.estado = 'en_curso';` |
| Borrar toda la simulación (reservas, cobros, facturas y bitácora) | `SELECT simulacion.borrar();` |

`nuevo_lote` solo ocupa habitaciones libres para toda la estadía, en servicio y listas para huéspedes; si no hay
suficientes, crea las que quepan. La API no puede ejecutar estas funciones: solo el administrador de la base y
`pg_cron`.

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
| POST | `/api/reservas` | Cliente, recepcionista, gerente. El personal indica `canal` (`recepcion` o `telefono`) y `telefono_huesped`, obligatorio por teléfono |
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
| GET | `/api/resenas` | Público: promedio, total y las reseñas más recientes |
| POST | `/api/resenas` | Cuenta activa con una reservación propia ya cumplida (una reseña por reservación) |
| GET | `/api/gestion/tablero` | Recepcionista, gerente: situación de cada habitación hoy e indicadores del día |
| POST | `/api/gestion/liberar-no-presentados` | Recepcionista, gerente: libera ya las reservas con la garantía vencida (lo mismo que `pg_cron` cada hora) |
| GET | `/api/gestion/reservas` | Recepcionista, gerente: búsqueda y vistas de recepción (`vista`, `q`) |
| GET | `/api/gestion/reservas/{codigo}` | Recepcionista, gerente: detalle con acciones posibles e historial |
| GET | `/api/gestion/reservas/{codigo}/alternativas` | Recepcionista, gerente: habitaciones a las que se puede mover, con su total |
| POST | `/api/gestion/reservas/{codigo}/check-in` | Recepcionista, gerente |
| POST | `/api/gestion/reservas/{codigo}/check-out` | Recepcionista, gerente |
| PATCH | `/api/gestion/reservas/{codigo}` | Recepcionista, gerente: cambia habitación, fechas o personas |
| GET | `/api/gestion/reservas/{codigo}/cuenta` | Recepcionista, gerente: estado de cuenta con lo que falta por pagar a la salida |
| POST | `/api/gestion/reservas/{codigo}/cargos` | Recepcionista, gerente: carga un consumo del catálogo o libre (huésped alojado) |
| POST | `/api/gestion/reservas/{codigo}/cargos/{id}/anular` | Recepcionista, gerente: anula un cargo con motivo |
| POST | `/api/gestion/reservas/{codigo}/pagos` | Recepcionista, gerente: pago en caja, sin superar el saldo |
| POST | `/api/gestion/reservas/{codigo}/check-out` | Recibe `metodo_pago` si hay saldo: lo cobra y emite la factura final |
| GET | `/api/servicios` | Recepcionista, gerente (con `todos=true`, gerencia ve también los inactivos) |
| POST/PATCH | `/api/servicios`, `/api/servicios/{id}` | Gerente: agrega, cambia, activa o desactiva servicios |
| GET | `/api/reservas/{codigo}/cuenta` | Cliente titular: su cuenta, sin nombres del personal |
| GET/POST | `/api/reservas/{codigo}/comprobantes` | Cliente titular: datos para pagar por SINPE o transferencia y envío del comprobante |
| GET | `/api/gestion/comprobantes` | Recepcionista, gerente: comprobantes por revisar o revisados (7 días) |
| GET | `/api/gestion/comprobantes/{id}/archivo` | Recepcionista, gerente: la imagen o el PDF del comprobante |
| POST | `/api/gestion/comprobantes/{id}/aceptar` | Recepcionista, gerente: registra el pago, confirma la reserva y la factura |
| POST | `/api/gestion/comprobantes/{id}/rechazar` | Recepcionista, gerente: rechaza con motivo |
| GET | `/api/solicitudes` | Personal, cada área lo suyo: bandeja; con `desde`, solo lo que cambió, y con `abierta` y `despues`, los mensajes nuevos de una conversación |
| POST | `/api/solicitudes/{id}/mensajes` | Personal del área: responde al huésped |
| PATCH | `/api/solicitudes/{id}` | Personal del área: tomar, pasar a otra área, resolver o reabrir |
| POST | `/api/solicitudes/simular` | Recepcionista, gerente: pedido de un huésped alojado al azar |
| GET | `/api/reservas/{codigo}/solicitudes` | Cliente titular de la reserva (por cuenta o por correo): su conversación |
| POST | `/api/reservas/{codigo}/solicitudes` | Cliente titular, solo durante la estadía y hasta 5 mensajes por minuto |

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
- **Cuenta de la habitación:** la API puede registrar cargos, pagos y servicios, pero no borrarlos; de un cargo
  solo puede escribir su anulación (quién, cuándo y por qué), y de una factura nunca cambia montos ni líneas.
  Ningún pago en caja supera el saldo, y la salida no se registra con saldo pendiente sin cobrarlo.
- **Chat con huéspedes:** solo escribe el titular de la reserva, durante su estadía y hasta 5 mensajes por
  minuto; un código ajeno responde igual que uno inexistente. Cada área del personal ve solo sus solicitudes. La
  API puede crear y leer solicitudes y mensajes, pero no editar ni borrar mensajes, ni cambiar a qué reserva
  pertenece una solicitud. Los mensajes se muestran como texto, nunca como HTML.
- **Recepción:** el ingreso, la salida y los cambios bloquean la fila de la reserva (y la de la habitación en
  el ingreso y la salida), así que dos personas no pueden alojar a dos huéspedes en la misma habitación al mismo
  tiempo. Los cambios pasan por la misma regla `sin_traslape` que impide la sobreventa.
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

`api/tests` contiene 212 pruebas automáticas. Cubren:

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
- Reseñas verificadas: sin sesión, código ajeno o inexistente, estadía futura, cancelada o sin pagar, reseña
  repetida, huésped que crea su cuenta después de reservar, datos inválidos y permisos de la base.
- Recepción: permisos por rol, vistas y búsqueda (con comodines escapados), el ciclo de un día (habitación
  ocupada, salida, habitación sucia, limpieza e ingreso), ingresos rechazados, llegada atrasada, salida
  anticipada que libera noches, cambios de habitación, fechas y personas con total recalculado, traslape al
  mover, reglas para huéspedes alojados, reservas pagadas que no cambian de monto y alternativas ofrecidas.
- Tablero de habitaciones: permisos, cada situación (incluido el día de cambio de huésped, la salida atrasada,
  la reserva sin pagar y la habitación fuera de servicio con una llegada), indicadores, cambios tras el ingreso y
  la salida, y un número fijo de consultas aunque crezcan las reservas.
- Cuenta de la habitación: cargos del catálogo y libres, precio copiado al cargar, solo con el huésped alojado,
  anulación con motivo, pagos parciales y excesivos, hospedaje pagado en línea o por agencia, salida que cobra el
  saldo y emite la factura final aceptada por el simulador de Hacienda, convivencia con la factura del hospedaje,
  vista del huésped, catálogo de gerencia y permisos de la base.
- Solicitudes de huéspedes: una sola solicitud abierta por reserva, reserva por cuenta o por correo, código
  ajeno igual a inexistente, escritura solo durante la estadía, límite por minuto, mensajes inválidos, cada área
  ve lo suyo, conversación completa, tomar, reasignar y reabrir, consultas incrementales, número fijo de
  sentencias, simulador, cierre al registrar la salida, permisos de la base y retención.
- Reservas por teléfono: teléfono obligatorio y su formato (en la API y en la base), canal de mostrador, el
  cliente no elige canal, correo con monto, IVA, teléfono y política de garantía, garantía solo para pago al
  llegar, garantía vencida en el tablero y correo de cambio con el monto nuevo.
- Liberación de no presentados: cancela la llegada vencida sin adelanto y deja constancia del sistema y de quién
  pulsó el botón; no toca reservas en línea, de la agencia, ya hospedadas, con adelanto, de mañana ni tomadas
  después de la hora de garantía; es idempotente; respeta `HORA_GARANTIA`; la función responde sin la API (como
  la llama `pg_cron`); tablero, detalle y correo anuncian lo mismo que hace la función; permisos por rol.
- Comprobantes de SINPE Móvil o transferencia: acuse al cliente y aviso a recepción, número normalizado y único,
  monto exacto, archivo validado por su contenido (tipo y tamaño), un comprobante en revisión a la vez, solo el
  titular, tarjeta bloqueada mientras se revisa, bandeja y archivo solo para recepción y gerencia, aceptación con
  pago, confirmación y factura, rechazo con motivo y reenvío, cancelación con el comprobante pendiente o ya
  pagado, retención de las imágenes y permisos de la base.
- Mantenimiento de la base: retención de un año, recorte a 90 días con ocupación alta, vigilancia sin efectos
  con ocupación normal, limpieza de idempotencia, función vedada a la API y límites de tiempo por consulta.

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
