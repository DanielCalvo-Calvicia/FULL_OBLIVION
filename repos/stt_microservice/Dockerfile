FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
# Keep Pydantic deterministic for Python 3.12 builds. The service requirements
# only specify a lower bound, and latest resolver paths can conflict.
RUN pip install --no-cache-dir "pydantic==2.10.6" "pydantic-core==2.27.2"
RUN if [ -f requirements.linux.txt ]; then \
        pip install --no-cache-dir -r requirements.linux.txt; \
    else \
        pip install --no-cache-dir -r requirements.windows.txt; \
    fi

COPY . .

EXPOSE 8001
CMD ["python", "main.py"]
