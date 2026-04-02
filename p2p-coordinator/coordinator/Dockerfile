FROM python:3.10-slim

WORKDIR /app

COPY coordinator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
COPY coordinator/ /app/coordinator/

# Set Python Path so it can find common
ENV PYTHONPATH=/app

CMD ["uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]
