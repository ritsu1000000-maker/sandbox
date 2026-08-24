FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py runner.py ./
COPY templates ./templates

EXPOSE 8080 9000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "app:app"]
