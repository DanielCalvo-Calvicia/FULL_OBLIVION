#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

services=("$@")
if (( ${#services[@]} == 0 )); then
  services=(brain microphone stt tts speaker)
fi

(cd "$root" && docker compose build --no-cache "${services[@]}")
(cd "$root" && docker compose --profile full up -d "${services[@]}")

echo "Rebuild complete for: ${services[*]}"
