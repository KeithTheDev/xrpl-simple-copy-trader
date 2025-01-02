# market_monitor.py

import asyncio
import json
from datetime import datetime
from typing import Dict, Set, Union
from decimal import Decimal
from dataclasses import dataclass

from xrpl.models.requests import Subscribe
from xrpl.wallet import Wallet

from utils.xrpl_base_monitor import XRPLBaseMonitor
from utils.xrpl_transaction_parser import XRPLTransactionParser, TrustSetInfo, PaymentInfo
from utils.xrpl_logger import XRPLLogger
from utils.token_analyzer import TokenAnalyzer
from config import Config
from utils.db_handler import XRPLDatabase

@dataclass
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
        self._is_filtered: bool = False  # Flag for filtered status

class XRPLMarketMonitor(XRPLBaseMonitor):
    """XRPL Market Monitor for analyzing token patterns and trends"""
    
    def __init__(self, config: Config, debug: bool = False):
        # Initialize base monitor
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
        
        # Set up logger
        log_config = config.get('logging', default={})
        self.logger = XRPLLogger(
            name='XRPLMarketMonitor',
            log_file=log_config.get('filename'),
            log_level=log_config.get('level', 'INFO'),
            debug=debug
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

    async def _subscribe(self, client) -> None:
        """Subscribe to all transactions on the network"""
        subscribe_request = Subscribe(streams=["transactions"])
        await client.send(subscribe_request)
        self.logger.success(f"Subscribed to XRPL transaction stream")
        
        # Start status updates
        self.status_task = asyncio.create_task(self._periodic_status_update())

    async def _handle_message(self, client, message: Union[str, Dict]) -> None:
        """Process incoming messages using the transaction parser"""
        try:
            # Convert message to dict if it's a string
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message

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
            self.logger.error_with_context("message handling", e)

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
                self.logger.log_trust_line_update(
                    trust_info.currency,
                    trust_info.issuer,
                    self.tokens[token_key].trust_lines,
                    removed=True
                )
        else:
            # New trust line
            if token_key not in self.tokens:
                # Check if token is already known to be too old
                if self.db.is_token_too_old(trust_info.currency, trust_info.issuer):
                    # Skip tracking if token is known to be too old
                    token = TokenInfo(trust_info.currency, trust_info.issuer)
                    token._is_filtered = True
                    self.tokens[token_key] = token
                    self.logger.debug(
                        f"⌛ Token {trust_info.currency}:{trust_info.issuer} skipped: previously marked as too old"
                    )
                    return
                    
                # New token - mark for analysis and start tracking
                self.db.mark_token_for_analysis(
                    trust_info.currency, 
                    trust_info.issuer,
                    trust_info.tx_hash
                )
                
                self.tokens[token_key] = TokenInfo(trust_info.currency, trust_info.issuer)
                self.logger.debug(
                    f"✨ New token {trust_info.currency}:{trust_info.issuer} marked for age analysis"
                )
                self.logger.log_token_discovery(
                    trust_info.currency,
                    trust_info.issuer,
                    trust_info.value
                )
            elif not self.tokens[token_key]._is_filtered:
                self.tokens[token_key].trust_lines += 1
                self._check_hot_token_status(token_key)

    async def handle_payment(self, payment_info: PaymentInfo) -> None:
        """Handle parsed Payment information"""
        token_key = self.tx_parser.get_token_key(payment_info.currency, payment_info.issuer)
        
        if token_key not in self.tokens or self.tokens[token_key]._is_filtered:
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
            self.logger.log_trade(
                token.currency,
                token.issuer,
                str(payment_info.value),
                str(token.total_volume),
                token.trades,
                token.trust_lines,
                is_hot=False
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
                is_hot=True
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
                time_to_hot
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
                if not v._is_filtered  # Only save non-filtered tokens
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
        # Count non-filtered tokens
        active_tokens = sum(1 for token in self.tokens.values() if not token._is_filtered)
        
        token_details = []
        if self.hot_tokens:
            for token_key in self.hot_tokens:
                token = self.tokens[token_key]
                if token._is_filtered:
                    continue
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
            total_tokens=active_tokens,
            hot_tokens=len(self.hot_tokens),
            token_details=token_details
        )

async def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='XRPL Token Market Monitor')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    config = Config()
    if not config.validate():
        return

    monitor = XRPLMarketMonitor(config, debug=args.debug)
    analyzer = TokenAnalyzer(
        websocket_url=config.get('network', 'websocket_url'),
        db_handler=XRPLDatabase(),
        analysis_interval=300,  # 5 minutes
        batch_size=10,
        max_token_age_hours=12
    )
    
    try:
        # Start both monitor and analyzer tasks
        await asyncio.gather(
            monitor.monitor(),
            analyzer.start()
        )
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await monitor.stop()
        await analyzer.stop()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())