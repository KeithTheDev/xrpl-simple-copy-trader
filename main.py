import asyncio
import json
import logging
import argparse
from typing import Any, Dict
from datetime import datetime

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import Subscribe
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
        
        # Track discovered tokens
        self.known_tokens = {}  # {currency: {'issuer': str, 'first_seen': datetime}}

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
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
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
        
        trust_set_tx = TrustSet(
            account=self.follower_wallet.classic_address,
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
        """Make a small purchase of the token"""
        amount = self.config.get('trading', 'initial_purchase_amount')
        
        if self.test_mode:
            self.logger.info(f"TEST MODE: Would make purchase of {currency} amount: {amount}")
            return

        self.logger.info(f"Attempting small purchase of {currency}...")
        
        payment = Payment(
            account=self.follower_wallet.classic_address,
            destination=issuer,
            amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=amount
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

        self.logger.info(f"Target wallet set new trust line:")
        self.logger.info(f"  Currency: {currency}")
        self.logger.info(f"  Issuer: {issuer}")
        self.logger.info(f"  Limit: {limit}")

        token_key = f"{currency}:{issuer}"
        if token_key not in self.known_tokens:
            self.known_tokens[token_key] = {
                'currency': currency,
                'issuer': issuer,
                'first_seen': datetime.now()
            }
            
            # Set our own trust line and make initial purchase
            try:
                await self.set_trust_line(client, currency, issuer, limit)
                await self.make_small_purchase(client, currency, issuer)
            except Exception as e:
                self.logger.error(f"Error handling trust set: {str(e)}")

    async def monitor(self):
        """Main monitoring loop"""
        self.is_running = True
        
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
                    self.logger.info(f"Subscribed to target wallet transactions")
                    
                    # Monitor incoming messages
                    async for message in client:
                        if not self.is_running:
                            break
                            
                        # Log raw message in debug mode
                        self.logger.debug(f"Received websocket message: {message}")
                            
                        # Handle message
                        if isinstance(message, str):
                            try:
                                data = json.loads(message)
                                self.logger.debug(f"Parsed JSON data: {json.dumps(data, indent=2)}")
                            except json.JSONDecodeError:
                                self.logger.error(f"Failed to parse message: {message}")
                                continue
                        else:
                            data = message
                            self.logger.debug(f"Received data object: {data}")

                        # Process transaction if appropriate
                        if data.get("type") == "transaction" and data.get("validated", False):
                            tx = data.get("transaction", {})
                            
                            # Handle transactions
                            tx_type = tx.get("TransactionType")
                            if tx_type == "TrustSet":
                                # Print all TrustSet transactions from our target wallet
                                if tx.get("Account") == self.target_wallet:
                                    limit_amount = tx.get("LimitAmount", {})
                                    if isinstance(limit_amount, dict):
                                        currency = limit_amount.get("currency")
                                        issuer = limit_amount.get("issuer")
                                        value = limit_amount.get("value")
                                        
                                        # If value is "0", the trust line is being removed
                                        if value == "0":
                                            print(f"\n🗑️  Target wallet removed trust line:")
                                            print(f"   Currency: {currency}")
                                            print(f"   Issuer: {issuer}\n")
                                        else:
                                            print(f"\n🔗 Target wallet set new trust line:")
                                            print(f"   Currency: {currency}")
                                            print(f"   Issuer: {issuer}")
                                            print(f"   Value: {value}\n")
                                
                                await self.handle_trust_set(client, tx)

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
        
        # Log final statistics
        self.logger.info("\nFinal Statistics:")
        self.logger.info(f"Total unique tokens discovered: {len(self.known_tokens)}")
        
        # Log details for each token
        for stats in self.known_tokens.values():
            self.logger.info(f"\nToken: {stats['currency']}")
            self.logger.info(f"  Issuer: {stats['issuer']}")
            self.logger.info(f"  First seen: {stats['first_seen']}")

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