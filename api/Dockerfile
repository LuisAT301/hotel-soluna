# Imagen de la API del Hotel Soluna
# python:3.13-slim existe para Intel/AMD (amd64) y Apple Silicon (arm64)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Primero las dependencias: Docker reutiliza esta capa si solo cambia el código
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# La API corre con un usuario sin privilegios; el código pertenece a root,
# así que el proceso no puede modificarlo aunque alguien lo comprometa.
RUN useradd --system --uid 10001 --no-create-home api
USER api

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
