#!/usr/bin/env bash
set -euo pipefail

rebuild=0
if [[ "${1:-}" == "--rebuild" ]]; then
  rebuild=1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
repos_dir="$root/repos"
dockerfiles_dir="$root/dockerfiles"

services=(
  "brain_microservice|brain.Dockerfile"
  "microphone_microservice|microphone.Dockerfile"
  "stt_microservice|stt.Dockerfile"
  "tts_microservice|tts.Dockerfile"
  "speaker_microservice|speaker.Dockerfile"
)

for item in "${services[@]}"; do
  IFS='|' read -r name dockerfile <<< "$item"
  repo="$repos_dir/$name"
  if [[ ! -d "$repo" ]]; then
    echo "Missing repo, skipping update: $name"
    continue
  fi

  echo "Updating $name..."
  rm -f "$repo/Dockerfile" "$repo/.dockerignore"
  (cd "$repo" && git pull --ff-only)
  cp "$dockerfiles_dir/$dockerfile" "$repo/Dockerfile"
  cp "$dockerfiles_dir/.dockerignore" "$repo/.dockerignore"
done

if (( rebuild == 1 )); then
  (cd "$root" && docker compose --profile full build)
fi

echo "Update complete."
