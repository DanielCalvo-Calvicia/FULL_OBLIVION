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

# The microphone service may hardcode a local bind in older checkouts. Patch it
# so native/container runs can use SERVICE_HOST/SERVICE_PORT or the root
# MICROPHONE_* aliases.
RUN python - <<'PY'
from pathlib import Path

path = Path("composition_root/setup/setup.py")
text = path.read_text()
if "import os" not in text:
    text = text.replace("import uvicorn", "import os\n\nimport uvicorn")
host_expr = 'os.getenv("SERVICE_HOST") or os.getenv("MICROPHONE_SERVICE_HOST", "0.0.0.0")'
port_expr = 'int(os.getenv("SERVICE_PORT") or os.getenv("MICROPHONE_SERVICE_PORT", "8000"))'
for host in ("127.0.0.1", "0.0.0.0"):
    text = text.replace(
        f'uvicorn.Config(app, host="{host}", port=8000)',
        f"uvicorn.Config(app, host={host_expr}, port={port_expr})",
    )
    text = text.replace(
        f"uvicorn.Config(app, host='{host}', port=8000)",
        f"uvicorn.Config(app, host={host_expr}, port={port_expr})",
    )
path.write_text(text)
PY

EXPOSE 8000
CMD ["python", "main.py"]
