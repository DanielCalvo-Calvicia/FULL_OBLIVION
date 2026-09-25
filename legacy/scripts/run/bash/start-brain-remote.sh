#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION brain container with configured remote service URLs..."
echo "BRAIN_MICROPHONE_BASE_URL=${BRAIN_MICROPHONE_BASE_URL:-from root .env or compose default}"
echo "BRAIN_STT_BASE_URL=${BRAIN_STT_BASE_URL:-from root .env or compose default}"
echo "BRAIN_TTS_BASE_URL=${BRAIN_TTS_BASE_URL:-from root .env or compose default}"
echo "BRAIN_SPEAKER_BASE_URL=${BRAIN_SPEAKER_BASE_URL:-from root .env or compose default}"

docker compose --profile brain up -d
docker compose --profile brain ps

echo "Started brain."
echo "System health: curl http://localhost:7999/integrations/health"
