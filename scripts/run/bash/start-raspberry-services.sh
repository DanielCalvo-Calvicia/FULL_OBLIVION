#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION Raspberry Pi service set: stt, tts, speaker..."
docker compose --profile stt --profile tts --profile speaker up -d
docker compose --profile stt --profile tts --profile speaker ps

echo "Started Raspberry Pi service set."
echo "STT health: curl http://localhost:8001/health"
echo "TTS health: curl http://localhost:8002/health"
echo "Speaker health: curl http://localhost:8003/health"
