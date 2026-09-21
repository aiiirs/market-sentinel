#!/bin/zsh
# Wrapper intended for launchd. It loads private environment variables first.

set -euo pipefail

PROJECT_DIR="${MARKET_SENTINEL_PROJECT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
ENV_FILE="${MARKET_SENTINEL_ENV_FILE:-$PROJECT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/us_market_temperature.py" --config "$PROJECT_DIR/temperature.toml" "$@"
