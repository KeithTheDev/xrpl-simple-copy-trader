import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import BookOffers
from utils.db_handler import XRPLDatabase

class PriceMonitor:
    def __init__(
        self,
        websocket_url: str,
        db_handler: XRPLDatabase,
        poll_interval: int = 120, # Poll interval in seconds. Too low => will be rate limited.
        batch_size: int = 10,
        wait_between_query: int = 5, # Number of seconds to wait between every price query. Too low => will be rate limited
        min_price_change: Decimal = Decimal('0.05')
    ):
        self.websocket_url = websocket_url
        self.db = db_handler
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.wait_between_query = wait_between_query
        self.min_price_change = min_price_change
        
        # Set up logger
        self.logger = logging.getLogger('PriceMonitor')
        self.logger.setLevel(logging.DEBUG)
        
        # Console handler med all output
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.is_running = False

    async def start(self):
        self.is_running = True
        self.logger.info("🚀 Starting price monitor")

        async with AsyncWebsocketClient(self.websocket_url) as client:
            self.logger.info(f"📡 Connected to {self.websocket_url}")
            while self.is_running:
                try:
                    await self._price_check_loop(client)
                    self.logger.info(f"💤 Sleeping for {self.poll_interval} seconds...")
                    await asyncio.sleep(self.poll_interval)
                except Exception as e:
                    self.logger.error(f"❌ Error in price check loop: {e}")
                    await asyncio.sleep(10)

    async def stop(self):
        self.logger.info("🛑 Stopping price monitor")
        self.is_running = False

    async def _price_check_loop(self, client: AsyncWebsocketClient):
        active_tokens = self.db.get_active_tokens()
        self.logger.info(f"📊 Checking prices for {len(active_tokens)} tokens")
        
        for i in range(0, len(active_tokens), self.batch_size):
            batch = active_tokens[i:i + self.batch_size]
            self.logger.debug(f"Processing batch {i//self.batch_size + 1} ({len(batch)} tokens)")
            
            for token in batch:
                try:
                    self.logger.debug(f"Checking {token['currency']}...")
                    current_price = await self._get_token_price(
                        client,
                        token['currency'],
                        token['issuer']
                    )
                    
                    # Wait a number of seconds between every call, since we want to avoid being rate limited.
                    await asyncio.sleep(self.wait_between_query) 

                    if current_price is None:
                        self.logger.debug(f"No price found for {token['currency']}")
                        continue

                    self.logger.debug(f"{token['currency']}: Current price = {current_price} XRP")
                    prev_max = self.db.get_token_max_price(token['currency'], token['issuer'])
                    self.logger.debug(f"{token['currency']}: Previous max = {prev_max} XRP")

                    self.db.update_token_price(
                        currency=token['currency'],
                        issuer=token['issuer'],
                        price=current_price,
                        timestamp=datetime.now()
                    )

                    if prev_max is None or current_price > prev_max * (Decimal('1') + self.min_price_change):
                        self.db.update_token_max_price(
                            currency=token['currency'],
                            issuer=token['issuer'],
                            price=current_price,
                            timestamp=datetime.now()
                        )
                        self.logger.info(
                            f"🚀 New max price for {token['currency']}: {current_price} XRP "
                            f"(prev: {prev_max if prev_max else 'None'})"
                        )

                except Exception as e:
                    self.logger.error(f"❌ Error checking price for {token['currency']}: {e}")

    async def _get_token_price(
        self,
        client: AsyncWebsocketClient,
        currency: str,
        issuer: str
    ) -> Optional[Decimal]:
        try:
            request = BookOffers(
                taker_gets={"currency": "XRP"},
                taker_pays={
                    "currency": currency,
                    "issuer": issuer
                }
            )
            
            self.logger.debug(f"Querying order book for {currency}...")
            response = await client.request(request)
            if not response.is_successful():
                self.logger.debug(f"No successful response for {currency}")
                return None

            offers = response.result.get('offers', [])
            if not offers:
                self.logger.debug(f"No offers found for {currency}")
                return None

            best_offer = offers[0]
            xrp_amount = Decimal(str(best_offer['TakerGets'])) / Decimal('1000000')
            token_amount = Decimal(str(best_offer['TakerPays']['value']))
            price = xrp_amount / token_amount
            
            self.logger.debug(f"Price calculation for {currency}:")
            self.logger.debug(f"XRP amount: {xrp_amount}")
            self.logger.debug(f"Token amount: {token_amount}")
            self.logger.debug(f"Price: {price} XRP per token")
            
            return price

        except Exception as e:
            self.logger.error(f"Error getting price for {currency}: {e}")
            return None