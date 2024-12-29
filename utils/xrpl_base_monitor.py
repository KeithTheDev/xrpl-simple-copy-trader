# xrpl_base_monitor.py

import asyncio
import logging
from typing import Optional, Dict, Any, Callable, Coroutine
import websockets.exceptions

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import Subscribe, Ping

class XRPLBaseMonitor:
    """Base class for XRPL WebSocket monitoring.
    
    Provides common functionality for WebSocket connection management,
    heartbeat monitoring, and reconnection logic.
    """
    
    def __init__(self, 
                 websocket_url: str, 
                 logger_name: str,
                 max_reconnect_attempts: int = 5,
                 reconnect_delay: int = 5,
                 ping_interval: int = 30,
                 ping_timeout: int = 10,
                 on_monitor_started: Optional[Callable[[], Coroutine]] = None,
                 on_transaction_validated: Optional[Callable[[Dict[str, Any]], Coroutine]] = None):
        """Initialize the base monitor.
        
        Args:
            websocket_url: XRPL WebSocket endpoint URL
            logger_name: Name for the logger instance
            max_reconnect_attempts: Maximum number of reconnection attempts
            reconnect_delay: Initial delay between reconnection attempts (seconds)
            ping_interval: How often to send ping messages (seconds)
            ping_timeout: How long to wait for pong response (seconds)
            on_monitor_started: Callback when monitor starts successfully
            on_transaction_validated: Callback for validated transactions
        """
        self.websocket_url = websocket_url
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        
        # Callbacks
        self.on_monitor_started = on_monitor_started
        self.on_transaction_validated = on_transaction_validated
        
        # Runtime state
        self.is_running = False
        self.last_pong = None
        self.ping_task = None
        self.client: Optional[AsyncWebsocketClient] = None
        
        # Setup logging
        self.logger = logging.getLogger(logger_name)
        
    async def _heartbeat(self, client: AsyncWebsocketClient) -> None:
        """Maintain connection heartbeat by sending periodic pings."""
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                
                # Check if we've missed too many pongs
                if self.last_pong and (asyncio.get_event_loop().time() - self.last_pong) > (self.ping_interval + self.ping_timeout):
                    self.logger.error("Connection appears dead (no pong received)")
                    raise websockets.exceptions.ConnectionClosed(1006, "No pong received")
                
                # Send ping using XRPL's native Ping request
                try:
                    ping = Ping()
                    await client.send(ping)
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Ping sent")
                except Exception as e:
                    self.logger.error(f"Failed to send ping: {str(e)}")
                    raise
                    
        except asyncio.CancelledError:
            # Clean shutdown
            pass
            
    async def _subscribe(self, client: AsyncWebsocketClient) -> None:
        """Set up initial subscriptions. Override in derived classes."""
        raise NotImplementedError("Derived classes must implement _subscribe")
        
    async def _handle_message(self, client: AsyncWebsocketClient, message: Dict[str, Any]) -> None:
        """Handle incoming messages. Override in derived classes."""
        # Call transaction validated callback if it exists and message is a validated transaction
        if (self.on_transaction_validated and 
            isinstance(message, dict) and 
            message.get("type") == "transaction" and 
            message.get("validated", False)):
            await self.on_transaction_validated(message)
        
    async def _cleanup(self) -> None:
        """Perform cleanup. Override in derived classes if needed."""
        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass
            self.ping_task = None
        
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:
                self.logger.error(f"Error during client cleanup: {e}")
            self.client = None
            
    async def monitor(self) -> None:
        """Main monitoring loop with automatic reconnection."""
        self.is_running = True
        reconnect_attempts = 0
        current_delay = self.reconnect_delay
        
        while self.is_running:
            try:
                self.logger.info(f"Connecting to {self.websocket_url}")
                
                async with AsyncWebsocketClient(self.websocket_url) as client:
                    self.client = client
                    self.logger.info("Connected to XRPL")
                    
                    # Set up subscriptions
                    await self._subscribe(client)
                    
                    # Call startup callback if exists
                    if self.on_monitor_started:
                        try:
                            await self.on_monitor_started()
                        except Exception as e:
                            self.logger.error(f"Error in monitor started callback: {e}")
                    
                    # Start heartbeat
                    self.last_pong = asyncio.get_event_loop().time()
                    self.ping_task = asyncio.create_task(self._heartbeat(client))
                    
                    # Reset reconnect counters on successful connection
                    reconnect_attempts = 0
                    current_delay = self.reconnect_delay
                    
                    # Monitor incoming messages
                    async for message in client:
                        if not self.is_running:
                            break
                            
                        try:
                            await self._handle_message(client, message)
                            
                            # Update last_pong time for responses
                            if isinstance(message, str) and '"type":"response"' in message:
                                self.last_pong = asyncio.get_event_loop().time()
                                if self.logger.isEnabledFor(logging.DEBUG):
                                    self.logger.debug("Pong received")
                        except Exception as e:
                            self.logger.error(f"Error handling message: {e}")
                            continue
                            
            except asyncio.CancelledError:
                self.logger.info("Monitoring cancelled...")
                break
                
            except (websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.WebSocketException) as e:
                reconnect_attempts += 1
                if reconnect_attempts > self.max_reconnect_attempts:
                    self.logger.error(f"Maximum reconnection attempts ({self.max_reconnect_attempts}) reached. Stopping.")
                    break
                    
                self.logger.error(f"WebSocket error: {str(e)}")
                self.logger.info(f"Reconnection attempt {reconnect_attempts} of {self.max_reconnect_attempts}")
                self.logger.info(f"Waiting {current_delay} seconds before reconnecting...")
                
                if self.is_running:
                    await asyncio.sleep(current_delay)
                    current_delay = min(current_delay * 2, 320)  # Max 5 minutes
                    
            except Exception as e:
                self.logger.error(f"Unexpected error: {str(e)}")
                if self.is_running:
                    await asyncio.sleep(current_delay)
                    current_delay = min(current_delay * 2, 320)
                    
            finally:
                await self._cleanup()
                
    async def stop(self) -> None:
        """Stop the monitor."""
        self.logger.info("Stopping monitor...")
        self.is_running = False
        await self._cleanup()