#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cat <<'EOF'
Simulation: audio-only containers

Use when this host owns both microphone and speaker hardware.

Services:
- microphone
- speaker

Expected command:
  docker compose --profile audio up -d

Expected health checks:
  curl http://localhost:8000/health
  curl http://localhost:8003/health

Notes:
- On Linux, uncomment/tune /dev/snd or PulseAudio/PipeWire mounts in docker-compose.yml.
- On Windows/macOS Docker Desktop, run these services natively instead of in containers.
EOF

echo
echo "Rendered services:"
(cd "$root" && docker compose --profile audio config --services)
