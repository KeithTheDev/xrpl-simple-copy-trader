# scripts/run_price_monitor.sh
cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
   source venv/bin/activate
fi

python3 - << EOF
import asyncio
import sys
sys.path.append('.')
from price_monitor import PriceMonitor
from utils.db_handler import XRPLDatabase
from config import Config

async def main():
   config = Config()
   db = XRPLDatabase()
   monitor = PriceMonitor(config.get('network', 'websocket_url'), db)
   
   try:
       await monitor.start()
   except KeyboardInterrupt:
       print("\nShutting down...")
       await monitor.stop()

asyncio.run(main())
EOF