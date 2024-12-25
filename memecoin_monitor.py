# memecoin_monitor.py

import asyncio
import json
import logging
import argparse
from typing import Any, Dict
import websockets.exceptions

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import Subscribe, Ping
from xrpl.models.transactions import TrustSet
from xrpl.wallet import Wallet

from config import Config
from db_handler import XRPLDatabase

class XRPLTokenMonitor:
    def __init__(self, config: Config, debug: bool = False, test_mode: bool = False):
        self.config = config
        self.target_wallet = config.get('wallets', 'target_wallet')
        self.follower_wallet = Wallet.from_seed(config.get('wallets', 'follower_seed'))
        self.websocket_url = config.get('network', 'websocket_url')
        self.is_running = False
        self.test_mode = test_mode
        self.db = XRPLDatabase()
        
        # Heartbeat settings
        self.ping_interval = 30  # Send ping every 30 seconds
        self.ping_timeout = 10   # Wait 10 seconds for pong response
        self.last_pong = None
        self.ping_task = None

        # Setup logging
        self.logger = logging.getLogger('XRPLMonitor')
        self.logger.setLevel(logging.DEBUG if debug else logging.INFO)
        
        if not self.logger.handlers:
            # File handler from config
            log_config = config.get('logging', 'filename', fallback=None)
            log_format = config.get('logging', 'format', fallback='%(message)s')
            if log_config:
                file_handler = logging.FileHandler(log_config)
                file_handler.setFormatter(logging.Formatter(log_format))
                self.logger.addHandler(file_handler)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(console_handler)

        if debug:
            self.logger.info("Debug mode enabled")
        if test_mode:
            self.logger.info("Test mode enabled - transactions will be monitored but no actual purchases will be made")

        # Callback-funktioner som kan sättas från web_server.py
        self.on_trust_line_created = None
        self.on_monitor_started = None

    async def _log_transaction(self, tx: Dict[str, Any], validated: bool) -> None:
        """Helper method for transaction logging"""
        tx_type = tx.get("TransactionType", "Unknown")
        tx_hash = tx.get('hash', 'Unknown hash')
        
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Got {tx_type} (validated={validated}) from target wallet")

        if validated:
            self.logger.info(f"Transaction {tx_hash} is now validated.")
            
        if validated and tx_type == "TrustSet":
            self.logger.info("Processing TrustSet transaction...")

    async def set_trust_line(self, client: AsyncWebsocketClient, currency: str, issuer: str, limit: str):
        """Set a trust line for the token"""
        if self.test_mode:
            self.logger.info(f"TEST MODE: Would set trust line for {currency} with limit {limit}")
            return

        self.logger.info(f"Setting trust line for {currency}...")
        
        trust_limit = min(
            float(limit), 
            float(self.config.get('trading', 'max_trust_line_amount'))
        )
        trust_limit = max(
            trust_limit, 
            float(self.config.get('trading', 'min_trust_line_amount'))
        )
        
        # Create TrustSet transaction with fee
        trust_set_tx = TrustSet(
            account=self.follower_wallet.classic_address,
            fee="12",  # Standard fee in drops (0.000012 XRP)
            limit_amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=str(trust_limit)
            )
        )
        
        try:
            response = await submit_and_wait(
                transaction=trust_set_tx,
                client=client,
                wallet=self.follower_wallet
            )
            result = response.result.get('meta', {}).get('TransactionResult')
            self.logger.info(f"Trust line set: {result}")
            
            if result != "tesSUCCESS":
                raise Exception(f"Trust line setting failed: {result}")
                
        except Exception as e:
            self.logger.error(f"Error setting trust line: {str(e)}")
            raise

    async def handle_trust_set(self, client: AsyncWebsocketClient, tx: Dict[str, Any]):
        """Handle TrustSet transactions related to target wallet"""

        self.logger.debug("Entering handle_trust_set method")

        account = tx.get("Account")
        destination = tx.get("Destination")
        self.logger.debug(f"Transaction Account: {account}")
        self.logger.debug(f"Transaction Destination: {destination}")
        self.logger.debug(f"Transaction Type: {tx.get('TransactionType')}")

        # Behandla endast TrustSet-transaktioner där target_wallet är Account eller Destination
        if account != self.target_wallet and destination != self.target_wallet:
            self.logger.debug(f"Ignoring TrustSet from {account} to {destination}, not involving target_wallet.")
            return

        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            self.logger.warning(f"LimitAmount is not a dict; got {type(limit_amount)} instead. Aborting handle_trust_set.")
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        limit = limit_amount.get("value")

        if not all([currency, issuer, limit]):
            self.logger.warning("Incomplete LimitAmount data. Aborting handle_trust_set.")
            return

        self.logger.info(f"\n🔗 Target wallet set new trust line:")
        self.logger.info(f"   Currency: {currency}")
        self.logger.info(f"   Issuer: {issuer}")
        self.logger.info(f"   Limit: {limit}\n")

        # Försök att lägga till trustline i databasen och logga resultatet
        try:
            self.db.add_trustline(currency, issuer, limit, tx.get('hash', 'Unknown'), self.test_mode)
            self.logger.info("Trust line successfully added to the database.")
        except Exception as e:
            self.logger.error(f"Failed to add trust line to the database: {str(e)}")
            return

        # Anropa callback för TrustSet
        if self.on_trust_line_created:
            self.logger.debug("Calling on_trust_line_created callback")
            try:
                await self.on_trust_line_created(tx)
                self.logger.debug("Callback executed successfully")
            except Exception as e:
                self.logger.error(f"Error in on_trust_line_created callback: {str(e)}")

        # Set our own trust line and make initial purchase
        try:
            await self.set_trust_line(client, currency, issuer, limit)
        except Exception as e:
            self.logger.error(f"Error handling trust set: {str(e)}")

    async def _heartbeat(self, client: AsyncWebsocketClient):
        """Send periodic pings and monitor for pong responses"""
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                
                # Check if we've missed too many pongs
                if self.last_pong and (asyncio.get_event_loop().time() - self.last_pong) > (self.ping_interval + self.ping_timeout):
                    self.logger.error("Connection appears dead (no pong received)")
                    # Force the connection to close, which will trigger a reconnect
                    raise websockets.exceptions.ConnectionClosed(1006, "No pong received")
                
                # Send ping - using XRPL's native Ping request
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

    async def monitor(self):
        """Main monitoring loop"""
        self.is_running = True
        reconnect_delay = 5  # Starting delay in seconds
        max_delay = 320  # Maximum delay (~5 minutes)
        
        while self.is_running:
            try:
                self.logger.info(f"Connecting to {self.websocket_url}")
                
                async with AsyncWebsocketClient(self.websocket_url) as client:
                    self.logger.info("Connected to XRPL")
                    self.logger.info(f"Target wallet: {self.target_wallet}")
                    self.logger.info(f"Follower wallet: {self.follower_wallet.classic_address}")

                    # Subscribe to target wallet
                    subscribe_request = Subscribe(
                        accounts=[self.target_wallet],
                        streams=["transactions"]  
                    )                   
                    await client.send(subscribe_request)
                    self.logger.info(f"Subscribed to target wallet: {self.target_wallet}")
                    
                    # Skicka initialt meddelande till frontend
                    if self.on_monitor_started:
                        self.logger.debug("Calling on_monitor_started callback")
                        try:
                            await self.on_monitor_started()
                            self.logger.debug("Monitor started callback executed successfully")
                        except Exception as e:
                            self.logger.error(f"Error in on_monitor_started callback: {str(e)}")
                    
                    # Start heartbeat
                    self.last_pong = asyncio.get_event_loop().time()
                    self.ping_task = asyncio.create_task(self._heartbeat(client))
                    
                    # Reset reconnect delay on successful connection
                    reconnect_delay = 5
                    
                    # Monitor incoming messages
                    async for message in client:
                        if not self.is_running:
                            break
                            
                        # Handle message
                        if isinstance(message, str):
                            try:
                                data = json.loads(message)
                                
                                # Handle pong responses
                                if data.get("type") == "response":
                                    self.last_pong = asyncio.get_event_loop().time()
                                    if self.logger.isEnabledFor(logging.DEBUG):
                                        self.logger.debug("Pong received")
                                    continue
                                    
                            except json.JSONDecodeError:
                                self.logger.error(f"Failed to parse message")
                                continue
                        else:
                            data = message

                        # Process validated transactions
                        if data.get("type") == "transaction":
                            tx = data.get("tx_json", {})
                            validated = data.get("validated", False)
                            
                            await self._log_transaction(tx, validated)
                            
                            if validated and tx.get("TransactionType") == "TrustSet":
                                await self.handle_trust_set(client, tx)

            except asyncio.CancelledError:
                self.logger.info("Monitoring cancelled...")
                break
                
            except websockets.exceptions.ConnectionClosed as e:
                self.logger.error(f"WebSocket connection closed: {str(e)}")
                if self.is_running:
                    self.logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
                    
            except websockets.exceptions.WebSocketException as e:
                self.logger.error(f"WebSocket error: {str(e)}")
                if self.is_running:
                    self.logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
                    
            except Exception as e:
                self.logger.error(f"Unexpected error: {str(e)}")
                if self.is_running:
                    self.logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
            
            finally:
                # Cleanup heartbeat task
                if self.ping_task:
                    self.ping_task.cancel()
                    try:
                        await self.ping_task
                    except asyncio.CancelledError:
                        pass
                    self.ping_task = None

    async def stop(self):
        """Gracefully stop the monitor"""
        self.logger.info("Stopping monitor...")
        self.is_running = False

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='XRPL Token Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('-t', '--test', action='store_true', help='Test mode - no actual purchases will be made')
    args = parser.parse_args()

    # Load and validate configuration
    config = Config()
    if not config.validate():
        return

    monitor = XRPLTokenMonitor(config, debug=args.debug, test_mode=args.test)
    
    try:
        await monitor.monitor()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await monitor.stop()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())