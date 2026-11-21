"""Crea las cuentas de demostración, una por rol.

Uso (con los contenedores levantados):
    docker compose exec api python -m app.seed

La contraseña se toma de DEMO_PASSWORD (archivo .env), así no queda en
el repositorio. Si una cuenta ya existe, no se modifica.

Es idempotente: se puede ejecutar varias veces sin duplicar cuentas ni
cambiar las contraseñas de las que ya existen.

Para probar las reseñas hace falta una estadía ya cumplida, que el sistema no
permite crear (no se reserva en fechas pasadas). Este comando la crea para la
cuenta de cliente, con el código SOL-DEMO01:
    docker compose exec api python -m app.seed estadia
"""
import sys
from datetime import timedelta

from sqlalchemy import select

from . import config, seguridad
from .db import SesionLocal
from .modelos import Reserva, Usuario

# (nombre visible, correo para iniciar sesión, rol)
CUENTAS = [
    ("Gerencia Soluna", "gerencia@soluna.test", "gerente"),
    ("Recepción Soluna", "recepcion@soluna.test", "recepcionista"),
    ("Limpieza Soluna", "limpieza@soluna.test", "limpieza"),
    ("Mantenimiento Soluna", "mantenimiento@soluna.test", "mantenimiento"),
    ("Cliente de Prueba", "cliente@soluna.test", "cliente"),
]


def main() -> None:
    """Crea en una sola transacción las cuentas que falten."""
    contrasena = config.obligatorio("DEMO_PASSWORD")
    if len(contrasena) < 8:
        raise SystemExit("DEMO_PASSWORD debe tener al menos 8 caracteres")
    with SesionLocal() as sesion:
        for nombre, correo, rol in CUENTAS:
            if sesion.scalar(select(Usuario).where(Usuario.correo == correo)):
                print(f"  ya existe   {correo}")
                continue
            # Cada cuenta recibe su propio hash (con sal distinta) aunque la contraseña sea la misma
            sesion.add(Usuario(nombre=nombre, correo=correo, rol=rol,
                               hash_contrasena=seguridad.hashear(contrasena)))
            print(f"  creada      {correo} ({rol})")
        sesion.commit()


CODIGO_ESTADIA_DEMO = "SOL-DEMO01"


def estadia_demo() -> None:
    """Crea una estadía terminada hace una semana para cliente@soluna.test.

    Tres noches en la primera habitación estándar libre en esas fechas, con
    estado "finalizada" y el precio real de cada noche. Si ya existe, no la
    repite.
    """
    # Se importa aquí para no cargar las rutas cuando solo se crean cuentas
    from .routers.reservas import calcular_total, habitaciones_libres, hoy

    with SesionLocal() as sesion:
        if sesion.scalar(select(Reserva).where(Reserva.codigo == CODIGO_ESTADIA_DEMO)):
            print(f"  ya existe   estadía {CODIGO_ESTADIA_DEMO}")
            return
        cliente = sesion.scalar(select(Usuario).where(Usuario.correo == "cliente@soluna.test"))
        if cliente is None:
            raise SystemExit("Primero cree las cuentas: python -m app.seed")
        salida = hoy() - timedelta(days=7)
        entrada = salida - timedelta(days=3)
        habitacion = habitaciones_libres(sesion, entrada, salida, 2)[0]
        sesion.add(Reserva(
            codigo=CODIGO_ESTADIA_DEMO, habitacion_id=habitacion.id, cliente_id=cliente.id,
            nombre_huesped=cliente.nombre, correo_huesped=cliente.correo, personas=2,
            fecha_entrada=entrada, fecha_salida=salida, canal="web", estado="finalizada",
            total=calcular_total(sesion, habitacion.tipo_id, entrada, salida), creada_por=cliente.id))
        sesion.commit()
        print(f"  creada      estadía {CODIGO_ESTADIA_DEMO} del {entrada:%d/%m/%Y} al {salida:%d/%m/%Y} "
              f"(habitación {habitacion.numero}): ya se puede opinar sobre ella")


if __name__ == "__main__":
    # "python -m app.seed" crea las cuentas; con "estadia", además la estadía de demostración
    main()
    if "estadia" in sys.argv[1:]:
        estadia_demo()
