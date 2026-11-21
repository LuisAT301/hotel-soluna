"""Prueba de carga del Hotel Soluna con Locust (bloque 4).

Simula el tráfico de una temporada alta sobre el sistema publicado, ya sea el
prototipo en Docker (Nginx y réplicas de la API) o el despliegue en Vercel:

- Visitantes (la mayoría): abren la página, consultan el catálogo y buscan
  habitaciones libres para fechas al azar.
- Clientes: inician sesión una sola vez, revisan sus reservas y, de vez en
  cuando, reservan y cancelan de inmediato. Así la prueba ejerce las
  escrituras y la regla contra la sobreventa sin dejar datos ocupando
  habitaciones.
- Monitor: consulta /api/salud y anota qué réplica respondió, para mostrar
  cómo se reparte la carga.

No paga ni pide tokens de tarjeta: la pasarela tiene su propio límite por
dirección y no es lo que se quiere medir. Se ejecuta con carga.sh.
"""
import os
import random
from collections import Counter
from datetime import date, timedelta

from locust import HttpUser, between, events, task

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "SolunaDemo2026")
replicas: Counter = Counter()


def fechas_al_azar(noches: int = 2) -> tuple[date, date]:
    """Entrada entre 20 y 300 días en el futuro y salida ``noches`` después: reparte las reservas
    en el calendario.
    """
    entrada = date.today() + timedelta(days=random.randint(20, 300))
    return entrada, entrada + timedelta(days=noches)


class UsuarioSoluna(HttpUser):
    """Base común. Locust ignora por defecto las variables de entorno de
    requests; con trust_env se respetan REQUESTS_CA_BUNDLE (el certificado del
    prototipo en Docker) y, donde haga falta, el proxy de la red."""
    abstract = True

    def on_start(self):
        """Se ejecuta una vez al crear cada usuario simulado."""
        self.client.trust_env = True


class Visitante(UsuarioSoluna):
    """Navegación anónima: el grueso del tráfico de un sitio de hotel."""
    weight = 8
    wait_time = between(1, 4)

    @task(2)
    def pagina_de_inicio(self):
        """Carga la página del sitio (archivo estático)."""
        self.client.get("/", name="sitio: inicio")

    @task(3)
    def catalogo(self):
        """Consulta el catálogo público de tipos de habitación."""
        self.client.get("/api/tipos-habitacion", name="api: catálogo")

    @task(5)
    def disponibilidad(self):
        """Busca habitaciones libres para fechas y cantidad de personas al azar."""
        entrada, salida = fechas_al_azar(random.randint(1, 5))
        self.client.get("/api/disponibilidad", name="api: disponibilidad",
                        params={"entrada": entrada, "salida": salida, "personas": random.randint(1, 4)})


class Cliente(UsuarioSoluna):
    """Huésped con cuenta. Inicia sesión una vez: el inicio de sesión tiene
    límite por dirección en Nginx y usa Argon2id, que es costoso a propósito."""
    weight = 2
    wait_time = between(2, 6)

    def on_start(self):
        """Inicia sesión una sola vez; si no lo logra, sus tareas no hacen nada."""
        super().on_start()
        r = self.client.post("/api/auth/login", name="api: inicio de sesión",
                             data={"username": "cliente@soluna.test", "password": DEMO_PASSWORD})
        self.cabeceras = {"Authorization": f"Bearer {r.json()['access_token']}"} if r.ok else None

    @task(3)
    def mis_reservas(self):
        """Consulta la lista de reservas propias."""
        if self.cabeceras:
            self.client.get("/api/reservas", name="api: mis reservas", headers=self.cabeceras)

    @task(1)
    def reservar_y_cancelar(self):
        """Busca una habitación libre, la reserva y la cancela de inmediato.

        Si otro usuario simulado ganó la habitación (409), se cuenta como éxito:
        es la regla contra la sobreventa funcionando bajo carga.
        """
        if not self.cabeceras:
            return
        entrada, salida = fechas_al_azar()
        libres = self.client.get("/api/disponibilidad", name="api: disponibilidad",
                                 params={"entrada": entrada, "salida": salida, "personas": 2})
        if not libres.ok or not libres.json():
            return
        habitacion = random.choice(libres.json())["habitacion_id"]
        with self.client.post("/api/reservas", name="api: reservar", headers=self.cabeceras,
                              json={"habitacion_id": habitacion, "fecha_entrada": str(entrada),
                                    "fecha_salida": str(salida), "personas": 2},
                              catch_response=True) as r:
            if r.status_code == 409:
                # Otro usuario simulado ganó la habitación: la regla contra la
                # sobreventa funcionó, así que no cuenta como falla.
                r.success()
                return
            if r.status_code != 201:
                return
        self.client.post(f"/api/reservas/{r.json()['codigo']}/cancelar", name="api: cancelar",
                         headers=self.cabeceras)


class Monitor(UsuarioSoluna):
    """Pregunta a la API quién responde, para ver el balanceo entre réplicas."""
    weight = 1
    fixed_count = 1
    wait_time = between(0.5, 1)

    @task
    def salud(self):
        """Consulta la salud y cuenta qué réplica o instancia respondió."""
        r = self.client.get("/api/salud", name="api: salud")
        if r.ok:
            replicas[r.json().get("replica", "?")] += 1


@events.quitting.add_listener
def resumen(environment, **_):
    """Al terminar la prueba, imprime cuántas consultas atendió cada réplica, con su porcentaje."""
    if not replicas:
        return
    total = sum(replicas.values())
    print("\nSolicitudes a /api/salud por réplica (instancia que respondió):")
    for replica, n in replicas.most_common(10):
        print(f"  {replica:<24} {n:5d}  ({100 * n / total:4.1f} %)")
    if len(replicas) > 10:
        print(f"  ... y {len(replicas) - 10} instancias más")
