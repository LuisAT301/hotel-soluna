# Simulador de servicios externos (pasarela de pago, Hacienda y OTA)
FROM python:3.13-slim

# Mismas opciones que la imagen de la API: sin .pyc, registros sin búfer, pip sin caché
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY simulador.py almacen.py ./

# Usuario sin privilegios propio del simulador (distinto del de la API)
RUN useradd --system --uid 10002 --no-create-home simulador
USER simulador

EXPOSE 8000

# Nginx espera a que el simulador esté sano antes de arrancar (depends_on en Compose)
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=2).status == 200 else 1)"

# Una sola copia: el simulador guarda su estado en memoria
CMD ["uvicorn", "simulador:app", "--host", "0.0.0.0", "--port", "8000"]
