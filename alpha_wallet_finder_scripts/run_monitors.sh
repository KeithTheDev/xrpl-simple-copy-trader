#!/bin/zsh

# scripts/run_monitors.zsh
cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Check MongoDB
if ! pgrep -x "mongod" > /dev/null; then
    echo "Starting MongoDB..."
    mongod --dbpath ./data/db &
    sleep 2
fi

python3 - << EOF
import asyncio
import sys
sys.path.append('.')
from market_monitor import XRPLMarketMonitor
from price_monitor import PriceMonitor
from wallet_analyzer import WalletAnalyzer
from utils.db_handler import XRPLDatabase
from config import Config

async def main():
    config = Config()
    db = XRPLDatabase()
    
    market_monitor = XRPLMarketMonitor(config)
    price_monitor = PriceMonitor(config.get('network', 'websocket_url'), db)
    wallet_analyzer = WalletAnalyzer(db)
    
    try:
        await asyncio.gather(
            market_monitor.monitor(),
            price_monitor.start(),
            wallet_analyzer.start()
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        await asyncio.gather(
            market_monitor.stop(),
            price_monitor.stop(),
            wallet_analyzer.stop()
        )
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
EOF