import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass
import time
from decimal import Decimal

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
    analysis_timestamp: datetime = datetime.now()

class RateLimiter:
    def __init__(self, initial_delay: float = 1.0, max_delay: float = 60.0, backoff_factor: float = 2.0):
        self.current_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.last_request_time = 0.0
        self.consecutive_429s = 0

    async def wait_if_needed(self):
        """Enforce a delay before sending the next request, if required."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.current_delay:
            await asyncio.sleep(self.current_delay - time_since_last)
        self.last_request_time = time.time()

    def handle_success(self):
        """Reset the backoff if we had 429 errors but succeeded now."""
        if self.consecutive_429s > 0:
            self.current_delay = max(1.0, self.current_delay / self.backoff_factor)
            self.consecutive_429s = 0

    def handle_429(self):
        """Double the current delay (up to a max) each time we get a 429."""
        self.consecutive_429s += 1
        self.current_delay = min(self.max_delay, self.current_delay * self.backoff_factor)

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
        self.rate_limiter = RateLimiter()
        self.is_running = False

    async def start(self):
        """
        Start the main analysis loop (runs until stop() is called).
        Connects to the XRPL node via WebSocket and periodically calls the analysis routine.
        """
        self.is_running = True
        self.logger.info("Starting token analyzer loop")
        print("\033[1;95m>>> [TokenAnalyzer] The 'start' method has been called; beginning the analysis loop.\033[0m")

        async with AsyncWebsocketClient(self.websocket_url) as client:
            self.logger.info(f"Connected to XRPL node at {self.websocket_url}")
            print(f"\033[1;95m>>> [TokenAnalyzer] WebSocket connection established to {self.websocket_url}\033[0m")

            while self.is_running:
                try:
                    await self._analysis_loop(client)
                    self.logger.debug(f"Sleeping for {self.analysis_interval} seconds")
                    print(f"\033[1;95m>>> [TokenAnalyzer] Sleeping for {self.analysis_interval} seconds before next cycle.\033[0m")
                    await asyncio.sleep(self.analysis_interval)
                except Exception as e:
                    self.logger.error(f"Error in analysis loop: {e}", exc_info=True)
                    print(f"\033[1;95m>>> [TokenAnalyzer] Caught an exception in analysis loop: {e}\033[0m")
                    # Small delay to avoid tight looping if errors happen constantly
                    await asyncio.sleep(10)

    async def stop(self):
        """Stop the analysis loop gracefully."""
        self.logger.info("Stopping analyzer")
        print("\033[1;95m>>> [TokenAnalyzer] 'stop' called; halting the analysis loop.\033[0m")
        self.is_running = False

    async def _analysis_loop(self, client: AsyncWebsocketClient):
        """
        Main analysis loop: fetch pending or expired tokens, analyze them, and store results.
        """
        self.logger.debug("Starting analysis cycle")
        print("\033[1;95m>>> [TokenAnalyzer] Entering _analysis_loop...\033[0m")
        cutoff_time = datetime.now() - timedelta(hours=24)

        # Retrieve tokens that need analysis
        try:
            tokens = self.db.get_unanalyzed_tokens(cutoff_time)
            print(f"\033[1;95m>>> [TokenAnalyzer] get_unanalyzed_tokens returned {len(tokens)} tokens.\033[0m")
        except Exception as e:
            self.logger.error(f"Failed to get unanalyzed tokens: {e}", exc_info=True)
            print(f"\033[1;95m>>> [TokenAnalyzer] Exception fetching unanalyzed tokens: {e}\033[0m")
            return

        if not tokens:
            self.logger.debug("No unanalyzed tokens found for analysis")
            print("\033[1;95m>>> [TokenAnalyzer] No tokens found; nothing to analyze.\033[0m")
            return

        self.logger.debug(f"Found {len(tokens)} unanalyzed tokens to analyze")
        print(f"\033[1;95m>>> [TokenAnalyzer] Found {len(tokens)} tokens to analyze...\033[0m")

        # Process tokens in batches
        for i in range(0, len(tokens), self.batch_size):
            batch = tokens[i:i + self.batch_size]
            self.logger.debug(f"Processing batch of {len(batch)} tokens (starting at index {i})")
            print(f"\033[1;95m>>> [TokenAnalyzer] Processing batch of {len(batch)} tokens (index {i}-{i + len(batch) - 1})\033[0m")

            try:
                # Run each token analysis concurrently and capture exceptions
                analyses = await asyncio.gather(
                    *[self._analyze_token(client, token) for token in batch],
                    return_exceptions=True
                )
            except Exception as e:
                self.logger.error(f"Error analyzing batch: {e}", exc_info=True)
                print(f"\033[1;95m>>> [TokenAnalyzer] Exception when analyzing token batch: {e}\033[0m")
                continue

            # Store analysis results for each token
            for token, analysis_res in zip(batch, analyses):
                currency = token.get('currency')
                issuer = token.get('issuer')

                if isinstance(analysis_res, Exception):
                    # If _analyze_token() raised an exception
                    self.logger.error(f"Exception analyzing token {currency}:{issuer}: {analysis_res}", exc_info=True)
                    print(f"\033[1;95m>>> [TokenAnalyzer] Error while analyzing token {currency}:{issuer}: {analysis_res}\033[0m")
                    continue

                self.logger.debug(f"Analysis completed for {currency}:{issuer}")
                print(f"\033[1;95m>>> [TokenAnalyzer] Analysis completed for {currency}:{issuer}\033[0m")

                if analysis_res is None:
                    # Token is too old or its age couldn't be determined
                    self.logger.debug(f"No analysis stored for {currency}:{issuer}")
                    print(f"\033[1;95m>>> [TokenAnalyzer] No analysis stored for {currency}:{issuer} (skipped).\033[0m")
                    continue

                # Save the analysis to the database
                try:
                    result = self.db.store_token_analysis(
                        currency=analysis_res.currency,
                        issuer=analysis_res.issuer,
                        creation_date=analysis_res.creation_date,
                        total_supply=analysis_res.total_supply,
                        unique_holders=analysis_res.unique_holders,
                        creator_address=analysis_res.creator_address,
                        is_frozen=analysis_res.is_frozen,
                        last_activity=analysis_res.last_activity,
                        status="active"
                    )
                    if not result:
                        self.logger.error(f"Failed to store analysis for {currency}:{issuer}")
                        print(f"\033[1;95m>>> [TokenAnalyzer] Failed to store analysis for {currency}:{issuer}\033[0m")
                except Exception as e:
                    self.logger.error(f"Exception storing token analysis {currency}:{issuer}: {e}", exc_info=True)
                    print(f"\033[1;95m>>> [TokenAnalyzer] Exception storing analysis for {currency}:{issuer}: {e}\033[0m")

    async def _analyze_token(self, client: AsyncWebsocketClient, token: Dict) -> Optional['TokenAnalysis']:
        """
        Analyze a single token (age check, transaction inspection, etc.).
        Returns a TokenAnalysis object on success or None if analysis is skipped.
        """
        currency = token.get('currency')
        issuer = token.get('issuer')
        tx_hash = token.get('first_seen_tx')

        self.logger.debug(f"Starting analysis for {currency}:{issuer}")
        self.logger.debug(f"Token data: {token}")
        print(f"\033[1;95m>>> [TokenAnalyzer] _analyze_token called for {currency}:{issuer}\033[0m")

        # We need a transaction hash to determine age
        if not tx_hash:
            self.logger.warning(f"No transaction hash for {currency}:{issuer}. Cannot check age.")
            print(f"\033[1;95m>>> [TokenAnalyzer] Missing tx_hash for {currency}:{issuer} -> skipping.\033[0m")
            return None

        # Check token age
        token_age = await self._get_token_age(client, tx_hash)
        if token_age is None:
            self.logger.warning(f"Could not determine age for {currency}:{issuer}. Skipping analysis.")
            print(f"\033[1;95m>>> [TokenAnalyzer] Could not determine age for {currency}:{issuer}; skipping.\033[0m")
            return None

        self.logger.debug(f"Token {currency}:{issuer} age is {token_age:.2f}h (limit {self.max_token_age_hours}h)")
        print(f"\033[1;95m>>> [TokenAnalyzer] Age for {currency}:{issuer} is {token_age:.2f}h (limit {self.max_token_age_hours}).\033[0m")
        if token_age > self.max_token_age_hours:
            self.logger.debug(f"Token {currency}:{issuer} is too old; marking as too_old in the database.")
            print(f"\033[1;95m>>> [TokenAnalyzer] {currency}:{issuer} exceeded max age; marking as too_old.\033[0m")
            self.db.mark_token_too_old(currency, issuer)
            return None

        # Retrieve some transaction data for further analysis
        self.logger.debug(f"Fetching transactions for {issuer}")
        print(f"\033[1;95m>>> [TokenAnalyzer] Fetching transactions for issuer {issuer}...\033[0m")
        await self.rate_limiter.wait_if_needed()

        request = AccountTx(
            account=issuer,
            limit=20
        )
        try:
            response = await client.request(request)
        except Exception as e:
            self.logger.error(f"Error requesting AccountTx for {issuer}: {e}", exc_info=True)
            print(f"\033[1;95m>>> [TokenAnalyzer] Exception while requesting AccountTx for {issuer}: {e}\033[0m")
            return None

        # Check for rate limiting
        if response.status == 429:
            self.logger.warning(f"Rate limit (429) from XRPL when fetching {currency}:{issuer}")
            print(f"\033[1;95m>>> [TokenAnalyzer] Got 429 Rate Limit for {currency}:{issuer}.\033[0m")
            self.rate_limiter.handle_429()
            return None

        self.rate_limiter.handle_success()

        if not response.is_successful():
            self.logger.error(f"Error getting transactions for {issuer}: {response.result}")
            print(f"\033[1;95m>>> [TokenAnalyzer] Non-success response for {issuer}: {response.result}\033[0m")
            return None

        tx_list = response.result.get('transactions', [])
        tx_count = len(tx_list)
        self.logger.debug(f"Retrieved {tx_count} transactions for {currency}:{issuer}")
        print(f"\033[1;95m>>> [TokenAnalyzer] Retrieved {tx_count} transactions for {currency}:{issuer}\033[0m")

        analysis = TokenAnalysis(
            currency=currency,
            issuer=issuer,
            creation_date=None,
            total_supply=None,
            unique_holders=0,
            creator_address=None,
            is_frozen=False,
            last_activity=None,
            analysis_timestamp=datetime.now()
        )

        # Update analysis based on the transactions
        for i, tx_wrapper in enumerate(tx_list, 1):
            tx = tx_wrapper.get('tx', {})
            self.logger.debug(f"Processing transaction {i}/{tx_count} for {currency}:{issuer}, hash={tx.get('hash')}")
            print(f"\033[1;95m>>> [TokenAnalyzer] Processing TX {i}/{tx_count} for {currency}:{issuer} (hash={tx.get('hash')}).\033[0m")
            await self._update_analysis_from_tx(analysis, tx)

        self.logger.debug(
            f"Analysis results for {currency}:{issuer}:\n"
            f"  Holders: {analysis.unique_holders}\n"
            f"  Frozen: {analysis.is_frozen}\n"
            f"  Creation date: {analysis.creation_date}\n"
            f"  Last activity: {analysis.last_activity}"
        )
        print(
            f"\033[1;95m>>> [TokenAnalyzer] Finished analysis for {currency}:{issuer}.\n"
            f"    Holders: {analysis.unique_holders}\n"
            f"    Frozen: {analysis.is_frozen}\n"
            f"    Creation date: {analysis.creation_date}\n"
            f"    Last activity: {analysis.last_activity}\033[0m"
        )

        return analysis

    async def _get_token_age(self, client: AsyncWebsocketClient, tx_hash: str) -> Optional[float]:
        """
        Calculate token age in hours based on the transaction that first introduced the token.
        Returns None if the age could not be determined.
        """
        self.logger.debug(f"Fetching transaction {tx_hash} to calculate token age")
        print(f"\033[1;95m>>> [TokenAnalyzer] _get_token_age() called for TX {tx_hash}\033[0m")
        try:
            await self.rate_limiter.wait_if_needed()
            request = Tx(transaction=tx_hash)
            response = await client.request(request)
        except Exception as e:
            self.logger.error(f"Error fetching transaction {tx_hash}: {e}", exc_info=True)
            print(f"\033[1;95m>>> [TokenAnalyzer] Exception fetching TX {tx_hash}: {e}\033[0m")
            return None

        if response.status == 429:
            self.logger.warning(f"Rate limit (429) encountered for Tx {tx_hash}")
            print(f"\033[1;95m>>> [TokenAnalyzer] 429 Rate Limit for TX {tx_hash}\033[0m")
            self.rate_limiter.handle_429()
            return None

        self.rate_limiter.handle_success()

        if not response.is_successful():
            self.logger.debug(f"Failed to get transaction: {response.result}")
            print(f"\033[1;95m>>> [TokenAnalyzer] Failed to get TX {tx_hash}: {response.result}\033[0m")
            return None

        tx_date = response.result.get('date')
        if not tx_date:
            self.logger.debug("No 'date' field found in transaction response")
            print(f"\033[1;95m>>> [TokenAnalyzer] No 'date' in TX {tx_hash} response; cannot calculate age.\033[0m")
            return None

        try:
            # XRPL 'date' is the number of seconds since January 1, 2000.
            ripple_epoch = datetime(2000, 1, 1)
            tx_datetime = ripple_epoch + timedelta(seconds=tx_date)
        except Exception as e:
            self.logger.error(f"Error parsing date for transaction {tx_hash}: {e}", exc_info=True)
            print(f"\033[1;95m>>> [TokenAnalyzer] Error parsing date in TX {tx_hash}: {e}\033[0m")
            return None

        age_hours = (datetime.now() - tx_datetime).total_seconds() / 3600
        self.logger.debug(f"Calculated age for TX {tx_hash}: {age_hours:.2f} hours")
        print(f"\033[1;95m>>> [TokenAnalyzer] Calculated age for TX {tx_hash}: {age_hours:.2f} hours\033[0m")
        return age_hours

    async def _update_analysis_from_tx(self, analysis: TokenAnalysis, tx: Dict):
        """
        Update the analysis object based on a single transaction: freeze flags, holders, creation date, etc.
        """
        try:
            tx_type = tx.get('TransactionType')
            tx_date = self._get_tx_datetime(tx)

            if tx_date:
                # Update last_activity and creation_date
                if not analysis.last_activity or tx_date > analysis.last_activity:
                    analysis.last_activity = tx_date
                if not analysis.creation_date or tx_date < analysis.creation_date:
                    analysis.creation_date = tx_date
                    analysis.creator_address = tx.get('Account')

            # Simple example of counting new trust lines
            if tx_type == 'TrustSet':
                analysis.unique_holders += 1

            elif tx_type == 'AccountSet':
                flags = tx.get('Flags', 0)
                # 0x00100000 -> Global Freeze flag
                if flags & 0x00100000:
                    analysis.is_frozen = True

        except Exception as e:
            self.logger.error(f"Error updating analysis from TX {tx.get('hash')}: {e}", exc_info=True)
            print(f"\033[1;95m>>> [TokenAnalyzer] Exception updating analysis from TX {tx.get('hash')}: {e}\033[0m")

    @staticmethod
    def _get_tx_datetime(tx: Dict) -> Optional[datetime]:
        """Convert XRPL timestamp in a single transaction to a Python datetime."""
        try:
            if 'date' in tx:
                ripple_epoch = datetime(2000, 1, 1)
                return ripple_epoch + timedelta(seconds=tx['date'])
        except Exception:
            pass
        return None