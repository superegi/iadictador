FROM python:3.12-slim

# IAD_AUDIO_FIRST_FFMPEG_V1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code:/code/app

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r /code/requirements.txt \
    && python -m pip install --no-cache-dir itsdangerous==2.2.0 \
    && python - <<'PY'
import itsdangerous
print("BUILD CHECK: itsdangerous OK")
PY

COPY . /code

RUN mkdir -p /data/uploads_iadictador

EXPOSE 8015

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8015"]
