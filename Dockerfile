FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_DEBUG=0 \
    HOST=0.0.0.0 \
    PORT=5000 \
    HOLLY_IDENTITY_STORE_PATH=/data/identity_store.json \
    HOLLY_FACE_VERIFY_STORE_PATH=/data/face_verify_store.json

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY identity_store.py ./
COPY plugin_system.py ./
COPY plugins ./plugins
COPY prompts ./prompts
COPY templates ./templates
COPY static ./static

RUN groupadd --gid 10001 holly \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin holly \
    && mkdir -p /data \
    && chown -R holly:holly /app /data

USER holly

EXPOSE 5000

VOLUME ["/data"]

CMD ["python", "main.py"]
