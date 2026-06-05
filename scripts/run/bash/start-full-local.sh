#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$root/scripts/run/bash/lib.sh"
ensure_repos "$root"
cd "$root"

echo "Starting FULL_OBLIVION full local stack..."
docker compose --profile full up -d
docker compose --profile full ps

echo "Started full local stack."
echo "System health: curl http://localhost:7999/integrations/health"
