#!/usr/bin/env bash
# Run the store contract tests (tests/test_store_state_machines.py) against BOTH stores:
# the in-memory store and SupabaseReviewStore over the LOCAL Supabase stack started from
# supabase/config.toml, plus the Data API exposure check (tests/test_data_api_exposure.py).
# See docs/store-contract-tests.md.
#
#   npx --yes supabase@2.122.1 start              # once, from the repository root
#   services/ai-review/scripts/run_store_contract_tests.sh [extra pytest args]
#
# The stack's URL, service_role key and anon key are read from `supabase status` at run
# time and passed only to the pytest process; they are never printed or written to disk.
# They are the CLI's local development keys, valid only for this local stack.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SUPABASE_CLI="${SUPABASE_CLI:-npx --yes supabase@2.122.1}"
PYTHON="${PYTHON:-python}"

env_value() {  # env_value NAME  -> value of NAME="..." in the status output
  printf '%s\n' "$status_env" | sed -n "s/^$1=\"\(.*\)\"\$/\1/p"
}

cd "$REPO_ROOT"
status_env="$($SUPABASE_CLI status -o env 2>/dev/null || true)"
api_url="$(env_value API_URL)"
service_key="$(env_value SERVICE_ROLE_KEY)"
anon_key="$(env_value ANON_KEY)"
if [ -z "$api_url" ] || [ -z "$service_key" ] || [ -z "$anon_key" ]; then
  echo "No local Supabase stack with API keys is running." >&2
  echo "Start it from $REPO_ROOT with: $SUPABASE_CLI start" >&2
  exit 2
fi

cd "$REPO_ROOT/services/ai-review"
CODENTRY_TEST_SUPABASE_URL="$api_url" \
CODENTRY_TEST_SUPABASE_SERVICE_ROLE_KEY="$service_key" \
CODENTRY_TEST_SUPABASE_ANON_KEY="$anon_key" \
  "$PYTHON" -m pytest tests/test_store_state_machines.py tests/test_data_api_exposure.py \
  -p no:cacheprovider -rsx "$@"
