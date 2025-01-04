# web_server.py

import asyncio
import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Any
from datetime import datetime
import os

# Import the monitor
from memecoin_monitor import XRPLTokenMonitor
from config import Config

# Base paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Global state
monitor: XRPLTokenMonitor = None
active_connections: List[WebSocket] = []
monitor_stats = {
    "last_transaction": None,
    "trust_lines_today": 0,
    "transactions_today": 0,
    "status": "stopped",
    "last_error": None,
    "start_time": None,
    "debug_mode": False,
    "test_mode": False
}

# Callback för TrustSet transaktioner
async def on_trust_line_created(tx_data: Dict[str, Any]):
    global monitor_stats
    monitor_stats["trust_lines_today"] += 1
    monitor_stats["transactions_today"] += 1
    monitor_stats["last_transaction"] = f"TrustSet: Hash={tx_data.get('tx_hash', 'Unknown')}"
    logging.info(f"Updated monitor_stats: {monitor_stats}")
    await broadcast_stats()

# Callback när monitorn startar
async def on_monitor_started():
    global monitor_stats
    monitor_stats["status"] = "running"
    monitor_stats["start_time"] = datetime.now().isoformat()
    monitor_stats["last_error"] = None
    logging.info("Monitor started - updating monitor_stats and broadcasting to clients.")
    await broadcast_stats()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global monitor, monitor_stats
    
    # Ensure directories exist
    TEMPLATES_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)

    # Check if index.html exists
    INDEX_TEMPLATE = TEMPLATES_DIR / "index.html"
    if not INDEX_TEMPLATE.exists():
        raise FileNotFoundError(
            "index.html not found in templates directory. "
            "Please ensure template files are in place before starting the server."
        )
    
    # Validate config
    config = Config()
    if not config.validate():
        raise Exception("Invalid configuration")
            
    # Initialize monitor with flags from environment
    monitor = XRPLTokenMonitor(
        config, 
        debug=app.debug_mode,
        test_mode=app.test_mode
    )
    
    # Set global callbacks
    monitor.on_trust_line_created = on_trust_line_created
    monitor.on_monitor_started = on_monitor_started

    # Update monitor_stats with current settings
    monitor_stats.update({
        "debug_mode": app.debug_mode,
        "test_mode": app.test_mode
    })
    logging.info(f"Startup complete - debug={app.debug_mode}, test={app.test_mode}")
    
    yield
    
    # Shutdown
    if monitor:
        await monitor.stop()
        logging.info("Monitor stopped during shutdown.")

# Initialize app
app = FastAPI(lifespan=lifespan)

# Initialize app state from environment
app.debug_mode = os.environ.get('APP_DEBUG', 'False').lower() == 'true'
app.test_mode = os.environ.get('APP_TEST', 'False').lower() == 'true'

# Setup templates and static files
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the dashboard homepage"""
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "stats": monitor_stats,
            "ws_url": f"ws://{request.client.host}:{request.url.port}/ws"
        }
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections for real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)
    logging.info(f"New client connected: {websocket.client.host}:{websocket.client.port}")
    try:
        # Send current stats to the new client
        await websocket.send_json(monitor_stats)
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "start":
                    logging.info(f"Received start command from {websocket.client.host}:{websocket.client.port}")
                    await start_monitor()
                elif message.get("type") == "stop":
                    logging.info(f"Received stop command from {websocket.client.host}:{websocket.client.port}")
                    await stop_monitor()
            except json.JSONDecodeError:
                logging.warning(f"Received invalid JSON from {websocket.client.host}:{websocket.client.port}")
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
    finally:
        active_connections.remove(websocket)
        logging.info(f"Client disconnected: {websocket.client.host}:{websocket.client.port}")

async def broadcast_stats():
    """Broadcast current stats to all connected clients"""
    if not active_connections:
        return

    message_data = json.dumps(monitor_stats)
    logging.debug(f"Broadcasting stats to {len(active_connections)} clients: {monitor_stats}")
    await asyncio.gather(*[client.send_text(message_data) for client in active_connections], return_exceptions=True)

async def start_monitor():
    """Start the XRPL monitor"""
    global monitor, monitor_stats
    if monitor_stats["status"] != "running":
        config = Config()
        if not config.validate():
            raise Exception("Invalid configuration")
            
        monitor = XRPLTokenMonitor(
            config, 
            debug=app.debug_mode,
            test_mode=app.test_mode
        )
        
        # Set global callbacks again if re-initializing monitor
        monitor.on_trust_line_created = on_trust_line_created
        monitor.on_monitor_started = on_monitor_started

        monitor_stats.update({
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "last_error": None,
            "debug_mode": app.debug_mode,
            "test_mode": app.test_mode
        })
        logging.info("Starting monitor and broadcasting updated stats.")
        await broadcast_stats()
        asyncio.create_task(run_monitor())

async def stop_monitor():
    """Stop the XRPL monitor"""
    global monitor_stats
    if monitor and monitor_stats["status"] == "running":
        await monitor.stop()
        monitor_stats["status"] = "stopped"
        logging.info("Monitor stopped and broadcasting updated stats.")
        await broadcast_stats()

async def run_monitor():
    """Run the monitor and handle updates"""
    try:
        await monitor.monitor()
    except Exception as e:
        monitor_stats["last_error"] = str(e)
        monitor_stats["status"] = "error"
        logging.error(f"Monitor encountered an error: {e}")
        await broadcast_stats()

@app.get("/api/stats")
async def get_stats():
    """API endpoint to get current stats"""
    return monitor_stats

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description='XRPL Monitor Web Dashboard')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('-t', '--test', action='store_true', help='Test mode - no actual purchases will be made')
    parser.add_argument('-p', '--port', type=int, default=8000, help='Port to run webserver on')
    args = parser.parse_args()

    # Store flags in environment variables
    os.environ['APP_DEBUG'] = str(args.debug)
    os.environ['APP_TEST'] = str(args.test)
    
    # Update app state from environment
    app.debug_mode = args.debug
    app.test_mode = args.test

    # Set up root logger
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler()
        ]
    )
    
    # Set specific levels for noisy libraries
    logging.getLogger('websockets').setLevel(logging.INFO)
    logging.getLogger('websockets.client').setLevel(logging.INFO)

    logging.info(f"Starting web_server.py with debug={app.debug_mode}, test_mode={app.test_mode}, port={args.port}")
    
    uvicorn.run("web_server:app", host="0.0.0.0", port=args.port, reload=True)