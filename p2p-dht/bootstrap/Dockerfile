FROM python:3.10-slim

WORKDIR /app

COPY bootstrap/requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY bootstrap/ /app/bootstrap/

CMD ["python", "-m", "bootstrap.main"]
