#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$root"

profiles=("$@")
if (( ${#profiles[@]} == 0 )); then
  profiles=(full)
fi

args=()
for profile in "${profiles[@]}"; do
  args+=(--profile "$profile")
done

echo "Stopping FULL_OBLIVION profiles: ${profiles[*]}"
docker compose "${args[@]}" down
echo "Stopped FULL_OBLIVION profiles: ${profiles[*]}"
