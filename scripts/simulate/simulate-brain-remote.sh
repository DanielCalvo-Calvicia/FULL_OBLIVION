#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mic_url="${MICROPHONE_BASE_URL:-http://192.168.1.20:8000}"
stt_url="${STT_BASE_URL:-http://192.168.1.30:8001}"
tts_url="${TTS_BASE_URL:-http://192.168.1.30:8002}"
speaker_url="${SPEAKER_BASE_URL:-http://192.168.1.31:8003}"

cat <<EOF
Simulation: brain container with remote services

Use when brain runs in Docker, but dependencies are already running on LAN hosts.

Example dependency URLs:
  MICROPHONE_BASE_URL=$mic_url
  STT_BASE_URL=$stt_url
  TTS_BASE_URL=$tts_url
  SPEAKER_BASE_URL=$speaker_url

Expected command:
  MICROPHONE_BASE_URL=$mic_url \\
  STT_BASE_URL=$stt_url \\
  TTS_BASE_URL=$tts_url \\
  SPEAKER_BASE_URL=$speaker_url \\
  docker compose --profile brain up -d

Expected health checks from the brain host:
  curl $mic_url/health
  curl $stt_url/health
  curl $tts_url/health
  curl $speaker_url/health
  curl http://localhost:7999/integrations/health

Notes:
- Remote services must bind to LAN-reachable addresses, not only 127.0.0.1.
- The native Windows microphone service may need a bind-address source/config change.
EOF

echo
echo "Rendered services with these URLs:"
(
  cd "$root"
  MICROPHONE_BASE_URL="$mic_url" \
  STT_BASE_URL="$stt_url" \
  TTS_BASE_URL="$tts_url" \
  SPEAKER_BASE_URL="$speaker_url" \
  docker compose --profile brain config --services
)
