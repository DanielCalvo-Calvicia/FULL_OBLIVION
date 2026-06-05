FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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

# The current microphone service hardcodes localhost. Patch it so other
# containers can reach this service over the Compose network.
RUN python - <<'PY'
from pathlib import Path

path = Path("composition_root/setup/setup.py")
text = path.read_text()
text = text.replace('host="127.0.0.1", port=8000', 'host="0.0.0.0", port=8000')
text = text.replace("host='127.0.0.1', port=8000", "host='0.0.0.0', port=8000")
path.write_text(text)
PY

EXPOSE 8000
CMD ["python", "main.py"]
