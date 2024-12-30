import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import AccountLines, BookOffers, GatewayBalances
from xrpl.models.amounts import IssuedCurrencyAmount
from config import Config
from utils.db_handler import XRPLDatabase

class XRPLTokenInfoCollector:
    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.websocket_url = config.get('network', 'websocket_url')
        self.db = XRPLDatabase()
        self.is_running = False
        
        # Setup logging
        self.logger = logging.getLogger('XRPLTokenInfoCollector')
        self._setup_logging(debug)
        
        # Collection intervals (in seconds)
        self.collection_interval = int(config.get('analytics', 'price_check_interval_minutes', default=5)) * 60
        
        # Track tokens we're monitoring
        self.monitored_tokens = set()
        
    def _setup_logging(self, debug: bool):
        """Setup logging with proper handlers"""
        self.logger.setLevel(logging.DEBUG if debug else logging.INFO)
        
        # Clear any existing handlers
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        
        # File handler
        log_config = self.config.get('logging', default={})
        if log_config.get('filename'):
            file_handler = logging.FileHandler(log_config['filename'])
            formatter = logging.Formatter(
                log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

    async def get_token_trust_lines(self, client: AsyncWebsocketClient, 
                                  issuer: str, currency: str) -> Optional[Dict]:
        """Get trust line information for a token"""
        try:
            request = AccountLines(
                account=issuer,
                ledger_index="validated"
            )
            response = await client.request(request)
            
            if not response.is_successful():
                self.logger.error(f"Failed to get trust lines: {response.result}")
                return None
            
            lines = response.result.get('lines', [])
            
            # Filter for specific currency and analyze trust lines
            relevant_lines = [
                line for line in lines 
                if line.get('currency') == currency
            ]
            
            total_limit = sum(
                Decimal(line.get('limit', '0')) 
                for line in relevant_lines
            )
            
            return {
                'trust_line_count': len(relevant_lines),
                'total_trust_line_limit': str(total_limit),
                'unique_trustors': len(set(line.get('account') for line in relevant_lines))
            }
            
        except Exception as e:
            self.logger.error(f"Error getting trust lines: {e}")
            return None

    async def get_token_price(self, client: AsyncWebsocketClient,
                            currency: str, issuer: str) -> Optional[Dict]:
        """Get current market price and liquidity for a token"""
        try:
            # Get XRP/Token order book
            book_request = BookOffers(
                taker_gets=IssuedCurrencyAmount(
                    currency=currency,
                    issuer=issuer,
                    value="1000000"  # Large value to get good price sample
                ),
                taker_pays="XRP",
                ledger_index="validated"
            )
            
            response = await client.request(book_request)
            
            if not response.is_successful():
                self.logger.error(f"Failed to get order book: {response.result}")
                return None
                
            offers = response.result.get('offers', [])
            
            if not offers:
                return {
                    'best_bid': None,
                    'best_ask': None,
                    'liquidity_xrp': "0",
                    'num_offers': 0
                }
            
            # Calculate metrics
            liquidity_xrp = sum(
                Decimal(offer.get('TakerPays', '0')) / 1_000_000  # Convert drops to XRP
                for offer in offers
            )
            
            # Get best bid/ask if available
            best_offer = offers[0]
            if 'TakerGets' in best_offer and 'TakerPays' in best_offer:
                # Calculate price in XRP per token
                amount_token = Decimal(best_offer['TakerGets']['value'])
                amount_xrp = Decimal(best_offer['TakerPays']) / 1_000_000
                price = amount_xrp / amount_token
            else:
                price = None
            
            return {
                'best_price_xrp': str(price) if price else None,
                'liquidity_xrp': str(liquidity_xrp),
                'num_offers': len(offers)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting token price: {e}")
            return None

    async def get_token_supply(self, client: AsyncWebsocketClient,
                             issuer: str, currency: str) -> Optional[Dict]:
        """Get token supply information"""
        try:
            request = GatewayBalances(
                account=issuer,
                ledger_index="validated"
            )
            
            response = await client.request(request)
            
            if not response.is_successful():
                self.logger.error(f"Failed to get gateway balances: {response.result}")
                return None
            
            obligations = response.result.get('obligations', {})
            supply = Decimal(obligations.get(currency, '0'))
            
            return {
                'total_supply': str(supply),
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting token supply: {e}")
            return None

    async def collect_token_info(self, client: AsyncWebsocketClient, 
                               currency: str, issuer: str) -> None:
        """Collect and store all available information for a token"""
        self.logger.info(f"Collecting info for {currency} ({issuer})")
        
        # Get trust line info
        trust_info = await self.get_token_trust_lines(client, issuer, currency)
        
        # Get price info
        price_info = await self.get_token_price(client, currency, issuer)
        
        # Get supply info
        supply_info = await self.get_token_supply(client, issuer, currency)
        
        if any([trust_info, price_info, supply_info]):
            # Combine all info
            token_info = {
                'currency': currency,
                'issuer': issuer,
                'timestamp': datetime.utcnow(),
                'trust_lines': trust_info,
                'price': price_info,
                'supply': supply_info
            }
            
            # Store in database
            self.db.analytics_add_token_info(token_info)
            
            # Log summary
            self.logger.info(f"\nToken Info Summary for {currency}:")
            if trust_info:
                self.logger.info(f"Trust lines: {trust_info['trust_line_count']}")
            if price_info and price_info['best_price_xrp']:
                self.logger.info(f"Price (XRP): {price_info['best_price_xrp']}")
                self.logger.info(f"Liquidity (XRP): {price_info['liquidity_xrp']}")
            if supply_info:
                self.logger.info(f"Total Supply: {supply_info['total_supply']}")

    async def monitor_tokens(self):
        """Main monitoring loop"""
        self.is_running = True
        
        while self.is_running:
            try:
                async with AsyncWebsocketClient(self.websocket_url) as client:
                    self.logger.info("Connected to XRPL")
                    
                    while self.is_running:
                        # Get list of tokens to monitor from database
                        hot_tokens = await self.db.get_hot_tokens()
                        
                        for token in hot_tokens:
                            if self.is_running:
                                await self.collect_token_info(
                                    client, 
                                    token['currency'], 
                                    token['issuer']
                                )
                        
                        # Wait for next collection interval
                        await asyncio.sleep(self.collection_interval)
                        
            except Exception as e:
                self.logger.error(f"Connection error: {e}")
                if self.is_running:
                    await asyncio.sleep(5)  # Wait before reconnecting

    async def stop(self):
        """Stop the collector"""
        self.logger.info("Stopping token info collector...")
        self.is_running = False

async def main():
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='XRPL Token Info Collector')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    # Load and validate configuration
    config = Config()
    if not config.validate():
        return

    collector = XRPLTokenInfoCollector(config, debug=args.debug)
    
    try:
        await collector.monitor_tokens()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await collector.stop()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())