#!/bin/zsh

# scripts/run_alpha_wallet_finder.sh
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Ensure data directory exists
mkdir -p "${PROJECT_ROOT}/data/db"

# Check MongoDB and start with specific dbpath
if ! pgrep -x "mongod" > /dev/null; then
    echo "Starting MongoDB..."
    mongod --dbpath "${PROJECT_ROOT}/data/db" &
    sleep 2
fi

# Start all components in separate terminals
osascript -e '
tell application "Terminal"
    do script "cd '${PROJECT_ROOT}'; source venv/bin/activate; zsh alpha_wallet_finder_scripts/run_market_monitor.sh"
    do script "cd '${PROJECT_ROOT}'; source venv/bin/activate; zsh alpha_wallet_finder_scripts/run_price_monitor.sh"
    do script "cd '${PROJECT_ROOT}'; source venv/bin/activate; zsh alpha_wallet_finder_scripts/run_wallet_scorer.sh"
end tell
'