#!/bin/zsh
cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

python3 - << EOF
import asyncio
import sys
sys.path.append('.')
from market_monitor import XRPLMarketMonitor
from config import Config

async def main():
    monitor = XRPLMarketMonitor(Config())
    try:
        await monitor.monitor()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await monitor.stop()

asyncio.run(main())
EOF