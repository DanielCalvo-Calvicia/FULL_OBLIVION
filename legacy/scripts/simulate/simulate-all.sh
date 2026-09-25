#!/usr/bin/env bash
set -euo pipefail

dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

simulations=(
  simulate-full-local.sh
  simulate-brain-remote.sh
  simulate-software-only.sh
  simulate-audio-only.sh
  simulate-raspberry-services.sh
)

for script in "${simulations[@]}"; do
  echo
  echo "============================================================"
  echo "$script"
  echo "============================================================"
  bash "$dir/$script"
done
