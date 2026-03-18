FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_DEBUG=0 \
    HOST=0.0.0.0 \
    PORT=5000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY plugin_system.py ./
COPY plugins ./plugins
COPY templates ./templates
COPY static ./static

RUN useradd --create-home --shell /usr/sbin/nologin holly \
    && chown -R holly:holly /app

USER holly

EXPOSE 5000

CMD ["python", "main.py"]
