import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from utils.db_handler import XRPLDatabase

class WalletAnalyzer:
    def __init__(
        self,
        db_handler: XRPLDatabase,
        analysis_interval: int = 3600,  # 1 hour
        min_trades: int = 5,
        min_roi: float = 2.0  # 200% minimum ROI to consider "successful"
    ):
        self.db = db_handler
        self.analysis_interval = analysis_interval
        self.min_trades = min_trades
        self.min_roi = min_roi
        self.logger = logging.getLogger('WalletAnalyzer')
        self.logger.setLevel(logging.DEBUG)

        self.is_running = False

    async def start(self):
        """Start the wallet analysis loop"""
        self.is_running = True
        self.logger.info("Starting wallet analyzer")

        while self.is_running:
            try:
                await self._analysis_loop()
                await asyncio.sleep(self.analysis_interval)
            except Exception as e:
                self.logger.error(f"Error in analysis loop: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        """Stop the analyzer gracefully"""
        self.is_running = False

    async def _analysis_loop(self):
        """Main analysis loop"""
        try:
            # Get wallets with recent activity
            active_wallets = await self._get_active_wallets()
            
            for wallet in active_wallets:
                wallet_stats = await self.analyze_wallet(wallet)
                if wallet_stats:
                    alpha_score = self._calculate_alpha_score(wallet_stats)
                    self.db.update_wallet_alpha_score(
                        wallet=wallet,
                        alpha_score=alpha_score,
                        calculation_time=datetime.now()
                    )

        except Exception as e:
            self.logger.error(f"Error in analysis loop: {e}")

    async def analyze_wallet(self, wallet: str) -> Optional[Dict]:
        """Analyze a wallet's trading performance"""
        try:
            # Get all trustlines created by wallet
            trustlines = self.db.get_wallet_trustlines(wallet)
            if not trustlines:
                return None

            successful_trades = 0
            total_roi = Decimal('0')
            early_adoptions = 0
            
            for trustline in trustlines:
                token_stats = await self._analyze_token_performance(
                    wallet,
                    trustline['currency'],
                    trustline['issuer'],
                    trustline['timestamp']
                )
                
                if token_stats:
                    if token_stats['roi'] >= self.min_roi:
                        successful_trades += 1
                        total_roi += token_stats['roi']
                    if token_stats['early_adopter']:
                        early_adoptions += 1

            if successful_trades < self.min_trades:
                return None

            return {
                'wallet': wallet,
                'successful_trades': successful_trades,
                'average_roi': total_roi / successful_trades if successful_trades > 0 else Decimal('0'),
                'early_adoptions': early_adoptions,
                'total_trustlines': len(trustlines)
            }

        except Exception as e:
            self.logger.error(f"Error analyzing wallet {wallet}: {e}")
            return None

    async def _analyze_token_performance(
        self,
        wallet: str,
        currency: str,
        issuer: str,
        trustline_time: datetime
    ) -> Optional[Dict]:
        """Analyze wallet's performance with a specific token"""
        try:
            # Get token's price history
            price_history = self.db.get_price_history(currency, issuer)
            if not price_history:
                return None

            # Get wallet's trades for this token
            trades = self.db.get_wallet_token_trades(wallet, currency, issuer)
            if not trades:
                return None

            # Calculate entry price (average of first N purchases)
            entry_price = self._calculate_entry_price(trades[:3])
            if not entry_price:
                return None

            # Get maximum price after entry
            max_price = self._get_max_price_after_time(price_history, trustline_time)
            if not max_price:
                return None

            # Calculate ROI
            roi = (max_price - entry_price) / entry_price

            # Determine if wallet was an early adopter
            total_trustlines = self.db.get_token_trustline_count(currency, issuer)
            early_adopter = self._is_early_adopter(trustline_time, total_trustlines)

            return {
                'currency': currency,
                'issuer': issuer,
                'entry_price': entry_price,
                'max_price': max_price,
                'roi': roi,
                'early_adopter': early_adopter
            }

        except Exception as e:
            self.logger.error(f"Error analyzing token performance: {e}")
            return None

    def _calculate_alpha_score(self, stats: Dict) -> float:
        """Calculate alpha score based on trading performance"""
        try:
            base_score = float(stats['average_roi']) * 0.4  # 40% weight on ROI
            success_rate = (stats['successful_trades'] / stats['total_trustlines']) * 0.3  # 30% weight
            early_rate = (stats['early_adoptions'] / stats['total_trustlines']) * 0.3  # 30% weight
            
            return base_score + success_rate + early_rate

        except Exception as e:
            self.logger.error(f"Error calculating alpha score: {e}")
            return 0.0

    def _is_early_adopter(self, trustline_time: datetime, total_trustlines: int) -> bool:
        """Determine if a trustline was created early in token's lifecycle"""
        return total_trustlines <= 10  # Consider first 10 trustlines as early adopters

    @staticmethod
    def _calculate_entry_price(trades: List[Dict]) -> Optional[Decimal]:
        """Calculate average entry price from initial trades"""
        if not trades:
            return None
            
        total_amount = Decimal('0')
        total_cost = Decimal('0')
        
        for trade in trades:
            total_amount += trade['amount']
            total_cost += trade['amount'] * trade['price_xrp']
            
        return total_cost / total_amount if total_amount > 0 else None

    @staticmethod
    def _get_max_price_after_time(
        price_history: List[Dict],
        start_time: datetime
    ) -> Optional[Decimal]:
        """Get maximum price after a specific time"""
        relevant_prices = [
            price['price'] for price in price_history 
            if price['timestamp'] > start_time
        ]
        return max(relevant_prices) if relevant_prices else None

    async def _get_active_wallets(self) -> List[str]:
        """Get list of wallets with recent activity"""
        cutoff = datetime.now() - timedelta(days=7)
        return self.db.get_active_wallets(cutoff)