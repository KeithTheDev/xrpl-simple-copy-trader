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
from xrpl.models.transactions import Payment, TrustSet
from xrpl.wallet import Wallet

from config import Config

class XRPLTokenMonitor:
    def __init__(self, config: Config, debug: bool = False, test_mode: bool = False):
        self.config = config
        self.target_wallet = config.get('wallets', 'target_wallet')
        self.follower_wallet = Wallet.from_seed(config.get('wallets', 'follower_seed'))
        self.websocket_url = config.get('network', 'websocket_url')
        self.is_running = False
        self.test_mode = test_mode
        
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
            log_config = config.get('logging', default={})
            if log_config.get('filename'):
                file_handler = logging.FileHandler(log_config['filename'])
                file_handler.setFormatter(logging.Formatter(log_config.get('format', '%(message)s')))
                self.logger.addHandler(file_handler)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(console_handler)

        if debug:
            self.logger.info("Debug mode enabled")
        if test_mode:
            self.logger.info("Test mode enabled - transactions will be monitored but no actual purchases will be made")

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

    async def make_small_purchase(self, client: AsyncWebsocketClient, currency: str, issuer: str):
        """Make a small purchase of the token using path-finding"""
        amount = self.config.get('trading', 'initial_purchase_amount')
        send_max_xrp = self.config.get('trading', 'send_max_xrp')
        slippage = float(self.config.get('trading', 'slippage_percent')) / 100.0
        
        if self.test_mode:
            self.logger.info(f"TEST MODE: Would make purchase of {currency} amount: {amount}")
            return

        self.logger.info(f"Attempting purchase of {currency}...")
        
        # Calculate min delivery amount with configured slippage
        target_amount = float(amount)
        min_amount = target_amount * (1 - slippage)
        
        # Convert send_max to drops (multiply by 1M)
        send_max_drops = str(int(float(send_max_xrp) * 1_000_000))
        
        # tfPartialPayment = 0x00020000
        payment = Payment(
            account=self.follower_wallet.classic_address,
            destination=self.follower_wallet.classic_address,  # Send to self
            fee="12",  # Standard fee in drops
            send_max=send_max_drops,
            flags=0x00020000,  # tfPartialPayment flag
            amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=str(target_amount)
            ),
            deliver_min=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=str(min_amount)
            )
        )
        
        try:
            response = await submit_and_wait(
                transaction=payment,
                client=client,
                wallet=self.follower_wallet
            )
            result = response.result.get('meta', {}).get('TransactionResult')
            self.logger.info(f"Purchase attempt result: {result}")
            
            if result != "tesSUCCESS":
                raise Exception(f"Purchase failed: {result}")
            
            # Log delivered amount if available
            delivered = response.result.get('meta', {}).get('delivered_amount')
            if delivered and isinstance(delivered, dict):
                self.logger.info(f"Actually delivered: {delivered.get('value')} {delivered.get('currency')}")
                self.logger.info(f"Used {float(send_max_xrp)} XRP max")
                
        except Exception as e:
            self.logger.error(f"Error making purchase: {str(e)}")
            raise


    async def handle_trust_set(self, client: AsyncWebsocketClient, tx: Dict[str, Any]):
        """Handle TrustSet transactions from target wallet"""
        if tx.get("Account") != self.target_wallet:
            return

        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        limit = limit_amount.get("value")

        if not all([currency, issuer, limit]):
            return

        self.logger.info(f"\n🔗 Target wallet set new trust line:")
        self.logger.info(f"   Currency: {currency}")
        self.logger.info(f"   Issuer: {issuer}")
        self.logger.info(f"   Limit: {limit}\n")

        # Set our own trust line and make initial purchase
        try:
            await self.set_trust_line(client, currency, issuer, limit)
            await self.make_small_purchase(client, currency, issuer)
        except Exception as e:
            self.logger.error(f"Error handling trust set: {str(e)}")

    async def _heartbeat(self, client: AsyncWebsocketClient):
        """Send periodic pings and monitor for pong responses"""

        self.logger.debug("Connection montoring code disabled for now.")
        return

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
                    subscribe_request = Subscribe(accounts=[self.target_wallet])
                    await client.send(subscribe_request)
                    self.logger.info(f"Subscribed to target wallet: {self.target_wallet}")
                    
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
                        if data.get("type") == "transaction" and data.get("validated", False):
                            tx = data.get("tx_json", {})
                            tx_type = tx.get("TransactionType")
                            
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(f"Got {tx_type} from target wallet")
                            
                            if tx_type == "TrustSet":
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