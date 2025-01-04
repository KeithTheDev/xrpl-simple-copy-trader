import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional, List
from dataclasses import dataclass

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import Tx, AccountTx
from xrpl.models.response import Response

@dataclass
class TokenAnalysis:
    currency: str
    issuer: str
    creation_date: Optional[datetime]
    total_supply: Optional[Decimal]
    unique_holders: int
    creator_address: Optional[str]
    is_frozen: bool
    last_activity: Optional[datetime]
    current_price: Optional[Decimal]
    first_price: Optional[Decimal]
    first_price_time: Optional[datetime]
    max_price: Optional[Decimal]
    max_price_time: Optional[datetime]

class TokenAnalyzer:
    def __init__(
        self,
        websocket_url: str,
        db_handler,
        analysis_interval: int = 300,
        batch_size: int = 10,
        max_token_age_hours: int = 12
    ):
        self.websocket_url = websocket_url
        self.db = db_handler
        self.analysis_interval = analysis_interval
        self.batch_size = batch_size
        self.max_token_age_hours = max_token_age_hours
        
        self.logger = logging.getLogger('TokenAnalyzer')
        self.logger.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.is_running = False

    async def start(self):
        self.is_running = True
        self.logger.info("🚀 Starting token analyzer")

        async with AsyncWebsocketClient(self.websocket_url) as client:
            self.logger.info(f"📡 Connected to {self.websocket_url}")
            while self.is_running:
                try:
                    await self._analysis_loop(client)
                    self.logger.info(f"💤 Sleeping for {self.analysis_interval} seconds")
                    await asyncio.sleep(self.analysis_interval)
                except Exception as e:
                    self.logger.error(f"❌ Error in analysis loop: {e}")
                    await asyncio.sleep(10)

    async def stop(self):
        self.logger.info("🛑 Stopping analyzer")
        self.is_running = False

    async def _analysis_loop(self, client: AsyncWebsocketClient):
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        try:
            tokens = self.db.get_unanalyzed_tokens(cutoff_time)
            self.logger.info(f"📊 Found {len(tokens)} tokens to analyze")
        except Exception as e:
            self.logger.error(f"❌ Failed to get unanalyzed tokens: {e}")
            return

        for i in range(0, len(tokens), self.batch_size):
            batch = tokens[i:i + self.batch_size]
            self.logger.debug(f"Processing batch {i//self.batch_size + 1} ({len(batch)} tokens)")
            
            try:
                analyses = await asyncio.gather(
                    *[self._analyze_token(client, token) for token in batch],
                    return_exceptions=True
                )
            except Exception as e:
                self.logger.error(f"❌ Error analyzing batch: {e}")
                continue

            for token, analysis_res in zip(batch, analyses):
                currency = token.get('currency')
                issuer = token.get('issuer')

                if isinstance(analysis_res, Exception):
                    self.logger.error(f"❌ Exception analyzing {currency}:{issuer}: {analysis_res}")
                    continue

                if analysis_res is None:
                    self.logger.debug(f"⏭️ Skipped analysis for {currency}:{issuer}")
                    continue

                try:
                    current_price = await self._get_token_price(client, currency, issuer)
                    if current_price:
                        self.db.update_token_prices(currency, issuer, current_price)
                        self.logger.info(f"💰 Updated price for {currency}: {current_price} XRP")

                except Exception as e:
                    self.logger.error(f"❌ Failed to store analysis for {currency}:{issuer}: {e}")

    async def _analyze_token(self, client: AsyncWebsocketClient, token: Dict) -> Optional[TokenAnalysis]:
        """Analyze a single token"""
        currency = token.get('currency')
        issuer = token.get('issuer')
        tx_hash = token.get('first_seen_tx')

        self.logger.debug(f"🔍 Analyzing {currency}:{issuer}")

        if not tx_hash:
            self.logger.warning(f"⚠️ No transaction hash for {currency}:{issuer}")
            return None

        token_age = await self._get_token_age(client, tx_hash)
        if token_age is None:
            self.logger.warning(f"⚠️ Could not determine age for {currency}:{issuer}")
            return None

        self.logger.debug(f"Token age: {token_age:.2f}h (limit {self.max_token_age_hours}h)")
        if token_age > self.max_token_age_hours:
            self.logger.debug(f"⌛ Token {currency}:{issuer} is too old")
            self.db.mark_token_too_old(currency, issuer)
            return None

        self.logger.debug(f"📥 Fetching transactions for {issuer}")
        request = AccountTx(account=issuer, limit=20)
        
        try:
            response = await client.request(request)
        except Exception as e:
            self.logger.error(f"❌ Error requesting transactions for {issuer}: {e}")
            return None

        if response.status == 429:
            self.logger.warning(f"⚠️ Rate limited when fetching {currency}:{issuer}")
            return None

        if not response.is_successful():
            self.logger.error(f"❌ Failed to get transactions for {issuer}: {response.result}")
            return None

        tx_list = response.result.get('transactions', [])
        self.logger.debug(f"📝 Retrieved {len(tx_list)} transactions")
        
        analysis = TokenAnalysis(
            currency=currency,
            issuer=issuer,
            creation_date=None,
            total_supply=None,
            unique_holders=0,
            creator_address=None,
            is_frozen=False,
            last_activity=None,
            current_price=None,
            first_price=None,
            first_price_time=None,
            max_price=None,
            max_price_time=None
        )

        for tx_wrapper in tx_list:
            tx = tx_wrapper.get('tx', {})
            await self._update_analysis_from_tx(analysis, tx)

        return analysis

    async def _get_token_price(self, client, currency: str, issuer: str) -> Optional[Decimal]:
        """Get current DEX price for token in XRP"""
        from xrpl.models.requests import BookOffers
        
        try:
            request = BookOffers(
                taker_gets={"currency": "XRP"},
                taker_pays={
                    "currency": currency,
                    "issuer": issuer
                }
            )
            
            response = await client.request(request)
            if not response.is_successful():
                return None

            offers = response.result.get('offers', [])
            if not offers:
                return None

            best_offer = offers[0]
            xrp_amount = Decimal(str(best_offer['TakerGets'])) / Decimal('1000000')
            token_amount = Decimal(str(best_offer['TakerPays']['value']))
            
            return xrp_amount / token_amount

        except Exception as e:
            self.logger.error(f"Error getting price for {currency}: {e}")
            return None

    async def _get_token_age(self, client: AsyncWebsocketClient, tx_hash: str) -> Optional[float]:
        try:
            request = Tx(transaction=tx_hash)
            response = await client.request(request)

            if response.status == 429:
                self.logger.warning(f"⚠️ Rate limited for tx {tx_hash}")
                return None

            if not response.is_successful():
                self.logger.debug(f"Failed to get tx {tx_hash}: {response.result}")
                return None

            tx_date = response.result.get('date')
            if not tx_date:
                return None

            ripple_epoch = datetime(2000, 1, 1)
            tx_datetime = ripple_epoch + timedelta(seconds=tx_date)
            age_hours = (datetime.now() - tx_datetime).total_seconds() / 3600

            self.logger.debug(f"Token age from tx {tx_hash}: {age_hours:.2f}h")
            return age_hours

        except Exception as e:
            self.logger.error(f"❌ Error getting token age from {tx_hash}: {e}")
            return None

    async def _update_analysis_from_tx(self, analysis: TokenAnalysis, tx: Dict):
        try:
            tx_type = tx.get('TransactionType')
            tx_date = self._get_tx_datetime(tx)

            if tx_date:
                if not analysis.last_activity or tx_date > analysis.last_activity:
                    analysis.last_activity = tx_date
                if not analysis.creation_date or tx_date < analysis.creation_date:
                    analysis.creation_date = tx_date
                    analysis.creator_address = tx.get('Account')

            if tx_type == 'TrustSet':
                analysis.unique_holders += 1

            elif tx_type == 'AccountSet':
                flags = tx.get('Flags', 0)
                if flags & 0x00100000:  # Global Freeze flag
                    analysis.is_frozen = True

        except Exception as e:
            self.logger.error(f"❌ Error updating analysis from tx {tx.get('hash')}: {e}")

    @staticmethod
    def _get_tx_datetime(tx: Dict) -> Optional[datetime]:
        try:
            if 'date' in tx:
                ripple_epoch = datetime(2000, 1, 1)
                return ripple_epoch + timedelta(seconds=tx['date'])
        except Exception:
            pass
        return None