import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Set

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import Subscribe
from config import Config

class XRPLMarketMonitor:
    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.websocket_url = config.get('network', 'websocket_url')
        self.is_running = False

        # Setup logging first
        self.logger = logging.getLogger('XRPLMarketMonitor')
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
        
        # Configuration
        self.min_trade_volume = float(config.get('monitoring', 'min_trade_volume', default=1000))
        self.min_trust_lines = int(config.get('monitoring', 'min_trust_lines', default=5))
        self.data_file = config.get('monitoring', 'data_file', default='token_data.json')
        self.save_interval = int(config.get('monitoring', 'save_interval_minutes', default=5)) * 60  # Convert to seconds
        self.last_save = datetime.now()
        
        # Load existing data or initialize new
        stored_data = self._load_data()
        
        # Track token data
        self.tokens = stored_data.get('tokens', {})
        self.hot_tokens = set(stored_data.get('hot_tokens', []))
        self.traded_tokens = stored_data.get('traded_tokens', {})
        
        # Track token data
        self.tokens = stored_data.get('tokens', {})
        self.hot_tokens = set(stored_data.get('hot_tokens', []))
        self.traded_tokens = stored_data.get('traded_tokens', {})
        
        # Convert stored datetime strings back to datetime objects
        for token_data in self.tokens.values():
            if isinstance(token_data.get('first_seen'), str):
                token_data['first_seen'] = datetime.fromisoformat(token_data['first_seen'])
                
        for trade_data in self.traded_tokens.values():
            if isinstance(trade_data.get('first_trade'), str):
                trade_data['first_trade'] = datetime.fromisoformat(trade_data['first_trade'])

        # Setup logging
        self.logger = logging.getLogger('XRPLMarketMonitor')
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

    def get_token_key(self, currency: str, issuer: str) -> str:
        """Create a unique key for a token"""
        return f"{currency}:{issuer}"
        
    def _load_data(self) -> Dict:
        """Load token data from JSON file"""
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.logger.info(f"Loaded data for {len(data.get('tokens', {}))} tokens")
                return data
        except FileNotFoundError:
            self.logger.info(f"No existing data file found at {self.data_file}, starting fresh")
            # Create empty file to prevent future FileNotFoundError
            with open(self.data_file, 'w') as f:
                json.dump({}, f)
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Error reading data file: {e}, starting fresh")
            return {}
            
    def _save_data(self):
        """Save token data to JSON file"""
        # Convert datetime objects to ISO format strings for JSON serialization
        data = {
            'tokens': {
                k: {**v, 'first_seen': v['first_seen'].isoformat()} 
                for k, v in self.tokens.items()
            },
            'hot_tokens': list(self.hot_tokens),
            'traded_tokens': {
                k: {**v, 'first_trade': v['first_trade'].isoformat()} 
                for k, v in self.traded_tokens.items()
            }
        }
        
        try:
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"Saved data for {len(self.tokens)} tokens")
        except Exception as e:
            self.logger.error(f"Error saving data: {e}")

    async def handle_trust_set(self, tx: Dict[str, Any]):
        """Handle TrustSet transactions to detect new tokens and track trust lines"""
        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        value = limit_amount.get("value")

        if not all([currency, issuer, value]):
            return

        token_key = self.get_token_key(currency, issuer)
        
        if value == "0":
            # Trust line removal
            if token_key in self.tokens:
                self.tokens[token_key]['trust_lines'] = max(0, self.tokens[token_key]['trust_lines'] - 1)
                print(f"\n🔥 Trust line removed for {currency}")
                print(f"   Issuer: {issuer}")
                print(f"   Remaining trust lines: {self.tokens[token_key]['trust_lines']}\n")
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
                print(f"\n🆕 New token discovered!")
                print(f"   Currency: {currency}")
                print(f"   Issuer: {issuer}")
                print(f"   First trust line value: {value}\n")
            else:
                # Increment trust lines
                self.tokens[token_key]['trust_lines'] += 1
                current_trust_lines = self.tokens[token_key]['trust_lines']
                
                # Check if token just became "hot"
                if current_trust_lines == self.min_trust_lines:
                    self.hot_tokens.add(token_key)
                    time_to_hot = datetime.now() - self.tokens[token_key]['first_seen']
                    print(f"\n🔥 Token reached {self.min_trust_lines} trust lines!")
                    print(f"   Currency: {currency}")
                    print(f"   Issuer: {issuer}")
                    print(f"   Time to reach {self.min_trust_lines} trust lines: {time_to_hot}\n")

    async def handle_payment(self, tx: Dict[str, Any]):
        """Handle Payment transactions to track token trading activity"""
        amount = tx.get("Amount")
        if not isinstance(amount, dict):  # Skip XRP payments
            return

        currency = amount.get("currency")
        issuer = amount.get("issuer")
        value = float(amount.get("value", 0))

        if not all([currency, issuer]) or value < self.min_trade_volume:
            return

        token_key = self.get_token_key(currency, issuer)
        
        # Only track trades for tokens we've seen trust lines for
        if token_key in self.tokens:
            # Initialize trading data if first trade
            if token_key not in self.traded_tokens:
                self.traded_tokens[token_key] = {
                    'total_volume': value,
                    'trades': 1,
                    'first_trade': datetime.now()
                }
                time_to_trade = self.traded_tokens[token_key]['first_trade'] - self.tokens[token_key]['first_seen']
                print(f"\n💰 First trade for token {currency}!")
                print(f"   Issuer: {issuer}")
                print(f"   Amount: {value}")
                print(f"   Time from first trust line to first trade: {time_to_trade}")
                if token_key in self.hot_tokens:
                    print(f"   ⚠️  This token has {self.tokens[token_key]['trust_lines']} trust lines!")
                print()
            else:
                # Update trading stats
                self.traded_tokens[token_key]['total_volume'] += value
                self.traded_tokens[token_key]['trades'] += 1
                
                # Log significant trades for hot tokens
                if token_key in self.hot_tokens:
                    print(f"\n💸 Hot token traded!")
                    print(f"   Currency: {currency}")
                    print(f"   Amount: {value}")
                    print(f"   Total volume: {self.traded_tokens[token_key]['total_volume']}")
                    print(f"   Total trades: {self.traded_tokens[token_key]['trades']}")
                    print(f"   Trust lines: {self.tokens[token_key]['trust_lines']}\n")

    async def monitor(self):
        """Main monitoring loop"""
        self.is_running = True
        
        while self.is_running:
            try:
                self.logger.info(f"Connecting to {self.websocket_url}")
                
                async with AsyncWebsocketClient(self.websocket_url) as client:
                    self.logger.info("Connected to XRPL")

                    # Subscribe to all transactions
                    subscribe_request = Subscribe(streams=["transactions"])
                    await client.send(subscribe_request)
                    self.logger.info("Subscribed to transaction stream")
                    
                    # Monitor incoming messages
                    async for message in client:
                        if not self.is_running:
                            break
                            
                        # Handle message
                        if isinstance(message, str):
                            try:
                                data = json.loads(message)
                            except json.JSONDecodeError:
                                self.logger.error(f"Failed to parse message: {message}")
                                continue
                        else:
                            data = message

                        # Process validated transactions
                        if data.get("type") == "transaction" and data.get("validated", False):
                            tx = data.get("transaction", {})
                            tx_type = tx.get("TransactionType")
                            
                            # Print full transaction for debugging
                            if tx:
                                print(f"\nTransaction:")
                                print(json.dumps(tx, indent=2))
                            else:
                                print("\nEmpty transaction data in:", json.dumps(data, indent=2))
                            
                            if tx_type == "TrustSet":
                                await self.handle_trust_set(tx)
                            elif tx_type == "Payment":
                                await self.handle_payment(tx)
                            
                            # Check if it's time to save data
                            now = datetime.now()
                            if (now - self.last_save).total_seconds() >= self.save_interval:
                                self._save_data()
                                self.last_save = now
                                self.logger.debug(f"Auto-saved data at {now}")

            except asyncio.CancelledError:
                self.logger.info("Monitoring cancelled...")
                break
            except Exception as e:
                self.logger.error(f"Connection error: {str(e)}")
                if self.is_running:
                    self.logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
                continue

    async def stop(self):
        """Gracefully stop the monitor"""
        self.logger.info("Stopping monitor...")
        self.is_running = False
        
        # Save data before stopping
        self._save_data()
        
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