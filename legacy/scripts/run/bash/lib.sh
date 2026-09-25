#!/usr/bin/env bash

required_repos=(
  brain_microservice
  microphone_microservice
  stt_microservice
  tts_microservice
  speaker_microservice
)

ensure_repos() {
  local root="$1"
  local missing=()

  for repo in "${required_repos[@]}"; do
    if [[ ! -d "$root/repos/$repo" ]]; then
      missing+=("$repo")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Missing cloned service repositories:"
    printf ' - repos/%s\n' "${missing[@]}"
    echo
    echo "Run bootstrap first:"
    echo "  ./scripts/repo/bootstrap.sh"
    echo
    echo "Or, on Windows PowerShell:"
    echo "  .\\scripts\\repo\\bootstrap.ps1"
    exit 1
  fi
}
