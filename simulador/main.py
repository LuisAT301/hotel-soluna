"""Punto de entrada para Vercel, que busca la aplicación en main.py.
En Docker se sigue arrancando con: uvicorn simulador:app"""
from simulador import app  # noqa: F401
