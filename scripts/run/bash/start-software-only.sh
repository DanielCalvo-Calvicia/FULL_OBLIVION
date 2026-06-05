#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION software-only services: stt, tts..."
docker compose --profile stt --profile tts up -d
docker compose --profile stt --profile tts ps

echo "Started software-only services."
echo "STT health: curl http://localhost:8001/health"
echo "TTS health: curl http://localhost:8002/health"
