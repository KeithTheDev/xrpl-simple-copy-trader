# market_monitor.py

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Set
from decimal import Decimal

from xrpl.wallet import Wallet

from utils.xrpl_base_monitor import XRPLBaseMonitor
from xrpl_transaction_parser import XRPLTransactionParser, TrustSetInfo, PaymentInfo
from config import Config
from db_handler import XRPLDatabase

class TokenInfo:
    """Class to track token information"""
    def __init__(self, currency: str, issuer: str):
        self.currency = currency
        self.issuer = issuer
        self.first_seen = datetime.now()
        self.trust_lines = 1
        self.total_volume = Decimal('0')
        self.trades = 0
        self.first_trade: datetime = None

class XRPLMarketMonitor(XRPLBaseMonitor):
    def __init__(self, config: Config, debug: bool = False):
        super().__init__(
            websocket_url=config.get('network', 'websocket_url'),
            logger_name='XRPLMarketMonitor',
            max_reconnect_attempts=int(config.get('network', 'max_reconnect_attempts', fallback=5)),
            reconnect_delay=int(config.get('network', 'reconnect_delay_seconds', fallback=5))
        )
        
        # Initialize components
        self.config = config
        self.db = XRPLDatabase()
        self.tx_parser = XRPLTransactionParser()
        
        # Set debug level if needed
        if debug:
            self.logger.setLevel(logging.DEBUG)
            self.logger.info("Debug mode enabled")

        # Load configuration
        self.min_trade_volume = float(config.get('monitoring', 'min_trade_volume', fallback=1000))
        self.min_trust_lines = int(config.get('monitoring', 'min_trust_lines', fallback=5))
        self.data_file = config.get('monitoring', 'data_file', fallback='token_data.json')
        self.save_interval = int(config.get('monitoring', 'save_interval_minutes', fallback=5)) * 60

        # State tracking
        self.tokens: Dict[str, TokenInfo] = {}
        self.hot_tokens: Set[str] = set()
        self.last_save = datetime.now()
        self.status_task = None

        # Initialize wallets
        self._setup_wallets(config)

    def _setup_wallets(self, config: Config) -> None:
        """Initialize wallets from configuration"""
        self.target_wallet = config.get('wallets', 'target_wallet')
        follower_seed = config.get('wallets', 'follower_seed')

        if not all([self.target_wallet, follower_seed]):
            raise ValueError("Missing required wallet configuration")

        try:
            self.follower_wallet = Wallet.from_seed(follower_seed)
            self.logger.info(f"Follower wallet initialized: {self.follower_wallet.classic_address}")
        except Exception as e:
            self.logger.error(f"Invalid follower_seed format: {e}")
            raise

    async def _subscribe(self, client) -> None:
        """Set up subscriptions and start status updates"""
        subscribe_request = Subscribe(accounts=[self.target_wallet], streams=["transactions"])
        await client.send(subscribe_request)
        self.logger.info(f"Subscribed to target wallet: {self.target_wallet}")
        
        # Start status updates
        self.status_task = asyncio.create_task(self._periodic_status_update())

    async def _handle_message(self, client, message: str) -> None:
        """Process incoming messages using the transaction parser"""
        try:
            data = json.loads(message)
            tx_type, parsed_info = self.tx_parser.parse_transaction(data, self.min_trade_volume)
            
            if tx_type == "TrustSet" and isinstance(parsed_info, TrustSetInfo):
                await self.handle_trust_set(parsed_info)
            elif tx_type == "Payment" and isinstance(parsed_info, PaymentInfo):
                await self.handle_payment(parsed_info)
            
            # Check if it's time to save data
            now = datetime.now()
            if (now - self.last_save).total_seconds() >= self.save_interval:
                self._save_data()
                self.last_save = now
                
        except json.JSONDecodeError:
            self.logger.error("Failed to parse message")
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")

    async def handle_trust_set(self, trust_info: TrustSetInfo) -> None:
        """Handle parsed TrustSet information"""
        token_key = self.tx_parser.get_token_key(trust_info.currency, trust_info.issuer)
        
        # Store in analytics database
        self.db.analytics_add_trust_line(
            currency=trust_info.currency,
            issuer=trust_info.issuer,
            wallet=trust_info.wallet,
            limit=trust_info.value,
            tx_hash=trust_info.tx_hash
        )
        
        if trust_info.value == "0":
            # Trust line removal
            if token_key in self.tokens:
                self.tokens[token_key].trust_lines = max(0, self.tokens[token_key].trust_lines - 1)
                self._log_trust_removal(trust_info)
        else:
            # New trust line
            if token_key not in self.tokens:
                self.tokens[token_key] = TokenInfo(trust_info.currency, trust_info.issuer)
                self._log_new_token(trust_info)
            else:
                self.tokens[token_key].trust_lines += 1
                self._check_hot_token_status(token_key)

    async def handle_payment(self, payment_info: PaymentInfo) -> None:
        """Handle parsed Payment information"""
        token_key = self.tx_parser.get_token_key(payment_info.currency, payment_info.issuer)
        
        if token_key not in self.tokens:
            return

        # Store in analytics database
        self.db.analytics_add_trade(
            currency=payment_info.currency,
            issuer=payment_info.issuer,
            amount=str(payment_info.delivered_amount),
            price_xrp="0",  # Will need price monitoring
            buyer=payment_info.buyer,
            seller=payment_info.seller,
            tx_hash=payment_info.tx_hash
        )

        # Update token tracking
        token = self.tokens[token_key]
        if token.first_trade is None:
            token.first_trade = payment_info.timestamp
            self._log_first_trade(token_key, payment_info)
        
        token.total_volume += payment_info.value
        token.trades += 1
        
        if token_key in self.hot_tokens:
            self._log_hot_token_trade(token_key, payment_info)

    def _check_hot_token_status(self, token_key: str) -> None:
        """Check if a token has reached hot status"""
        token = self.tokens[token_key]
        if token.trust_lines == self.min_trust_lines:
            self.hot_tokens.add(token_key)
            time_to_hot = datetime.now() - token.first_seen
            self.logger.info(f"\n🔥 Token reached {self.min_trust_lines} trust lines!")
            self.logger.info(f"   Currency: {token.currency}")
            self.logger.info(f"   Issuer: {token.issuer}")
            self.logger.info(f"   Time to reach threshold: {time_to_hot}\n")

    def _save_data(self) -> None:
        """Save current state to JSON file"""
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'tokens': {
                k: {
                    'currency': v.currency,
                    'issuer': v.issuer,
                    'first_seen': v.first_seen.isoformat(),
                    'trust_lines': v.trust_lines,
                    'total_volume': str(v.total_volume),
                    'trades': v.trades,
                    'first_trade': v.first_trade.isoformat() if v.first_trade else None
                } for k, v in self.tokens.items()
            },
            'hot_tokens': list(self.hot_tokens)
        }
        
        try:
            with open(self.data_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
            self.logger.debug(f"State snapshot saved to {self.data_file}")
        except Exception as e:
            self.logger.error(f"Error saving state snapshot: {e}")

    async def _periodic_status_update(self) -> None:
        """Print periodic status updates"""
        try:
            while self.is_running:
                await asyncio.sleep(300)  # 5 minutes
                self._print_status_update()
        except asyncio.CancelledError:
            pass

    def _print_status_update(self) -> None:
        """Print current monitoring status"""
        yellow = "\033[93m"
        reset = "\033[0m"
        
        status = [
            f"{yellow}{'='*50}",
            f"Status Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            f"{'='*50}",
            f"Tracking {len(self.tokens)} tokens total",
            f"Hot tokens (>= {self.min_trust_lines} trust lines): {len(self.hot_tokens)}"
        ]

        if self.hot_tokens:
            status.append("\nHot Token Details:")
            for token_key in self.hot_tokens:
                token = self.tokens[token_key]
                status.extend([
                    f"\n🔥 {token.currency}",
                    f"   Issuer: {token.issuer}",
                    f"   Trust lines: {token.trust_lines}",
                    f"   Age: {datetime.now() - token.first_seen}",
                    f"   Trade volume: {token.total_volume}",
                    f"   Number of trades: {token.trades}"
                ])
                if token.first_trade:
                    status.append(f"   Time to first trade: {token.first_trade - token.first_seen}")

        status.extend([f"\n{'='*50}{reset}"])
        print("\n".join(status))

    # Logging helper methods
    def _log_trust_removal(self, trust_info: TrustSetInfo) -> None:
        self.logger.info(f"\n🔥 Trust line removed for {trust_info.currency}")
        self.logger.info(f"   Issuer: {trust_info.issuer}")
        self.logger.info(f"   Remaining trust lines: {self.tokens[self.tx_parser.get_token_key(trust_info.currency, trust_info.issuer)].trust_lines}\n")

    def _log_new_token(self, trust_info: TrustSetInfo) -> None:
        self.logger.info(f"\n🆕 New token discovered!")
        self.logger.info(f"   Currency: {trust_info.currency}")
        self.logger.info(f"   Issuer: {trust_info.issuer}")
        self.logger.info(f"   First trust line value: {trust_info.value}\n")

    def _log_first_trade(self, token_key: str, payment_info: PaymentInfo) -> None:
        token = self.tokens[token_key]
        self.logger.info(f"\n💰 First trade for token {token.currency}!")
        self.logger.info(f"   Issuer: {token.issuer}")
        self.logger.info(f"   Amount: {payment_info.value}")
        self.logger.info(f"   Time from first trust line: {payment_info.timestamp - token.first_seen}")
        if token_key in self.hot_tokens:
            self.logger.info(f"   ⚠️  This token has {token.trust_lines} trust lines!")
        self.logger.info("")

    def _log_hot_token_trade(self, token_key: str, payment_info: PaymentInfo) -> None:
        token = self.tokens[token_key]
        self.logger.info(f"\n💸 Hot token traded!")
        self.logger.info(f"   Currency: {token.currency}")
        self.logger.info(f"   Amount: {payment_info.value}")
        self.logger.info(f"   Total volume: {token.total_volume}")
        self.logger.info(f"   Total trades: {token.trades}")
        self.logger.info(f"   Trust lines: {token.trust_lines}\n")

async def main():
    import argparse
    parser = argparse.ArgumentParser(description='XRPL Token Market Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    config = Config()
    if not config.validate():
        return

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