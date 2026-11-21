"""Crea las cuentas de demostración, una por rol.

Uso (con los contenedores levantados):
    docker compose exec api python -m app.seed

La contraseña se toma de DEMO_PASSWORD (archivo .env), así no queda en
el repositorio. Si una cuenta ya existe, no se modifica.

Es idempotente: se puede ejecutar varias veces sin duplicar cuentas ni
cambiar las contraseñas de las que ya existen.
"""
from sqlalchemy import select

from . import config, seguridad
from .db import SesionLocal
from .modelos import Usuario

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


if __name__ == "__main__":
    main()
