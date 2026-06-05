#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cat <<'EOF'
Simulation: full local Docker Compose stack

Use when all five services run as containers on the same Linux Docker host:
- brain
- microphone
- stt
- tts
- speaker

Expected command:
  docker compose --profile full up -d

Expected health checks:
  curl http://localhost:7999/health
  curl http://localhost:8000/health
  curl http://localhost:8001/health
  curl http://localhost:8002/health
  curl http://localhost:8003/health
  curl http://localhost:7999/integrations/health

Notes:
- Linux audio passthrough may be required for microphone/speaker.
- OPENAI_API_KEY is required when STT_ENGINE=openai or TTS_ADAPTER=openai.
EOF

echo
echo "Rendered services:"
(cd "$root" && docker compose --profile full config --services)
