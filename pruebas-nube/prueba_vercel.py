"""Prueba de punta a punta del Hotel Soluna desplegado en Vercel.

Recorre el sistema como lo haría un huésped desde el navegador, siempre a
través del dominio del sitio, y comprueba cada servicio de la arquitectura en
la nube: sitio estático, API, base de datos en Supabase, pasarela de pago,
Hacienda y, si se proporciona la llave de servicios, la agencia de viajes en
línea (OTA). Mide además el tiempo de respuesta de cada paso.

Solo usa la biblioteca estándar de Python 3.10 o superior:

    python3 pruebas-nube/prueba_vercel.py

Variables opcionales:
    SITIO            dirección del sitio (por defecto, producción)
    SIMULADOR        dirección del simulador de servicios externos
    DEMO_PASSWORD    contraseña de las cuentas de demostración
    SERVICIOS_LLAVE  llave de servicios; sin ella se omiten la OTA y Hacienda

Las reservas que crea se cancelan al final, así que puede repetirse antes de
la exposición sin dejar datos de prueba. Termina con código 1 si algo falla.
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

SITIO = os.environ.get("SITIO", "https://hotel-soluna-web.vercel.app").rstrip("/")
SIMULADOR = os.environ.get("SIMULADOR", "https://hotel-soluna-simulador.vercel.app").rstrip("/")
DEMO = os.environ.get("DEMO_PASSWORD", "SolunaDemo2026")
LLAVE = os.environ.get("SERVICIOS_LLAVE", "").strip()

APROBADA, RECHAZADA = "4242 4242 4242 4242", "4000 0000 0000 0002"

resultados: list[tuple[str, bool, float, str]] = []
pendientes_de_cancelar: list[tuple[str, dict]] = []


class Respuesta:
    def __init__(self, estado: int, cabeceras, cuerpo: bytes):
        """Guarda el código HTTP, las cabeceras y el cuerpo decodificado como texto."""
        self.estado, self.cabeceras, self.texto = estado, cabeceras, cuerpo.decode("utf-8", "replace")

    def json(self):
        """Interpreta el cuerpo como JSON (diccionario vacío si viene vacío)."""
        return json.loads(self.texto) if self.texto else {}


def pedir(metodo: str, url: str, json_=None, formulario=None, cabeceras=None) -> tuple[Respuesta, float]:
    """Hace una solicitud HTTP y devuelve la respuesta y su duración en milisegundos.

    Envía el cuerpo como JSON (``json_``) o como formulario (``formulario``). Los errores HTTP
    (4xx y 5xx) no lanzan excepción: se devuelven como respuesta, porque varias
    comprobaciones esperan justamente un error (401, 402, 409).
    """
    datos, tipo = None, None
    if json_ is not None:
        datos, tipo = json.dumps(json_).encode(), "application/json"
    elif formulario is not None:
        datos, tipo = urllib.parse.urlencode(formulario).encode(), "application/x-www-form-urlencoded"
    solicitud = urllib.request.Request(url, data=datos, method=metodo, headers={
        **({"Content-Type": tipo} if tipo else {}), "User-Agent": "prueba-hotel-soluna", **(cabeceras or {})})
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(solicitud, timeout=40) as r:
            respuesta = Respuesta(r.status, r.headers, r.read())
    except urllib.error.HTTPError as error:
        respuesta = Respuesta(error.code, error.headers, error.read())
    return respuesta, (time.perf_counter() - inicio) * 1000


def paso(nombre: str, condicion: bool, ms: float, detalle: str = "") -> bool:
    """Anota el resultado de una comprobación, lo imprime con su tiempo y devuelve si fue
    correcta.
    """
    resultados.append((nombre, condicion, ms, detalle))
    marca = "OK   " if condicion else "FALLA"
    print(f"{marca} {nombre:<52} {ms:7.0f} ms  {detalle}")
    return condicion


def sesion(correo: str) -> dict:
    """Inicia sesión con una cuenta de demostración; si falla, termina la prueba (lo demás
    depende de ella).
    """
    r, ms = pedir("POST", f"{SITIO}/api/auth/login", formulario={"username": correo, "password": DEMO})
    if not paso(f"Inicio de sesión ({correo})", r.estado == 200, ms, str(r.estado)):
        raise SystemExit(terminar())
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def tokenizar(numero: str) -> str | None:
    """Lo que hace el navegador: la tarjeta va a la pasarela, nunca a la API."""
    r, ms = pedir("POST", f"{SITIO}/pasarela/tokens", json_={
        "numero": numero, "titular": "Prueba Automatica", "vencimiento": "12/39", "cvv": "123"})
    paso(f"Pasarela: token de la tarjeta ...{numero[-4:]}", r.estado == 201, ms,
         r.json().get("marca", "") if r.estado == 201 else str(r.estado))
    return r.json().get("token") if r.estado == 201 else None


def terminar() -> int:
    """Cancela las reservas que quedaron abiertas, imprime el resumen con la mediana y el máximo
    de los tiempos y devuelve 1 si alguna comprobación falló.
    """
    for codigo, cabecera in pendientes_de_cancelar:
        pedir("POST", f"{SITIO}/api/reservas/{codigo}/cancelar", cabeceras=cabecera)
    fallas = [n for n, ok, _, _ in resultados if not ok]
    tiempos = sorted(ms for _, _, ms, _ in resultados)
    print("\n" + "-" * 78)
    print(f"{len(resultados) - len(fallas)} de {len(resultados)} comprobaciones correctas. "
          f"Tiempo de respuesta: mediana {tiempos[len(tiempos) // 2]:.0f} ms, máximo {tiempos[-1]:.0f} ms.")
    if fallas:
        print("Fallaron: " + "; ".join(fallas))
    return 1 if fallas else 0


def main() -> int:
    """Recorre el sistema en el orden en que lo usa un huésped y devuelve el código de salida.

    Cada reserva que crea se anota en ``pendientes_de_cancelar``; ``terminar`` las cancela
    al final, aunque una comprobación intermedia falle.
    """
    print(f"Sitio: {SITIO}\nSimulador: {SIMULADOR}\n")

    # 1. Sitio estático en la red de distribución de Vercel
    r, ms = pedir("GET", f"{SITIO}/")
    paso("Sitio: página de inicio", r.estado == 200 and "Soluna" in r.texto, ms, str(r.estado))
    faltan = [c for c in ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options")
              if not r.cabeceras.get(c)]
    paso("Sitio: cabeceras de seguridad", not faltan, 0, ", ".join(faltan) or "CSP, HSTS, X-Frame-Options")

    # 2. API y base de datos en Supabase
    r, ms = pedir("GET", f"{SITIO}/api/salud")
    salud = r.json() if r.estado == 200 else {}
    paso("API: salud y conexión con Supabase", salud.get("base_de_datos") == "ok", ms, json.dumps(salud))
    r, ms = pedir("GET", f"{SITIO}/api/tipos-habitacion")
    paso("API: catálogo público", r.estado == 200 and len(r.json()) == 3, ms, f"{len(r.json())} tipos")

    # 3. Reserva y pago aprobado: pasarela, factura electrónica y Hacienda
    cliente = sesion("cliente@soluna.test")
    entrada = date.today() + timedelta(days=random.randint(180, 330))
    salida = entrada + timedelta(days=2)
    r, ms = pedir("GET", f"{SITIO}/api/disponibilidad?" + urllib.parse.urlencode(
        {"entrada": entrada, "salida": salida, "personas": 2}))
    libres = r.json() if r.estado == 200 else []
    if not paso("API: disponibilidad", len(libres) >= 2, ms, f"{len(libres)} habitaciones libres"):
        return terminar()

    def reservar(habitacion: dict) -> str | None:
        """Reserva una habitación para las fechas de la prueba y la anota para cancelarla al
        final.
        """
        r, ms = pedir("POST", f"{SITIO}/api/reservas", cabeceras=cliente, json_={
            "habitacion_id": habitacion["habitacion_id"], "fecha_entrada": str(entrada),
            "fecha_salida": str(salida), "personas": 2})
        if paso(f"API: reserva de la habitación {habitacion['numero']}", r.estado == 201, ms, str(r.estado)):
            codigo = r.json()["codigo"]
            pendientes_de_cancelar.append((codigo, cliente))
            return codigo
        return None

    codigo = reservar(libres[0])
    token = tokenizar(APROBADA)
    pago = {}
    if codigo and token:
        r, ms = pedir("POST", f"{SITIO}/api/reservas/{codigo}/pago", cabeceras=cliente, json_={"token": token})
        pago = r.json() if r.estado == 200 else {}
        factura = pago.get("factura") or {}
        paso("Pago aprobado: reserva confirmada", pago.get("reserva", {}).get("estado") == "confirmada", ms,
             f"{codigo}, {pago.get('monto')} USD con IVA" if pago else r.texto[:80])
        paso("Hacienda: factura electrónica aceptada", factura.get("estado") == "aceptada", 0,
             f"clave ...{factura.get('clave', '')[-8:]}")
        r, ms = pedir("POST", f"{SITIO}/api/reservas/{codigo}/pago", cabeceras=cliente, json_={"token": token})
        paso("Pago repetido: no se cobra dos veces", r.estado >= 400, ms, str(r.estado))

    # 4. Tarjeta rechazada: la reserva queda pendiente
    codigo2 = reservar(libres[1])
    token2 = tokenizar(RECHAZADA)
    if codigo2 and token2:
        r, ms = pedir("POST", f"{SITIO}/api/reservas/{codigo2}/pago", cabeceras=cliente, json_={"token": token2})
        paso("Pago rechazado: 402 y reserva pendiente", r.estado == 402, ms, r.json().get("detail", "")[:45])

    # 5. Cancelar la reserva pagada: reembolso en la pasarela
    if pago:
        r, ms = pedir("POST", f"{SITIO}/api/reservas/{codigo}/cancelar", cabeceras=cliente)
        ok = r.estado == 200 and r.json().get("estado") == "cancelada"
        paso("Cancelación con reembolso", ok, ms, str(r.estado))
        if ok:
            pendientes_de_cancelar.remove((codigo, cliente))

    # 6. Servicios protegidos del simulador
    r, ms = pedir("GET", f"{SIMULADOR}/panel")
    paso("Simulador: panel protegido sin la llave", r.estado == 401, ms, str(r.estado))
    if not LLAVE:
        print("\n(Sin SERVICIOS_LLAVE: se omiten la consulta a Hacienda y el aviso de la OTA.)\n")
        return terminar()

    autorizacion = {"Authorization": f"Bearer {LLAVE}"}
    if pago.get("factura"):
        r, ms = pedir("GET", f"{SIMULADOR}/hacienda/comprobantes/{pago['factura']['clave']}", cabeceras=autorizacion)
        paso("Hacienda: el comprobante quedó registrado", r.estado == 200, ms, str(r.estado))

    # 7. Aviso firmado de la OTA: el simulador llama a la API por Internet
    r, ms = pedir("POST", f"{SIMULADOR}/ota/enviar", cabeceras=autorizacion,
                  json_={"nombre_huesped": "Prueba Automatica"})
    hotel = r.json().get("respuesta_hotel", {}) if r.estado == 200 else {}
    reserva_ota = hotel.get("cuerpo", {})
    paso("OTA: aviso firmado crea la reserva", hotel.get("codigo_http") == 201, ms,
         reserva_ota.get("codigo", r.texto[:60]))
    if reserva_ota.get("codigo"):
        pendientes_de_cancelar.append((reserva_ota["codigo"], sesion("gerencia@soluna.test")))
    return terminar()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as error:
        print(f"\nNo se pudo conectar: {error.reason}")
        print("En Mac, si el error menciona certificados, ejecute 'Install Certificates.command' "
              "en la carpeta de Python dentro de Aplicaciones.")
        sys.exit(1)
