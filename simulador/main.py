"""Punto de entrada para Vercel, que busca la aplicación en main.py.
En Docker se sigue arrancando con: uvicorn simulador:app

Solo importa el objeto ``app`` de simulador.py; toda la lógica vive allí.
"""
from simulador import app  # noqa: F401
