FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        fonts-noto-cjk \
        git \
        libreoffice \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /app/requirements.txt

COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
COPY backend/main.py /app/main.py
COPY backend/worker.py /app/worker.py

RUN mkdir -p \
    /app/storage/uploads \
    /app/storage/derived \
    /app/storage/page_index \
    /app/storage/mineru_output \
    /app/models \
    /app/logs

EXPOSE 8888

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"]
