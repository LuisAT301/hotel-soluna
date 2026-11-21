"""Dónde guarda el simulador lo que recibe: en memoria (Docker) o en PostgreSQL (Vercel).

En Docker corre una sola copia del simulador y la memoria alcanza. En Vercel
cada solicitud puede llegar a una instancia distinta de la función, así que un
token creado en una debe poder usarse en otra: ahí el estado vive en el esquema
"simulador" de Supabase, separado de los datos del hotel.

Ninguna de las dos versiones guarda el número completo de la tarjeta: al crear
el token se guardan solo la marca, los últimos cuatro dígitos y el resultado
que tendrá el cobro, como haría una pasarela real.

Las dos clases ofrecen exactamente los mismos métodos (la misma interfaz),
así que simulador.py usa una u otra sin saber cuál es:
  tokens        guardar_token, tomar_token
  idempotencia  obtener_idempotencia, guardar_idempotencia
  cobros        guardar_cobro, obtener_cobro, marcar_reembolso, listar_cobros
  Hacienda      obtener_comprobante, guardar_comprobante, listar_respuestas_hacienda
  OTA           guardar_aviso, listar_avisos
"""
import json
import time
from datetime import datetime, timedelta, timezone


class Memoria:
    """Estado en diccionarios de Python: rápido y suficiente para una sola copia (Docker)."""

    def __init__(self) -> None:
        self.tokens: dict[str, dict] = {}
        self.cobros: dict[str, dict] = {}
        self.idempotencia: dict[str, dict] = {}
        self.comprobantes: dict[str, dict] = {}
        self.avisos: list[dict] = []

    # --- tokens de un solo uso
    def guardar_token(self, token: str, datos: dict, minutos: int) -> None:
        """Guarda los datos del token con su hora de vencimiento (reloj monotónico, inmune a cambios de hora)."""
        self.tokens[token] = {**datos, "_vence": time.monotonic() + minutos * 60}

    def tomar_token(self, token: str) -> dict | None:
        """Saca el token (deja de existir) y devuelve sus datos, o None si no existe o venció."""
        datos = self.tokens.pop(token, None)
        if datos is None or datos["_vence"] < time.monotonic():
            return None
        return {k: v for k, v in datos.items() if k != "_vence"}

    # --- idempotencia de cobros
    def obtener_idempotencia(self, llave: str) -> dict | None:
        return self.idempotencia.get(llave)

    def guardar_idempotencia(self, llave: str, huella: str, respuesta: dict) -> None:
        """Guarda la respuesta de la llave solo si no había una: la primera respuesta es la definitiva."""
        self.idempotencia.setdefault(llave, {"huella": huella, "respuesta": respuesta})

    # --- cobros y reembolsos
    def guardar_cobro(self, cobro: dict) -> None:
        self.cobros[cobro["transaccion"]] = dict(cobro)

    def obtener_cobro(self, transaccion: str) -> dict | None:
        cobro = self.cobros.get(transaccion)
        return dict(cobro) if cobro else None

    def marcar_reembolso(self, transaccion: str, reembolso: str) -> bool:
        """Anota el reembolso solo si el cobro no tenía uno: evita reembolsar dos veces."""
        cobro = self.cobros.get(transaccion)
        if cobro is None or cobro.get("reembolso"):
            return False
        cobro["reembolso"] = reembolso
        return True

    def listar_cobros(self) -> list[dict]:
        return list(self.cobros.values())

    # --- Hacienda
    def obtener_comprobante(self, clave: str) -> dict | None:
        return self.comprobantes.get(clave)

    def guardar_comprobante(self, clave: str, comprobante: dict, respuesta: dict) -> None:
        self.comprobantes.setdefault(clave, {"comprobante": comprobante, "respuesta": respuesta})

    def listar_respuestas_hacienda(self) -> list[dict]:
        return [c["respuesta"] for c in self.comprobantes.values()]

    # --- OTA
    def guardar_aviso(self, resultado: dict) -> None:
        self.avisos.append(resultado)

    def listar_avisos(self) -> list[dict]:
        return list(self.avisos)


class BaseDatos:
    """La misma interfaz sobre PostgreSQL. Cada operación abre y cierra su conexión,
    porque en Vercel se usa el pooler de Supabase en modo transacción.

    Las operaciones que deben ser únicas se resuelven con una sola sentencia
    SQL atómica, de modo que dos instancias de la función que atienden
    solicitudes simultáneas no puedan usar dos veces el mismo token ni
    reembolsar dos veces el mismo cobro.
    """

    def __init__(self, **conexion) -> None:
        import psycopg  # solo hace falta en este modo
        from psycopg.types.json import Jsonb
        self._psycopg = psycopg
        self._Jsonb = Jsonb
        self._conexion = conexion

    def _ejecutar(self, sql: str, parametros: tuple = (), una: bool = False, todas: bool = False):
        """Ejecuta una sentencia en su propia conexión (autocommit).

        Devuelve una fila (``una``), todas las filas (``todas``) o la cantidad
        de filas afectadas. Los valores van como parámetros (%s), nunca
        pegados al texto SQL, lo que impide la inyección de SQL.
        """
        # prepare_threshold=None: el modo transacción del pooler no admite sentencias preparadas
        with self._psycopg.connect(**self._conexion, autocommit=True, prepare_threshold=None) as c:
            cursor = c.execute(sql, parametros)
            if una:
                return cursor.fetchone()
            if todas:
                return cursor.fetchall()
            return cursor.rowcount

    # --- tokens de un solo uso
    def guardar_token(self, token: str, datos: dict, minutos: int) -> None:
        vence = datetime.now(timezone.utc) + timedelta(minutes=minutos)
        # De paso se limpian los tokens vencidos, para que la tabla no crezca sin fin
        self._ejecutar("DELETE FROM simulador.tokens WHERE vence < now()")
        self._ejecutar("INSERT INTO simulador.tokens (token, datos, vence) VALUES (%s, %s, %s)",
                       (token, self._Jsonb(datos), vence))

    def tomar_token(self, token: str) -> dict | None:
        # DELETE ... RETURNING es atómico: dos cobros simultáneos no pueden usar el mismo token
        fila = self._ejecutar("DELETE FROM simulador.tokens WHERE token = %s AND vence >= now() RETURNING datos",
                              (token,), una=True)
        return fila[0] if fila else None

    # --- idempotencia de cobros
    def obtener_idempotencia(self, llave: str) -> dict | None:
        fila = self._ejecutar("SELECT huella, respuesta FROM simulador.idempotencia WHERE llave = %s",
                              (llave,), una=True)
        return {"huella": fila[0], "respuesta": fila[1]} if fila else None

    def guardar_idempotencia(self, llave: str, huella: str, respuesta: dict) -> None:
        self._ejecutar("INSERT INTO simulador.idempotencia (llave, huella, respuesta) VALUES (%s, %s, %s) "
                       "ON CONFLICT (llave) DO NOTHING", (llave, huella, self._Jsonb(respuesta)))

    # --- cobros y reembolsos
    def guardar_cobro(self, cobro: dict) -> None:
        datos = {k: v for k, v in cobro.items() if k != "reembolso"}
        self._ejecutar("INSERT INTO simulador.cobros (transaccion, datos) VALUES (%s, %s) "
                       "ON CONFLICT (transaccion) DO NOTHING", (cobro["transaccion"], self._Jsonb(datos)))

    def obtener_cobro(self, transaccion: str) -> dict | None:
        fila = self._ejecutar("SELECT datos, reembolso FROM simulador.cobros WHERE transaccion = %s",
                              (transaccion,), una=True)
        if not fila:
            return None
        return {**fila[0], **({"reembolso": fila[1]} if fila[1] else {})}

    def marcar_reembolso(self, transaccion: str, reembolso: str) -> bool:
        filas = self._ejecutar("UPDATE simulador.cobros SET reembolso = %s "
                               "WHERE transaccion = %s AND reembolso IS NULL", (reembolso, transaccion))
        return filas == 1

    def listar_cobros(self) -> list[dict]:
        filas = self._ejecutar("SELECT datos, reembolso FROM simulador.cobros ORDER BY creado_en", todas=True)
        return [{**d, **({"reembolso": r} if r else {})} for d, r in filas]

    # --- Hacienda
    def obtener_comprobante(self, clave: str) -> dict | None:
        fila = self._ejecutar("SELECT comprobante, respuesta FROM simulador.comprobantes WHERE clave = %s",
                              (clave,), una=True)
        return {"comprobante": fila[0], "respuesta": fila[1]} if fila else None

    def guardar_comprobante(self, clave: str, comprobante: dict, respuesta: dict) -> None:
        """Guarda el comprobante; json.dumps(default=str) convierte fechas y decimales a texto para JSONB."""
        self._ejecutar("INSERT INTO simulador.comprobantes (clave, comprobante, respuesta) VALUES (%s, %s, %s) "
                       "ON CONFLICT (clave) DO NOTHING",
                       (clave, self._Jsonb(json.loads(json.dumps(comprobante, default=str))), self._Jsonb(respuesta)))

    def listar_respuestas_hacienda(self) -> list[dict]:
        return [f[0] for f in self._ejecutar("SELECT respuesta FROM simulador.comprobantes ORDER BY creado_en",
                                             todas=True)]

    # --- OTA
    def guardar_aviso(self, resultado: dict) -> None:
        self._ejecutar("INSERT INTO simulador.avisos_ota (resultado) VALUES (%s)", (self._Jsonb(resultado),))

    def listar_avisos(self) -> list[dict]:
        return [f[0] for f in self._ejecutar("SELECT resultado FROM simulador.avisos_ota ORDER BY id", todas=True)]
