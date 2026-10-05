# Generic image for any OBLIVION service, built by `oblivion` from a prepared build context:
#   <service tree>  requirements.docker.txt (no "-e ../sibling" lines)  libs/ (wheels of shared libraries)
# It is never built by hand: the CLI creates the context and passes the apt packages of the service.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG APT_PACKAGES=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN if [ -n "$APT_PACKAGES" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ca-certificates $APT_PACKAGES \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY . /app
# ./vendor/<wheel> lines (bundled contracts) resolve from /app
RUN pip install --no-cache-dir -r requirements.docker.txt \
    && if ls /app/libs/*.whl >/dev/null 2>&1; then pip install --no-cache-dir /app/libs/*.whl; fi

# The service's `prepare` script (config/catalogue.toml), e.g. tts' Piper voice. It may fail (no network while building):
# the service then starts on its fallback and says so in its log.
ARG PREPARE=""
RUN if [ -n "$PREPARE" ]; then python $PREPARE || echo "warning: prepare step failed: $PREPARE"; fi

# The port is set by SERVICE_PORT in the --env-file; the CLI publishes it on the chosen address.
CMD ["python", "main.py"]
