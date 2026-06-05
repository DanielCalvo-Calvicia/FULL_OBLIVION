#!/usr/bin/env bash
set -euo pipefail

skip_build=0
if [[ "${1:-}" == "--skip-build" ]]; then
  skip_build=1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
repos_dir="$root/repos"
dockerfiles_dir="$root/dockerfiles"

mkdir -p "$repos_dir"

services=(
  "brain_microservice|https://github.com/DanielCalvo-Calvicia/brain_microservice.git|main|brain.Dockerfile"
  "microphone_microservice|https://github.com/DanielCalvo-Calvicia/microphone_microservice.git|main|microphone.Dockerfile"
  "stt_microservice|https://github.com/DanielCalvo-Calvicia/stt_microservice.git|main|stt.Dockerfile"
  "tts_microservice|https://github.com/DanielCalvo-Calvicia/tts_microservice.git|main|tts.Dockerfile"
  "speaker_microservice|https://github.com/DanielCalvo-Calvicia/speaker_microservice.git|main|speaker.Dockerfile"
)

failures=()
for item in "${services[@]}"; do
  IFS='|' read -r name git_url branch dockerfile <<< "$item"
  target="$repos_dir/$name"
  if [[ ! -d "$target" ]]; then
    echo "Cloning $name..."
    if ! git clone --branch "$branch" "$git_url" "$target"; then
      failures+=("$name: clone failed")
      continue
    fi
  else
    echo "Repository exists, updating $name to $branch..."
    if [[ -n "$(git -C "$target" status --porcelain -- . ':(exclude)Dockerfile' ':(exclude).dockerignore')" ]]; then
      echo "Local changes found in $name; skipping git update."
    else
      git -C "$target" fetch origin "$branch"
      git -C "$target" checkout "$branch"
      git -C "$target" pull --ff-only origin "$branch"
    fi
  fi

  cp "$dockerfiles_dir/$dockerfile" "$target/Dockerfile"
  cp "$dockerfiles_dir/.dockerignore" "$target/.dockerignore"
done

if [[ ! -f "$root/.env" ]]; then
  cp "$root/.env.example" "$root/.env"
  echo "Created .env from .env.example. Review it before starting services."
fi

if (( ${#failures[@]} > 0 )); then
  echo "Bootstrap completed with failures:"
  printf ' - %s\n' "${failures[@]}"
  exit 1
fi

if (( skip_build == 0 )); then
  (cd "$root" && docker compose --profile full build)
fi

echo "Bootstrap complete."
