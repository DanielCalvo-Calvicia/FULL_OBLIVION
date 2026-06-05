#!/usr/bin/env bash
set -euo pipefail

scenario="${1:-full}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$scenario" in
  full)
    profiles=(full)
    ;;
  brain-remote)
    profiles=(brain)
    ;;
  windows-audio)
    profiles=(brain stt tts)
    export BRAIN_MICROPHONE_BASE_URL="${BRAIN_MICROPHONE_BASE_URL:-http://host.docker.internal:8000}"
    export BRAIN_SPEAKER_BASE_URL="${BRAIN_SPEAKER_BASE_URL:-http://host.docker.internal:8003}"
    export BRAIN_STARTUP_PREFLIGHT_ENABLED="${BRAIN_STARTUP_PREFLIGHT_ENABLED:-false}"
    ;;
  windows-speaker)
    profiles=(brain microphone stt tts)
    export BRAIN_SPEAKER_BASE_URL="${BRAIN_SPEAKER_BASE_URL:-http://host.docker.internal:8003}"
    export BRAIN_STARTUP_PREFLIGHT_ENABLED="${BRAIN_STARTUP_PREFLIGHT_ENABLED:-false}"
    ;;
  software-only)
    profiles=(stt tts)
    ;;
  audio-only)
    profiles=(audio)
    ;;
  raspberry-services)
    profiles=(stt tts speaker)
    ;;
  *)
    echo "Unknown scenario: $scenario"
    echo "Valid scenarios: full, brain-remote, windows-audio, windows-speaker, software-only, audio-only, raspberry-services"
    exit 1
    ;;
esac

compose_args=()
for profile in "${profiles[@]}"; do
  compose_args+=(--profile "$profile")
done

echo "FULL_OBLIVION start from scratch"
echo "Scenario: $scenario"
echo "Profiles: ${profiles[*]}"
if [[ "$scenario" == "windows-audio" ]]; then
  echo "BRAIN_MICROPHONE_BASE_URL=$BRAIN_MICROPHONE_BASE_URL"
  echo "BRAIN_SPEAKER_BASE_URL=$BRAIN_SPEAKER_BASE_URL"
  echo "BRAIN_STARTUP_PREFLIGHT_ENABLED=$BRAIN_STARTUP_PREFLIGHT_ENABLED"
fi
if [[ "$scenario" == "windows-speaker" ]]; then
  echo "BRAIN_SPEAKER_BASE_URL=$BRAIN_SPEAKER_BASE_URL"
  echo "BRAIN_STARTUP_PREFLIGHT_ENABLED=$BRAIN_STARTUP_PREFLIGHT_ENABLED"
fi

cd "$root"

echo
echo "Step 1/2: bootstrap repositories and generated Dockerfiles..."
./scripts/repo/bootstrap.sh --skip-build

echo
echo "Step 2/2: build and start containers..."
docker compose "${compose_args[@]}" up -d --build
docker compose "${compose_args[@]}" ps

echo
echo "Started scenario: $scenario"
