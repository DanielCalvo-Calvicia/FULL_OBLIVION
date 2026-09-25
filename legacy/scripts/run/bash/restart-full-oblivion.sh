#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

profiles=("$@")
if (( ${#profiles[@]} == 0 )); then
  profiles=(full)
fi

args=()
for profile in "${profiles[@]}"; do
  args+=(--profile "$profile")
done

echo "Restarting FULL_OBLIVION profiles: ${profiles[*]}"
docker compose "${args[@]}" down
docker compose "${args[@]}" up -d
docker compose "${args[@]}" ps
