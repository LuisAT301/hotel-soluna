"""Crea las cuentas de demostración, una por rol.

Uso (con los contenedores levantados):
    docker compose exec api python -m app.seed

La contraseña se toma de DEMO_PASSWORD (archivo .env), así no queda en
el repositorio. Si una cuenta ya existe, no se modifica.
"""
from sqlalchemy import select

from . import config, seguridad
from .db import SesionLocal
from .modelos import Usuario

CUENTAS = [
    ("Gerencia Soluna", "gerencia@soluna.test", "gerente"),
    ("Recepción Soluna", "recepcion@soluna.test", "recepcionista"),
    ("Limpieza Soluna", "limpieza@soluna.test", "limpieza"),
    ("Mantenimiento Soluna", "mantenimiento@soluna.test", "mantenimiento"),
    ("Cliente de Prueba", "cliente@soluna.test", "cliente"),
]


def main() -> None:
    contrasena = config.obligatorio("DEMO_PASSWORD")
    if len(contrasena) < 8:
        raise SystemExit("DEMO_PASSWORD debe tener al menos 8 caracteres")
    with SesionLocal() as sesion:
        for nombre, correo, rol in CUENTAS:
            if sesion.scalar(select(Usuario).where(Usuario.correo == correo)):
                print(f"  ya existe   {correo}")
                continue
            sesion.add(Usuario(nombre=nombre, correo=correo, rol=rol,
                               hash_contrasena=seguridad.hashear(contrasena)))
            print(f"  creada      {correo} ({rol})")
        sesion.commit()


if __name__ == "__main__":
    main()
