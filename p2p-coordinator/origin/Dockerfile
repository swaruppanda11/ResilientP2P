FROM python:3.10-slim

WORKDIR /app

COPY origin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
COPY origin/ /app/origin/

ENV PYTHONPATH=/app

CMD ["uvicorn", "origin.main:app", "--host", "0.0.0.0", "--port", "8001"]
