#!/bin/zsh
cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

python3 - << EOF
import asyncio
import sys
sys.path.append('.')
from wallet_analyzer import WalletAnalyzer
from utils.db_handler import XRPLDatabase

async def main():
    analyzer = WalletAnalyzer(XRPLDatabase())
    try:
        await analyzer.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await analyzer.stop()

asyncio.run(main())
EOF