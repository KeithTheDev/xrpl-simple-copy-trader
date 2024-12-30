# memecoin_monitor.py

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Set, Union
from decimal import Decimal

from xrpl.models.requests import Subscribe
from xrpl.wallet import Wallet

from utils.xrpl_base_monitor import XRPLBaseMonitor
from utils.xrpl_transaction_parser import XRPLTransactionParser, TrustSetInfo, PaymentInfo
from utils.xrpl_logger import XRPLLogger
from config import Config
from utils.db_handler import XRPLDatabase

class TokenInfo:
    """Class to track token information"""
    def __init__(self, currency: str, issuer: str):
        self.currency = currency
        self.issuer = issuer
        self.first_seen = datetime.now()
        self.trust_lines = 1
        self.total_volume = Decimal('0')
        self.trades = 0
        self.first_trade: Optional[datetime] = None

class XRPLTokenMonitor(XRPLBaseMonitor):
    """XRPL Token Monitor for following trust lines and trading"""
    
    def __init__(self, config: Config, debug: bool = False, test_mode: bool = False):
        # Initialize base monitor
        super().__init__(
            websocket_url=config.get('network', 'websocket_url'),
            logger_name='XRPLTokenMonitor',
            max_reconnect_attempts=int(config.get('network', 'max_reconnect_attempts', fallback=5)),
            reconnect_delay=int(config.get('network', 'reconnect_delay_seconds', fallback=5))
        )
        
        # Initialize components
        self.config = config
        self.db = XRPLDatabase()
        self.tx_parser = XRPLTransactionParser()
        
        # Set up logger
        log_config = config.get('logging', default={})
        self.logger = XRPLLogger(
            name='XRPLTokenMonitor',
            log_file=log_config.get('filename'),
            log_level=log_config.get('level', 'INFO'),
            debug=debug,
            test_mode=test_mode
        )

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
        self.test_mode = test_mode

        # Initialize wallets
        self._setup_wallets(config)
        
        # Callbacks for UI integration
        self.on_trust_line_created = None
        self.on_monitor_started = None

    def _setup_wallets(self, config: Config) -> None:
        """Initialize wallets from configuration"""
        self.target_wallet = config.get('wallets', 'target_wallet')
        follower_seed = config.get('wallets', 'follower_seed')

        if not all([self.target_wallet, follower_seed]):
            raise ValueError("Missing required wallet configuration")

        try:
            self.follower_wallet = Wallet.from_seed(follower_seed)
            self.logger.success(f"Follower wallet initialized: {self.follower_wallet.classic_address}")
        except Exception as e:
            self.logger.error_with_context("wallet initialization", e)
            raise

    async def _subscribe(self, client) -> None:
        """Subscribe to target wallet transactions"""
        subscribe_request = Subscribe(accounts=[self.target_wallet])
        await client.send(subscribe_request)
        self.logger.success(f"Subscribed to target wallet: {self.target_wallet}")
        
        # Start status updates
        self.status_task = asyncio.create_task(self._periodic_status_update())
        
        # Notify that monitor has started
        if self.on_monitor_started:
            await self.on_monitor_started()

    async def _handle_message(self, client, message: Union[str, Dict]) -> None:
        """Process incoming messages using the transaction parser"""
        try:
            # If message is already a dict, use it directly, otherwise parse it
            data = json.loads(message) if isinstance(message, str) else message
            
            # Handle pong responses first
            if isinstance(data, dict) and data.get("type") == "response":
                self.last_pong = asyncio.get_event_loop().time()
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug("Pong received")
                return
            
            tx_type, parsed_info = self.tx_parser.parse_transaction(
                data,
                min_payment_value=self.min_trade_volume,
                test_mode=self.test_mode
            )
            
            if tx_type == "TrustSet" and isinstance(parsed_info, TrustSetInfo):
                await self.handle_trust_set(parsed_info)
                if self.on_trust_line_created:
                    await self.on_trust_line_created(data.get("transaction", {}))
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
            self.logger.error_with_context("message handling", e)

    async def handle_trust_set(self, trust_info: TrustSetInfo) -> None:
        """Handle parsed TrustSet information"""
        token_key = self.tx_parser.get_token_key(trust_info.currency, trust_info.issuer)
        
        # Store in database
        self.db.add_trustline(
            currency=trust_info.currency,
            issuer=trust_info.issuer,
            limit=trust_info.value,
            tx_hash=trust_info.tx_hash,
            test_mode=self.test_mode
        )
        
        if trust_info.value == "0":
            # Trust line removal
            if token_key in self.tokens:
                self.tokens[token_key].trust_lines = max(0, self.tokens[token_key].trust_lines - 1)
                self.logger.log_trust_line_update(
                    trust_info.currency,
                    trust_info.issuer,
                    self.tokens[token_key].trust_lines,
                    removed=True,
                    test_mode=self.test_mode
                )
        else:
            # New trust line
            if token_key not in self.tokens:
                self.tokens[token_key] = TokenInfo(trust_info.currency, trust_info.issuer)
                self.logger.log_token_discovery(
                    trust_info.currency,
                    trust_info.issuer,
                    trust_info.value,
                    test_mode=self.test_mode
                )
            else:
                self.tokens[token_key].trust_lines += 1
                self._check_hot_token_status(token_key)

    async def handle_payment(self, payment_info: PaymentInfo) -> None:
        """Handle parsed Payment information"""
        token_key = self.tx_parser.get_token_key(payment_info.currency, payment_info.issuer)
        
        if token_key not in self.tokens:
            return

        # Store in database
        self.db.add_purchase(
            currency=payment_info.currency,
            issuer=payment_info.issuer,
            amount=str(payment_info.delivered_amount),
            cost_xrp="0",  # Will need price monitoring
            tx_hash=payment_info.tx_hash,
            test_mode=self.test_mode
        )

        # Update token tracking
        token = self.tokens[token_key]
        if token.first_trade is None:
            token.first_trade = payment_info.timestamp
            self.logger.log_trade(
                token.currency,
                token.issuer,
                str(payment_info.value),
                str(token.total_volume),
                token.trades,
                token.trust_lines,
                is_hot=False,
                test_mode=self.test_mode
            )
        
        token.total_volume += payment_info.value
        token.trades += 1
        
        if token_key in self.hot_tokens:
            self.logger.log_trade(
                token.currency,
                token.issuer,
                str(payment_info.value),
                str(token.total_volume),
                token.trades,
                token.trust_lines,
                is_hot=True,
                test_mode=self.test_mode
            )

    def _check_hot_token_status(self, token_key: str) -> None:
        """Check if a token has reached hot status"""
        token = self.tokens[token_key]
        if token.trust_lines == self.min_trust_lines:
            self.hot_tokens.add(token_key)
            time_to_hot = datetime.now() - token.first_seen
            self.logger.log_hot_token(
                token.currency,
                token.issuer,
                token.trust_lines,
                time_to_hot,
                test_mode=self.test_mode
            )

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
            self.logger.error_with_context("save data", e)

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
        token_details = []
        if self.hot_tokens:
            for token_key in self.hot_tokens:
                token = self.tokens[token_key]
                details = [
                    f"\n🔥 {token.currency}",
                    f"   Issuer: {token.issuer}",
                    f"   Trust lines: {token.trust_lines}",
                    f"   Age: {datetime.now() - token.first_seen}",
                    f"   Trade volume: {token.total_volume}",
                    f"   Number of trades: {token.trades}"
                ]
                if token.first_trade:
                    details.append(f"   Time to first trade: {token.first_trade - token.first_seen}")
                token_details.extend(details)

        self.logger.log_status_update(
            total_tokens=len(self.tokens),
            hot_tokens=len(self.hot_tokens),
            token_details=token_details
        )

    async def stop(self) -> None:
        """Stop the monitor gracefully"""
        self.logger.info("Stopping monitor...")
        await super().stop()
        if self.status_task:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass

async def main():
    import argparse
    parser = argparse.ArgumentParser(description='XRPL Token Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('-t', '--test', action='store_true', help='Enable test mode')
    args = parser.parse_args()

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