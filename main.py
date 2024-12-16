import asyncio
import json
import logging
import argparse
from typing import Any, Dict

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import StreamParameter, Subscribe
from xrpl.models.transactions import Payment, TrustSet
from xrpl.wallet import Wallet

from config import Config

class XRPLTokenMonitor:
    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.target_wallet = config.get('wallets', 'target_wallet')
        self.follower_wallet = Wallet.from_seed(config.get('wallets', 'follower_seed'))
        self.websocket_url = config.get('network', 'websocket_url')
        self.client = None
        self.is_running = False
        self.reconnect_count = 0
        
        # Setup logging
        log_config = config.get('logging', default={})
        log_handlers = []
        
        # File handler
        if log_config.get('filename'):
            file_handler = logging.FileHandler(log_config['filename'])
            file_handler.setFormatter(logging.Formatter(log_config.get('format')))
            log_handlers.append(file_handler)
        
        # Console handler (always on for error and critical, optional for debug)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        if debug:
            console_handler.setLevel(logging.DEBUG)
        else:
            console_handler.setLevel(logging.ERROR)
        log_handlers.append(console_handler)
        
        # Setup root logger
        logging.basicConfig(
            level=log_config.get('level', 'INFO'),
            handlers=log_handlers,
            force=True
        )
        
        self.logger = logging.getLogger('XRPLMonitor')
        if debug:
            self.logger.info("Debug mode enabled")

    async def connect(self) -> bool:
        """Establish connection to XRPL with retry logic"""
        try:
            if self.client:
                await self.client.close()
            
            self.logger.info(f"Connecting to {self.websocket_url}...")
            self.client = AsyncWebsocketClient(self.websocket_url)
            await self.client.open()
            self.logger.info("Connected to XRPL")
            self.logger.info(f"Follower wallet address: {self.follower_wallet.classic_address}")

            subscribe_request = Subscribe(
                streams=[StreamParameter.TRANSACTIONS],
                accounts=[self.target_wallet]
            )
            
            response = await self.client.send(subscribe_request)
            self.logger.info(f"Subscribed to target wallet: {self.target_wallet}")
            
            self.reconnect_count = 0
            return True

        except Exception as e:
            self.logger.error(f"Connection error: {str(e)}")
            return False

    async def handle_transaction(self, tx: Dict[str, Any]):
        """Process incoming transactions"""
        transaction_data = tx.get("transaction", {})
        if transaction_data.get("TransactionType") == "TrustSet" and transaction_data.get("Account") == self.target_wallet:
            await self.handle_trust_set(transaction_data)

    async def handle_trust_set(self, tx: Dict[str, Any]):
        """Handle TrustSet transactions"""
        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        limit = limit_amount.get("value")

        if not all([currency, issuer, limit]):
            return

        self.logger.info(f"Detected new trust line from target wallet:")
        self.logger.info(f"Currency: {currency}")
        self.logger.info(f"Issuer: {issuer}")
        self.logger.info(f"Limit: {limit}")

        try:
            await self.set_trust_line(currency, issuer, limit)
            await self.make_small_purchase(currency, issuer)
        except Exception as e:
            self.logger.error(f"Error handling trust set: {str(e)}")

    async def set_trust_line(self, currency: str, issuer: str, limit: str):
        """Set a trust line for the token"""
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
                client=self.client,
                wallet=self.follower_wallet
            )
            result = response.result.get('meta', {}).get('TransactionResult')
            self.logger.info(f"Trust line set: {result}")
            
            if result != "tesSUCCESS":
                raise Exception(f"Trust line setting failed: {result}")
                
        except Exception as e:
            self.logger.error(f"Error setting trust line: {str(e)}")
            raise

    async def make_small_purchase(self, currency: str, issuer: str):
        """Make a small purchase of the token"""
        self.logger.info(f"Attempting small purchase of {currency}...")
        
        payment = Payment(
            account=self.follower_wallet.classic_address,
            destination=issuer,
            amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=self.config.get('trading', 'initial_purchase_amount')
            )
        )
        
        try:
            response = await submit_and_wait(
                transaction=payment,
                client=self.client,
                wallet=self.follower_wallet
            )
            result = response.result.get('meta', {}).get('TransactionResult')
            self.logger.info(f"Purchase attempt result: {result}")
            
            if result != "tesSUCCESS":
                raise Exception(f"Purchase failed: {result}")
                
        except Exception as e:
            self.logger.error(f"Error making purchase: {str(e)}")
            raise

    async def monitor(self):
        """Main monitoring loop with reconnection logic"""
        self.is_running = True
        self.logger.info("Starting monitoring...")
        
        while self.is_running:
            try:
                if not self.client or not self.client.is_open():
                    max_attempts = self.config.get('network', 'max_reconnect_attempts')
                    if self.reconnect_count >= max_attempts:
                        self.logger.error(f"Maximum reconnection attempts ({max_attempts}) reached. Stopping monitor...")
                        self.is_running = False
                        break
                    
                    self.logger.info(f"Attempting reconnection ({self.reconnect_count + 1}/{max_attempts})...")
                    if not await self.connect():
                        self.reconnect_count += 1
                        await asyncio.sleep(self.config.get('network', 'reconnect_delay_seconds'))
                        continue

                async for message in self.client:
                    if not self.is_running:
                        break
                        
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            self.logger.error(f"Failed to parse message: {message}")
                            continue
                    else:
                        data = message
                    
                    if "type" in data and data["type"] == "transaction":
                        await self.handle_transaction(data)
                    
            except asyncio.CancelledError:
                self.logger.info("Monitoring cancelled...")
                self.is_running = False
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {str(e)}")
                self.reconnect_count += 1
                await asyncio.sleep(self.config.get('network', 'reconnect_delay_seconds'))
                continue

        if self.client:
            await self.client.close()

    async def stop(self):
        """Gracefully stop the monitor"""
        self.is_running = False
        if self.client:
            await self.client.close()

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='XRPL Token Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    # Load and validate configuration
    config = Config()
    if not config.validate():
        return

    monitor = XRPLTokenMonitor(config, debug=args.debug)
    try:
        await monitor.connect()
        await monitor.monitor()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await monitor.stop()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
    finally:
        if monitor.client:
            await monitor.client.close()

if __name__ == "__main__":
    asyncio.run(main())