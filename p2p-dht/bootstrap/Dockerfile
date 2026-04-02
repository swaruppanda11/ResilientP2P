FROM python:3.10-slim

WORKDIR /app

COPY bootstrap/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bootstrap/ /app/bootstrap/

CMD ["python", "-m", "bootstrap.main"]
