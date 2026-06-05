#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION audio-only services: microphone, speaker..."
docker compose --profile audio up -d
docker compose --profile audio ps

echo "Started audio-only services."
echo "Microphone health: curl http://localhost:8000/health"
echo "Speaker health: curl http://localhost:8003/health"
