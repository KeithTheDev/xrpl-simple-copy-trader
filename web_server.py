from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
import json
from typing import Dict, List
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

@app.on_event("startup")
async def startup_event():
    global monitor, monitor_stats
    config = Config()
    if not config.validate():
        raise Exception("Invalid configuration")
    
    # Initialize monitor with flags from environment
    debug_mode = app.debug_mode
    test_mode = app.test_mode

    # Initialize monitor with flags
    monitor = XRPLTokenMonitor(config, debug=debug_mode, test_mode=test_mode)

    # Update monitor stats with current settings
    monitor_stats.update({
        "debug_mode": debug_mode,
        "test_mode": test_mode
    })
    print(f"Startup complete - debug={debug_mode}, test={test_mode}")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the dashboard homepage"""
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "stats": monitor_stats,
            "ws_url": f"ws://{request.headers.get('host')}/ws"
        }
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections for real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "start":
                    print(f"Starting monitor with debug={app.debug_mode}, test={app.test_mode}")
                    await start_monitor()
                elif message.get("type") == "stop":
                    await stop_monitor()
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        active_connections.remove(websocket)

async def broadcast_stats():
    """Broadcast current stats to all connected clients"""
    if not active_connections:
        return
    
    for connection in active_connections:
        try:
            await connection.send_json(monitor_stats)
        except Exception as e:
            print(f"Error broadcasting stats: {e}")

async def start_monitor():
    """Start the XRPL monitor"""
    global monitor, monitor_stats
    if monitor_stats["status"] != "running":
        # Reinitialize monitor with correct flags
        config = Config()
        if not config.validate():
            raise Exception("Invalid configuration")
            
        monitor = XRPLTokenMonitor(
            config, 
            debug=app.debug_mode,
            test_mode=app.test_mode
        )
        
        monitor_stats.update({
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "last_error": None,
            "debug_mode": app.debug_mode,
            "test_mode": app.test_mode
        })
        await broadcast_stats()
        asyncio.create_task(run_monitor())

async def stop_monitor():
    """Stop the XRPL monitor"""
    global monitor_stats
    if monitor and monitor_stats["status"] == "running":
        await monitor.stop()
        monitor_stats["status"] = "stopped"
        await broadcast_stats()

async def run_monitor():
    """Run the monitor and handle updates"""
    try:
        await monitor.monitor()
    except Exception as e:
        monitor_stats["last_error"] = str(e)
        monitor_stats["status"] = "error"
        await broadcast_stats()

@app.get("/api/stats")
async def get_stats():
    """API endpoint to get current stats"""
    return monitor_stats

if __name__ == "__main__":
    import argparse
    import uvicorn
    from typing import Dict
    
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

    print(f"Starting web_server.py with debug={app.debug_mode}, test_mode={app.test_mode}, port={args.port}")
    
    uvicorn.run("web_server:app", host="0.0.0.0", port=args.port, reload=True)