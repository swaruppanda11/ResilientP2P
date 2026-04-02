FROM python:3.10-slim

WORKDIR /app

COPY peer/requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
COPY dht/ /app/dht/
COPY peer/ /app/peer/

ENV PYTHONPATH=/app

CMD ["uvicorn", "peer.main:app", "--host", "0.0.0.0", "--port", "7000"]
