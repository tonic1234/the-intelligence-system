FROM python:3.12-slim

WORKDIR /app

# Las dependencias primero: así la imagen se cachea aunque cambie el código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El código vive en src/, así que el paquete se resuelve desde ahí. Lo dejo explícito
# en el entorno para no depender de un instalador ni de un truco de PYTHONPATH en cada comando.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# La API es el proceso por defecto; el worker se levanta con `python -m intelligence.worker`
# (en docker-compose son dos servicios del mismo código, que es como se corre en serio).
CMD ["uvicorn", "intelligence.main:app", "--host", "0.0.0.0", "--port", "8000"]
