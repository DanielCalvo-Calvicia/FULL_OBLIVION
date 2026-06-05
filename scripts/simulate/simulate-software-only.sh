#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cat <<'EOF'
Simulation: software-only STT/TTS containers

Use when no audio hardware should be used by Docker.

Services:
- stt
- tts

Expected command:
  docker compose --profile stt --profile tts up -d

Expected health checks:
  curl http://localhost:8001/health
  curl http://localhost:8001/available
  curl http://localhost:8002/health
  curl http://localhost:8002/available

Notes:
- OPENAI_API_KEY is required for OpenAI modes.
- STT local mode may download faster-whisper model files into stt-model-cache.
EOF

echo
echo "Rendered services:"
(cd "$root" && docker compose --profile stt --profile tts config --services)
