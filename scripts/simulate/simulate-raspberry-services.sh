#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

pi_host="${PI_HOST:-raspberrypi.local}"

cat <<EOF
Simulation: Raspberry Pi runs STT, TTS, and speaker

Use when microphone is elsewhere, and the Raspberry Pi owns processing/playback.

Services on this host:
- stt
- tts
- speaker

Expected command on the Raspberry Pi:
  docker compose --profile stt --profile tts --profile speaker up -d

Expected URLs for brain on another host:
  STT_BASE_URL=http://$pi_host:8001
  TTS_BASE_URL=http://$pi_host:8002
  SPEAKER_BASE_URL=http://$pi_host:8003

Expected health checks from brain host:
  curl http://$pi_host:8001/health
  curl http://$pi_host:8002/health
  curl http://$pi_host:8003/health

Notes:
- Speaker playback needs Raspberry Pi audio configured and exposed to the speaker container.
- Local STT on a Pi may be slow; OpenAI STT is usually lighter on-device.
EOF

echo
echo "Rendered services:"
(cd "$root" && docker compose --profile stt --profile tts --profile speaker config --services)
