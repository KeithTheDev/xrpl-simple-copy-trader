# web_server.py

import asyncio
import websockets
import json
import logging

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, List, Any
from datetime import datetime
import os

from memecoin_monitor import XRPLTokenMonitor
from config import Config

app = FastAPI()

# Initialize app state from environment
app.debug_mode = os.environ.get('APP_DEBUG', 'False').lower() == 'true'
app.test_mode = os.environ.get('APP_TEST', 'False').lower() == 'true'

# Ensure directories exist
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Setup templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

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

# Callback för TrustSet-transaktioner
async def on_trust_line_created(tx_data: Dict[str, Any]):
    global monitor_stats
    monitor_stats["trust_lines_today"] += 1
    monitor_stats["transactions_today"] += 1
    monitor_stats["last_transaction"] = f"TrustSet: Hash={tx_data.get('hash', 'Unknown')}"
    logging.info(f"Updated monitor_stats: {monitor_stats}")
    await broadcast_stats()

# Callback när monitoreringen startar
async def on_monitor_started():
    global monitor_stats
    monitor_stats["status"] = "running"
    monitor_stats["start_time"] = datetime.now().isoformat()
    monitor_stats["last_error"] = None
    logging.info("Monitor started - updating monitor_stats and broadcasting to clients.")
    await broadcast_stats()

@app.on_event("startup")
async def startup_event():
    global monitor, monitor_stats
    config = Config()
    if not config.validate():
        raise Exception("Invalid configuration")

    # Initialize monitor med flags från miljön
    debug_mode = app.debug_mode
    test_mode = app.test_mode

    # Initialize monitor
    monitor = XRPLTokenMonitor(
        config,
        debug=debug_mode,
        test_mode=test_mode
    )

    # Sätt global callback
    monitor.on_trust_line_created = on_trust_line_created
    monitor.on_monitor_started = on_monitor_started

    # Uppdatera monitor_stats med nuvarande inställningar
    monitor_stats.update({
        "debug_mode": debug_mode,
        "test_mode": test_mode
    })
    logging.info(f"Startup complete - debug={debug_mode}, test={test_mode}")

@app.on_event("shutdown")
async def shutdown_event():
    global monitor
    if monitor:
        await monitor.stop()
        logging.info("Monitor stopped during shutdown.")

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
        # Skicka nuvarande stats till den nya klienten
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
        
        # Sätt global callback igen om du init:ar monitor på nytt
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

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler()
        ]
    )

    logging.info(f"Starting web_server.py with debug={app.debug_mode}, test_mode={app.test_mode}, port={args.port}")
    
    uvicorn.run("web_server:app", host="0.0.0.0", port=args.port, reload=True)