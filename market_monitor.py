# market_monitor.py

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import Subscribe, Ping  # Ensure Ping is imported correctly
from xrpl.models.transactions import TrustSet
from xrpl.wallet import Wallet

import websockets.exceptions  # Import websockets.exceptions
from config import Config
from db_handler import XRPLDatabase

class XRPLMarketMonitor:
    def __init__(self, config: Config, debug: bool = False):
        self.config = config

        # Network settings
        self.websocket_url = config.get('network', 'websocket_url')
        self.max_reconnect_attempts = int(config.get('network', 'max_reconnect_attempts', fallback=5))
        self.reconnect_delay = int(config.get('network', 'reconnect_delay_seconds', fallback=5))

        # Database connection
        self.db = XRPLDatabase()

        # Runtime state
        self.is_running = False
        self.last_save = datetime.now()

        # Monitoring configuration
        self.min_trade_volume = float(config.get('monitoring', 'min_trade_volume', fallback=1000))
        self.min_trust_lines = int(config.get('monitoring', 'min_trust_lines', fallback=5))
        self.data_file = config.get('monitoring', 'data_file', fallback='token_data.json')
        self.save_interval = int(config.get('monitoring', 'save_interval_minutes', fallback=5)) * 60  # Convert to seconds

        # Analytics configuration
        self.price_check_interval = int(config.get('analytics', 'price_check_interval_minutes', fallback=5)) * 60
        self.min_liquidity = float(config.get('analytics', 'min_liquidity', fallback=1000))
        self.max_slippage = float(config.get('analytics', 'max_slippage', fallback=10))

        # Trading configuration
        self.slippage_percent = float(config.get('trading', 'slippage_percent', fallback=5))
        self.send_max_xrp = float(config.get('trading', 'send_max_xrp', fallback=85))

        # Heartbeat settings
        self.ping_interval = 30  # Send ping every 30 seconds
        self.ping_timeout = 10   # Wait 10 seconds for pong response
        self.last_pong = None
        self.ping_task = None
        self.status_task = None  # Task for periodic status updates

        # Setup logging
        self.logger = logging.getLogger('XRPLMarketMonitor')
        self.logger.setLevel(logging.DEBUG if debug else logging.INFO)

        if not self.logger.handlers:
            # File handler from config
            log_config = config.get('logging', fallback={})
            if log_config.get('filename'):
                file_handler = logging.FileHandler(log_config['filename'])
                file_handler.setLevel(logging.INFO)  # Set file handler level to INFO
                file_handler.setFormatter(logging.Formatter(
                    log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                ))
                self.logger.addHandler(file_handler)

            # Console handler
            console_handler = logging.StreamHandler()
            console_level = logging.DEBUG if debug else logging.INFO
            console_handler.setLevel(console_level)  # Set console handler level based on debug flag
            console_handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(console_handler)

        if debug:
            self.logger.info("Debug mode enabled")

        # In-memory tracking (for performance and immediate state)
        self.tokens = {}        # Basic token info
        self.hot_tokens = set() # Tokens meeting criteria
        self.traded_tokens = {} # Trading history

        # Initialize wallets
        self.target_wallet = config.get('wallets', 'target_wallet')
        follower_seed = config.get('wallets', 'follower_seed')

        if not self.target_wallet:
            self.logger.error("Missing target_wallet in config")
            raise Exception("Invalid configuration")

        if not follower_seed:
            self.logger.error("Missing follower_seed in config")
            raise Exception("Invalid configuration")

        try:
            self.follower_wallet = Wallet.from_seed(follower_seed)
            self.logger.info(f"Follower wallet initialized: {self.follower_wallet.classic_address}")
        except Exception as e:
            self.logger.error(f"Invalid follower_seed format: {e}")
            raise Exception("Invalid configuration")

    def get_token_key(self, currency: str, issuer: str) -> str:
        """Create a unique key for a token"""
        return f"{currency}:{issuer}"

    async def handle_trust_set(self, tx: Dict[str, Any]):
        """Handle TrustSet transactions to detect new tokens and track trust lines"""
        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        value = limit_amount.get("value")
        wallet = tx.get("Account")

        if not all([currency, issuer, value, wallet]):
            return

        token_key = self.get_token_key(currency, issuer)
        
        # Store in analytics database
        self.db.analytics_add_trust_line(
            currency=currency,
            issuer=issuer,
            wallet=wallet,
            limit=value,
            tx_hash=tx.get("hash", "unknown")
        )
        
        if value == "0":
            # Trust line removal
            if token_key in self.tokens:
                self.tokens[token_key]['trust_lines'] = max(0, self.tokens[token_key]['trust_lines'] - 1)
                self.logger.info(f"\n🔥 Trust line removed for {currency}")
                self.logger.info(f"   Issuer: {issuer}")
                self.logger.info(f"   Remaining trust lines: {self.tokens[token_key]['trust_lines']}\n")
        else:
            # New trust line
            if token_key not in self.tokens:
                # First time seeing this token
                self.tokens[token_key] = {
                    'currency': currency,
                    'issuer': issuer,
                    'first_seen': datetime.now(),
                    'trust_lines': 1
                }
                self.logger.info(f"\n🆕 New token discovered!")
                self.logger.info(f"   Currency: {currency}")
                self.logger.info(f"   Issuer: {issuer}")
                self.logger.info(f"   First trust line value: {value}\n")
            else:
                # Increment trust lines
                self.tokens[token_key]['trust_lines'] += 1
                current_trust_lines = self.tokens[token_key]['trust_lines']
                
                # Check if token just became "hot"
                if current_trust_lines == self.min_trust_lines:
                    self.hot_tokens.add(token_key)
                    time_to_hot = datetime.now() - self.tokens[token_key]['first_seen']
                    self.logger.info(f"\n🔥 Token reached {self.min_trust_lines} trust lines!")
                    self.logger.info(f"   Currency: {currency}")
                    self.logger.info(f"   Issuer: {issuer}")
                    self.logger.info(f"   Time to reach {self.min_trust_lines} trust lines: {time_to_hot}\n")

    async def handle_payment(self, tx: Dict[str, Any]):
        """Handle Payment transactions to track token trading activity"""
        amount = tx.get("Amount")
        if not isinstance(amount, dict):  # Skip XRP payments
            return

        currency = amount.get("currency")
        issuer = amount.get("issuer")
        value = float(amount.get("value", 0))
        
        buyer = tx.get("Destination")
        seller = tx.get("Account")

        if not all([currency, issuer, value, buyer, seller]) or value < self.min_trade_volume:
            return

        token_key = self.get_token_key(currency, issuer)
        
        # Store in analytics database
        delivered_amount = tx.get("DeliveredAmount", amount)
        if isinstance(delivered_amount, dict):
            actual_value = delivered_amount.get("value", value)
        else:
            actual_value = value
            
        self.db.analytics_add_trade(
            currency=currency,
            issuer=issuer,
            amount=str(actual_value),
            price_xrp="0",  # We'll need price monitoring for this
            buyer=buyer,
            seller=seller,
            tx_hash=tx.get("hash", "unknown")
        )
        
        # Update in-memory tracking
        if token_key in self.tokens:
            if token_key not in self.traded_tokens:
                self.traded_tokens[token_key] = {
                    'total_volume': value,
                    'trades': 1,
                    'first_trade': datetime.now()
                }
                time_to_trade = self.traded_tokens[token_key]['first_trade'] - self.tokens[token_key]['first_seen']
                self.logger.info(f"\n💰 First trade for token {currency}!")
                self.logger.info(f"   Issuer: {issuer}")
                self.logger.info(f"   Amount: {value}")
                self.logger.info(f"   Time from first trust line to first trade: {time_to_trade}")
                if token_key in self.hot_tokens:
                    self.logger.info(f"   ⚠️  This token has {self.tokens[token_key]['trust_lines']} trust lines!")
                self.logger.info("")
            else:
                self.traded_tokens[token_key]['total_volume'] += value
                self.traded_tokens[token_key]['trades'] += 1
                
                if token_key in self.hot_tokens:
                    self.logger.info(f"\n💸 Hot token traded!")
                    self.logger.info(f"   Currency: {currency}")
                    self.logger.info(f"   Amount: {value}")
                    self.logger.info(f"   Total volume: {self.traded_tokens[token_key]['total_volume']}")
                    self.logger.info(f"   Total trades: {self.traded_tokens[token_key]['trades']}")
                    self.logger.info(f"   Trust lines: {self.tokens[token_key]['trust_lines']}\n")

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

    def _save_data(self):
        """Save current state to JSON file as backup/log"""
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'tokens': {
                k: {
                    'currency': v['currency'],
                    'issuer': v['issuer'],
                    'first_seen': v['first_seen'].isoformat(),
                    'trust_lines': v['trust_lines']
                } for k, v in self.tokens.items()
            },
            'hot_tokens': list(self.hot_tokens),
            'traded_tokens': {
                k: {
                    'total_volume': v['total_volume'],
                    'trades': v['trades'],
                    'first_trade': v['first_trade'].isoformat()
                } for k, v in self.traded_tokens.items()
            }
        }
        
        try:
            with open(self.data_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
            self.logger.debug(f"State snapshot saved to {self.data_file}")
        except Exception as e:
            self.logger.error(f"Error saving state snapshot: {e}")

    def _print_status_update(self):
        """Print current status to terminal with yellow text"""
        yellow = "\033[93m"  # ANSI escape code for yellow
        reset = "\033[0m"    # ANSI escape code to reset color

        status = f"{yellow}\n{'='*50}\n"
        status += f"Status Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n"
        status += f"{'='*50}\n"

        status += f"Tracking {len(self.tokens)} tokens total\n"
        status += f"Hot tokens (>= {self.min_trust_lines} trust lines): {len(self.hot_tokens)}\n"

        if self.hot_tokens:
            status += "\nHot Token Details:\n"
            for token_key in self.hot_tokens:
                token = self.tokens[token_key]
                trading = self.traded_tokens.get(token_key, {})
                
                status += f"\n🔥 {token['currency']}\n"
                status += f"   Issuer: {token['issuer']}\n"
                status += f"   Trust lines: {token['trust_lines']}\n"
                status += f"   Age: {datetime.now() - token['first_seen']}\n"
                
                if trading:
                    status += f"   Trade volume: {trading['total_volume']}\n"
                    status += f"   Number of trades: {trading['trades']}\n"
                    status += f"   First traded: {trading['first_trade']}\n"
                    time_to_trade = trading['first_trade'] - token['first_seen']
                    status += f"   Time to first trade: {time_to_trade}\n"
        
        status += f"\n{'='*50}{reset}\n"
        print(status)

    async def _periodic_status_update(self):
        """Periodically print status updates every 5 minutes"""
        try:
            while self.is_running:
                await asyncio.sleep(300)  # 5 minutes
                self._print_status_update()
        except asyncio.CancelledError:
            # Task was cancelled
            pass

    async def monitor(self):
        """Main monitoring loop"""
        self.is_running = True
        reconnect_attempts = 0
        current_delay = self.reconnect_delay
        last_save = datetime.now()
        
        while self.is_running:
            try:
                self.logger.info(f"Connecting to {self.websocket_url}")
                
                async with AsyncWebsocketClient(self.websocket_url) as client:
                    self.logger.info("Connected to XRPL")
                    # Ensure that target_wallet and follower_wallet are defined
                    if not hasattr(self, 'target_wallet') or not hasattr(self, 'follower_wallet'):
                        self.logger.error("Wallets are not initialized properly.")
                        raise Exception("Invalid configuration")

                    self.logger.info(f"Target wallet: {self.target_wallet}")
                    self.logger.info(f"Follower wallet: {self.follower_wallet.classic_address}")

                    # Subscribe to target wallet
                    subscribe_request = Subscribe(
                        accounts=[self.target_wallet],
                        streams=["transactions"]  
                    )                   
                    await client.send(subscribe_request)
                    self.logger.info(f"Subscribed to target wallet: {self.target_wallet}")
                    
                    # Send initial message to frontend
                    if hasattr(self, 'on_monitor_started') and callable(self.on_monitor_started):
                        self.logger.debug("Calling on_monitor_started callback")
                        try:
                            await self.on_monitor_started()
                            self.logger.debug("Monitor started callback executed successfully")
                        except Exception as e:
                            self.logger.error(f"Error in on_monitor_started callback: {str(e)}")
                    
                    # Start heartbeat
                    self.last_pong = asyncio.get_event_loop().time()
                    self.ping_task = asyncio.create_task(self._heartbeat(client))
                    
                    # Start periodic status updates
                    self.status_task = asyncio.create_task(self._periodic_status_update())
                    
                    # Reset reconnect counters on successful connection
                    reconnect_attempts = 0
                    current_delay = self.reconnect_delay
                    
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
                                
                                # Log incoming messages in debug mode
                                if self.logger.isEnabledFor(logging.DEBUG):
                                    self.logger.debug(f"Incoming Message: {data}")
                                    
                            except json.JSONDecodeError:
                                self.logger.error(f"Failed to parse message: {message}")
                                continue
                        else:
                            data = message
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(f"Incoming Binary Message: {data}")

                        # Process validated transactions
                        if data.get("type") == "transaction" and data.get("validated", False):
                            tx = data.get("transaction", {})
                            tx_type = tx.get("TransactionType")
                            
                            if tx_type == "TrustSet":
                                await self.handle_trust_set(tx)
                            elif tx_type == "Payment":
                                await self.handle_payment(tx)

                        # Check if it's time to save snapshot
                        now = datetime.now()
                        if (now - last_save).total_seconds() >= self.save_interval:
                            self._save_data()
                            last_save = now

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
                # Cleanup heartbeat and status tasks
                if self.ping_task:
                    self.ping_task.cancel()
                    try:
                        await self.ping_task
                    except asyncio.CancelledError:
                        pass
                    self.ping_task = None
                
                if self.status_task:
                    self.status_task.cancel()
                    try:
                        await self.status_task
                    except asyncio.CancelledError:
                        pass
                    self.status_task = None

    async def stop(self):
        """Gracefully stop the monitor"""
        self.logger.info("Stopping monitor...")
        self.is_running = False
        
        # Print final statistics
        print("\n📊 Final Statistics:")
        print(f"Total unique tokens discovered: {len(self.tokens)}")
        print(f"Tokens with {self.min_trust_lines}+ trust lines: {len(self.hot_tokens)}")
        print(f"Tokens with recorded trades: {len(self.traded_tokens)}")
        
        # Print details for hot tokens
        if self.hot_tokens:
            print("\n🔥 Hot Tokens:")
            for token_key in self.hot_tokens:
                token = self.tokens[token_key]
                trading = self.traded_tokens.get(token_key, {})
                print(f"\nToken: {token['currency']}")
                print(f"Issuer: {token['issuer']}")
                print(f"Trust lines: {token['trust_lines']}")
                print(f"First seen: {token['first_seen']}")
                if trading:
                    print(f"Total volume: {trading['total_volume']}")
                    print(f"Total trades: {trading['trades']}")
                    print(f"First trade: {trading['first_trade']}")

async def main():
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='XRPL Token Market Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--min-volume', type=float, help='Minimum trade volume to log')
    parser.add_argument('--min-trust-lines', type=int, help='Minimum trust lines to mark as hot token')
    args = parser.parse_args()

    # Load and validate configuration
    config = Config()
    if not config.validate():
        print("Invalid configuration. Exiting.")
        return

    # Override config with command line arguments if provided
    if args.min_volume:
        config.set('monitoring', 'min_trade_volume', str(args.min_volume))
    if args.min_trust_lines:
        config.set('monitoring', 'min_trust_lines', str(args.min_trust_lines))

    monitor = XRPLMarketMonitor(config, debug=args.debug)

    try:
        await monitor.monitor()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await monitor.stop()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())