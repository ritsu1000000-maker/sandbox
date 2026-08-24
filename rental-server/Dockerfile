FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py runner.py server.py gunicorn.conf.py ./
COPY rental_core ./rental_core
COPY templates ./templates
COPY static ./static

EXPOSE 8080 9000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
