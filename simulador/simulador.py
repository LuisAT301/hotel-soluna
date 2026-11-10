"""Simulador de los servicios externos del Hotel Soluna.

Reemplaza, solo para el prototipo, a tres proveedores reales:

  1. Pasarela de pago   /pasarela/...  tokeniza tarjetas, cobra y reembolsa.
  2. Hacienda           /hacienda/...  recibe y acepta las facturas electrónicas.
  3. OTA                /ota/...       una agencia de viajes en línea que envía
                                       reservas al hotel con un aviso firmado.

Guarda todo en memoria: al reiniciar el contenedor se borra, como corresponde
a un entorno de pruebas. Por eso corre una sola copia.

Panel para la demostración (solo en el propio equipo): http://localhost:8090/docs
"""
import hashlib
import hmac
import json
import os
import random
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


def leer(nombre: str, defecto: str | None = None) -> str | None:
    """Igual que en la API: NOMBRE_FILE (secreto de Docker) o NOMBRE."""
    ruta = os.getenv(f"{nombre}_FILE")
    if ruta:
        return Path(ruta).read_text(encoding="utf-8").strip()
    return os.getenv(nombre, defecto)


LLAVE_SERVICIOS = leer("SERVICIOS_LLAVE")   # la API la presenta al cobrar y al facturar
OTA_SECRETO = leer("OTA_SECRETO")           # firma los avisos de la OTA
API_URL = leer("API_URL", "http://api:8000")
if not LLAVE_SERVICIOS or not OTA_SECRETO:
    raise RuntimeError("Faltan SERVICIOS_LLAVE u OTA_SECRETO (o sus variantes _FILE)")

app = FastAPI(
    title="Simulador de servicios externos",
    version="0.1.0",
    description=(
        "Pasarela de pago, Hacienda y OTA simuladas para el prototipo del Hotel Soluna.\n\n"
        "**Tarjetas de prueba** (cualquier vencimiento futuro y cualquier CVV de 3 dígitos):\n\n"
        "| Número | Resultado |\n|---|---|\n"
        "| 4242 4242 4242 4242 | Aprobada (Visa) |\n"
        "| 5555 5555 5555 4444 | Aprobada (Mastercard) |\n"
        "| 4000 0000 0000 0002 | Rechazada: fondos insuficientes |\n"
        "| 4000 0000 0000 0119 | La pasarela falla (error 503) |"
    ),
)

ahora = lambda: datetime.now(timezone.utc)  # noqa: E731


# =====================================================================
# 1. Pasarela de pago
# =====================================================================
MINUTOS_TOKEN = 15
RECHAZADAS = {"4000000000000002": "fondos insuficientes"}
FALLA_PASARELA = "4000000000000119"

tokens: dict[str, dict] = {}        # token -> tarjeta (vive 15 minutos, se usa una vez)
cobros: dict[str, dict] = {}        # id de transacción -> cobro o reembolso
idempotencia: dict[str, dict] = {}  # Idempotency-Key -> datos recibidos y respuesta ya dada

_portador = HTTPBearer(auto_error=False)


def autorizar(credencial: HTTPAuthorizationCredentials | None = Depends(_portador)) -> None:
    """Solo la API del hotel, que conoce la llave, puede cobrar o facturar."""
    if credencial is None or not hmac.compare_digest(credencial.credentials, LLAVE_SERVICIOS):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Llave de comercio inválida")


def luhn_valido(numero: str) -> bool:
    """Dígito verificador que traen todas las tarjetas (algoritmo de Luhn)."""
    total = 0
    for i, digito in enumerate(int(d) for d in reversed(numero)):
        if i % 2:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return total % 10 == 0


def marca(numero: str) -> str:
    if numero.startswith("4"):
        return "Visa"
    if numero[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(numero[:4]) <= 2720:
        return "Mastercard"
    if numero[:2] in {"34", "37"}:
        return "American Express"
    return "Otra"


class Tarjeta(BaseModel):
    numero: str = Field(min_length=12, max_length=23, description="Puede llevar espacios")
    titular: str = Field(min_length=2, max_length=80)
    vencimiento: str = Field(pattern=r"^(0[1-9]|1[0-2])/\d{2}$", description="MM/AA")
    cvv: str = Field(pattern=r"^\d{3,4}$")


@app.post("/pasarela/tokens", tags=["pasarela"], status_code=201)
def tokenizar(tarjeta: Tarjeta):
    """El navegador del cliente envía la tarjeta aquí, nunca a la API del hotel.

    Devuelve un token de un solo uso que la API presenta para cobrar.
    """
    numero = tarjeta.numero.replace(" ", "").replace("-", "")
    if not numero.isdigit() or not 12 <= len(numero) <= 19 or not luhn_valido(numero):
        raise HTTPException(422, "El número de tarjeta no es válido")
    mes, anio = (int(p) for p in tarjeta.vencimiento.split("/"))
    hoy = date.today()
    if (2000 + anio, mes) < (hoy.year, hoy.month):
        raise HTTPException(422, "La tarjeta está vencida")

    token = "tok_" + secrets.token_urlsafe(18)
    tokens[token] = {"numero": numero, "titular": tarjeta.titular,
                     "vence": time.monotonic() + MINUTOS_TOKEN * 60}
    # El CVV se valida y se descarta: ni siquiera la pasarela lo conserva
    return {"token": token, "marca": marca(numero), "ultimos4": numero[-4:]}


class Cobro(BaseModel):
    token: str
    monto: Decimal = Field(gt=0, decimal_places=2)
    moneda: Literal["USD"] = "USD"
    referencia: str = Field(max_length=40)
    descripcion: str = Field(default="", max_length=200)


@app.post("/pasarela/cobros", tags=["pasarela"], dependencies=[Depends(autorizar)])
def cobrar(cobro: Cobro, idempotency_key: str = Header(min_length=8, max_length=100)):
    """Cobra a la tarjeta del token.

    Si la API repite la solicitud con la misma Idempotency-Key (por ejemplo,
    porque se cortó la conexión), recibe la misma respuesta y no se cobra dos veces.
    """
    huella = cobro.model_dump_json()
    if idempotency_key in idempotencia:
        anterior = idempotencia[idempotency_key]
        if anterior["huella"] != huella:
            # Misma llave con otros datos: es un error del comercio, no un reintento
            raise HTTPException(422, "La llave de idempotencia ya se usó con otros datos")
        return anterior["respuesta"]

    tarjeta = tokens.pop(cobro.token, None)
    if tarjeta is None or tarjeta["vence"] < time.monotonic():
        raise HTTPException(422, "El token de pago no es válido o ya se usó")
    if tarjeta["numero"] == FALLA_PASARELA:
        tokens[cobro.token] = tarjeta  # el cliente podrá reintentar con el mismo token
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Pasarela fuera de servicio (simulado)")

    motivo = RECHAZADAS.get(tarjeta["numero"])
    resultado = {
        "transaccion": "ch_" + secrets.token_hex(10),
        "tipo": "cobro",
        "estado": "rechazado" if motivo else "aprobado",
        "motivo": motivo,
        "monto": str(cobro.monto),
        "moneda": cobro.moneda,
        "referencia": cobro.referencia,
        "marca": marca(tarjeta["numero"]),
        "ultimos4": tarjeta["numero"][-4:],
        "fecha": ahora().isoformat(),
    }
    cobros[resultado["transaccion"]] = resultado
    idempotencia[idempotency_key] = {"huella": huella, "respuesta": resultado}
    return resultado


@app.post("/pasarela/cobros/{transaccion}/reembolso", tags=["pasarela"], dependencies=[Depends(autorizar)])
def reembolsar(transaccion: str):
    """Devuelve el monto completo de un cobro aprobado. Repetirlo no reembolsa dos veces."""
    original = cobros.get(transaccion)
    if original is None or original["tipo"] != "cobro" or original["estado"] != "aprobado":
        raise HTTPException(404, "Cobro aprobado no encontrado")
    if "reembolso" in original:
        return cobros[original["reembolso"]]
    resultado = {**original, "transaccion": "re_" + secrets.token_hex(10), "tipo": "reembolso",
                 "estado": "aprobado", "original": transaccion, "fecha": ahora().isoformat()}
    original["reembolso"] = resultado["transaccion"]
    cobros[resultado["transaccion"]] = resultado
    return resultado


# =====================================================================
# 2. Hacienda (recepción de comprobantes electrónicos)
# =====================================================================
IVA = Decimal("0.13")
comprobantes: dict[str, dict] = {}


class Linea(BaseModel):
    detalle: str
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal
    subtotal: Decimal


class Comprobante(BaseModel):
    clave: str
    consecutivo: str
    fecha_emision: datetime
    emisor: dict
    receptor: dict
    lineas: list[Linea] = Field(min_length=1)
    subtotal: Decimal
    impuesto: Decimal
    total: Decimal


@app.post("/hacienda/recepcion", tags=["hacienda"], dependencies=[Depends(autorizar)])
def recibir_comprobante(c: Comprobante):
    """Revisa la factura y responde "aceptada" o "rechazada" con el motivo."""
    if c.clave in comprobantes:
        return comprobantes[c.clave]["respuesta"]
    errores = []
    if not (len(c.clave) == 50 and c.clave.isdigit() and c.clave.startswith("506")):
        errores.append("la clave debe tener 50 dígitos y empezar con 506")
    if not (len(c.consecutivo) == 20 and c.consecutivo.isdigit()):
        errores.append("el consecutivo debe tener 20 dígitos")
    elif c.clave[21:41] != c.consecutivo:
        errores.append("el consecutivo no coincide con la clave")
    if sum(linea.subtotal for linea in c.lineas) != c.subtotal:
        errores.append("la suma de las líneas no coincide con el subtotal")
    if (c.subtotal * IVA).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != c.impuesto:
        errores.append("el IVA no corresponde al 13 %")
    if c.subtotal + c.impuesto != c.total:
        errores.append("el total no es subtotal más impuesto")

    respuesta = {
        "clave": c.clave,
        "estado": "rechazada" if errores else "aceptada",
        "mensaje": "; ".join(errores) or "Comprobante aceptado",
        "fecha": ahora().isoformat(),
    }
    comprobantes[c.clave] = {"comprobante": c.model_dump(mode="json"), "respuesta": respuesta}
    return respuesta


@app.get("/hacienda/comprobantes/{clave}", tags=["hacienda"])
def consultar_comprobante(clave: str):
    if clave not in comprobantes:
        raise HTTPException(404, "Comprobante no encontrado")
    return comprobantes[clave]


# =====================================================================
# 3. OTA: agencia de viajes en línea que envía reservas al hotel
# =====================================================================
NOMBRES = ["María Fernández", "John Carter", "Sofía Rojas", "Lukas Becker", "Ana Lucía Vargas",
           "Emma Dubois", "Diego Solano", "Hannah Smith", "Valeria Chaves", "Marco Bianchi"]
TIPOS = ["estándar", "superior", "suite"]
CAPACIDAD = {"estándar": 2, "superior": 3, "suite": 4}
enviadas: list[dict] = []


def firmar(cuerpo: bytes, fecha: int, secreto: str) -> str:
    """HMAC-SHA256 de "fecha.cuerpo". El hotel recalcula la firma con el mismo secreto."""
    return "sha256=" + hmac.new(secreto.encode(), f"{fecha}.".encode() + cuerpo, hashlib.sha256).hexdigest()


class EnvioOTA(BaseModel):
    """Todos los campos son opcionales: lo que falte se inventa al azar."""
    referencia: str | None = Field(default=None, pattern=r"^[A-Z0-9-]{4,40}$",
                                   description="Repetir una referencia ya enviada demuestra que no se duplica")
    tipo: Literal["estándar", "superior", "suite"] | None = None
    fecha_entrada: date | None = None
    noches: int | None = Field(default=None, ge=1, le=30)
    personas: int | None = Field(default=None, ge=1, le=4)
    nombre_huesped: str | None = None
    correo_huesped: str | None = None
    firma_invalida: bool = Field(default=False, description="Envía el aviso con una firma falsa")
    fecha_vieja: bool = Field(default=False, description="Envía un aviso de hace una hora (repetición)")


@app.post("/ota/enviar", tags=["ota"])
def enviar_reserva_ota(envio: EnvioOTA | None = None):
    """Simula que un huésped reservó en la OTA: se envía el aviso firmado al hotel."""
    envio = envio or EnvioOTA()
    tipo = envio.tipo or random.choice(TIPOS)
    entrada = envio.fecha_entrada or date.today() + timedelta(days=random.randint(10, 90))
    nombre = envio.nombre_huesped or random.choice(NOMBRES)
    datos = {
        "referencia": envio.referencia or f"OTA-{secrets.token_hex(4).upper()}",
        "tipo": tipo,
        "fecha_entrada": str(entrada),
        "fecha_salida": str(entrada + timedelta(days=envio.noches or random.randint(2, 5))),
        "personas": envio.personas or random.randint(1, CAPACIDAD[tipo]),
        "nombre_huesped": nombre,
        "correo_huesped": envio.correo_huesped
        or nombre.lower().replace(" ", ".").translate(str.maketrans("áéíóú", "aeiou")) + "@viajero.test",
    }
    cuerpo = json.dumps(datos, ensure_ascii=False).encode()
    fecha = int(time.time()) - (3600 if envio.fecha_vieja else 0)
    firma = firmar(cuerpo, fecha, "secreto-equivocado" if envio.firma_invalida else OTA_SECRETO)

    # En producción el aviso entraría por Internet a https://<hotel>/api/integraciones/...
    # pasando por Nginx; en el prototipo va directo a la red interna de Docker.
    try:
        r = httpx.post(f"{API_URL}/api/integraciones/ota/reservas", content=cuerpo, timeout=15,
                       headers={"Content-Type": "application/json", "X-OTA-Fecha": str(fecha),
                                "X-OTA-Firma": firma})
        resultado = {"enviado": datos, "respuesta_hotel": {"codigo_http": r.status_code, "cuerpo": r.json()}}
    except (httpx.HTTPError, ValueError) as error:
        resultado = {"enviado": datos, "respuesta_hotel": {"error": str(error)}}
    enviadas.append(resultado)
    return resultado


# =====================================================================
# Panel y salud
# =====================================================================
@app.get("/panel", tags=["panel"])
def panel():
    """Todo lo que ha pasado por el simulador desde que arrancó."""
    return {
        "pasarela": list(cobros.values()),
        "hacienda": [c["respuesta"] for c in comprobantes.values()],
        "ota": enviadas,
    }


@app.get("/salud", tags=["panel"])
def salud():
    return {"estado": "ok"}
