FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8003

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libportaudio2 \
        portaudio19-dev \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
RUN if [ -f requirements.linux.txt ]; then \
        pip install --no-cache-dir -r requirements.linux.txt; \
    else \
        pip install --no-cache-dir -r requirements.windows.txt; \
    fi

COPY . .

EXPOSE 8003
CMD ["python", "main.py"]
