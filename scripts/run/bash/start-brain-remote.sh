#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION brain container with configured remote service URLs..."
echo "MICROPHONE_BASE_URL=${MICROPHONE_BASE_URL:-from .env or compose default}"
echo "STT_BASE_URL=${STT_BASE_URL:-from .env or compose default}"
echo "TTS_BASE_URL=${TTS_BASE_URL:-from .env or compose default}"
echo "SPEAKER_BASE_URL=${SPEAKER_BASE_URL:-from .env or compose default}"

docker compose --profile brain up -d
docker compose --profile brain ps

echo "Started brain."
echo "System health: curl http://localhost:7999/integrations/health"
