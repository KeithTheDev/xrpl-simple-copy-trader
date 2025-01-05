# wallet_scorer.py

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Set
from pathlib import Path
from bson.decimal128 import Decimal128

from utils.db_handler import XRPLDatabase

class WalletScorer:
    """Analyzes wallet behavior and scores wallets based on their success with new tokens"""
    
    def __init__(
        self,
        db_handler: XRPLDatabase,
        analysis_interval: int = 180,  # 3 minute
        min_trades: int = 5,            # Minimum trades to be considered
        min_roi: float = 2.0,           # 200% ROI threshold
        early_adopter_max: int = 10,    # First N trustlines considered "early"
        output_file: str = "alpha_wallets.txt"
    ):
        self.db = db_handler
        self.analysis_interval = analysis_interval
        self.min_trades = min_trades
        self.min_roi = min_roi
        self.early_adopter_max = early_adopter_max
        self.output_file = output_file
        
        self.logger = logging.getLogger('WalletScorer')
        self.logger.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.is_running = False

    async def start(self):
        """Start the wallet scoring loop"""
        self.is_running = True
        self.logger.info("🚀 Starting wallet scorer")

        while self.is_running:
            try:
                await self._scoring_loop()
                self.logger.info(f"💤 Sleeping for {self.analysis_interval} seconds")
                await asyncio.sleep(self.analysis_interval)
            except Exception as e:
                self.logger.error(f"❌ Error in scoring loop: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        """Stop the scorer gracefully"""
        self.logger.info("🛑 Stopping wallet scorer")
        self.is_running = False

    async def _scoring_loop(self):
        """Main scoring loop"""
        try:
            cutoff = datetime.now() - timedelta(days=30)
            active_wallets = self.db.get_active_wallets(cutoff)
            self.logger.info(f"📊 Found {len(active_wallets)} active wallets to analyze")

            scored_wallets = []
            for i, wallet in enumerate(active_wallets, 1):
                self.logger.info(f"🔍 Analyzing wallet {i}/{len(active_wallets)}: {wallet}")
                
                trustlines = self.db.get_wallet_trustlines(wallet)
                self.logger.debug(f"  Found {len(trustlines)} trustlines")
                
                if not trustlines or len(trustlines) < self.min_trades:
                    self.logger.debug(f"  Skipping: insufficient activity")
                    continue

                # Calculate score components
                total_tokens = len({(t['currency'], t['issuer']) for t in trustlines})
                early_adoptions = await self._count_early_adoptions(wallet, trustlines)
                early_rate = early_adoptions / max(total_tokens, 1)
                self.logger.debug(f"  Early adoptions: {early_adoptions}/{total_tokens}")

                successful_trades = await self._analyze_trading_success(wallet)
                trade_success_rate = successful_trades / max(total_tokens, 1)
                self.logger.debug(f"  Successful trades: {successful_trades}/{total_tokens}")

                consistency = await self._calculate_consistency(trustlines)
                self.logger.debug(f"  Consistency score: {consistency:.2f}")

                # Calculate final score (0-10)
                score = min(10, (
                    (early_rate * 4.0) +           # 40% weight
                    (trade_success_rate * 4.0) +   # 40% weight
                    (consistency * 2.0)            # 20% weight
                ))

                self.logger.info(f"  📈 Final score: {score:.2f}")

                if score >= 7:
                    scored_wallets.append((wallet, score))
                    self.logger.info(f"⭐ High performer! {wallet} scored {score:.2f}")

                # Update database
                self.db.update_wallet_alpha_score(wallet, score, datetime.now())

            if scored_wallets:
                scored_wallets.sort(key=lambda x: x[1], reverse=True)
                self._save_alpha_wallets(scored_wallets)
                self.logger.info(f"💾 Saved {len(scored_wallets)} alpha wallets")
                
                self.logger.info("\n🏆 Top 5 performing wallets:")
                for i, (wallet, score) in enumerate(scored_wallets[:5], 1):
                    self.logger.info(f"  #{i}: {wallet} (score: {score:.2f})")

        except Exception as e:
            self.logger.error(f"❌ Error in scoring loop: {e}")

    async def _count_early_adoptions(self, wallet: str, trustlines: List[Dict]) -> int:
        """Count how many times the wallet was an early adopter"""
        early_count = 0
        for trustline in trustlines:
            try:
                position = self.db.get_token_trustline_position(
                    currency=trustline['currency'],
                    issuer=trustline['issuer'],
                    timestamp=trustline['timestamp']
                )
                if position <= self.early_adopter_max:
                    early_count += 1
                    self.logger.debug(f"    Early adoption: position {position} for {trustline['currency']}")
            except Exception as e:
                self.logger.error(f"Error checking early adoption: {e}")
        return early_count

    async def _analyze_trading_success(self, wallet: str) -> int:
        """Count successful trades (ROI > min_roi)"""
        success_count = 0
        trades = self.db.get_wallet_all_trades(wallet)
        
        # Group trades by token
        token_trades: Dict[tuple, List[Dict]] = {}
        for trade in trades:
            key = (trade['currency'], trade['issuer'])
            token_trades.setdefault(key, []).append(trade)

        self.logger.debug(f"Analyzing {len(token_trades)} tokens traded by {wallet}")
        
        for token_key, token_trades_list in token_trades.items():
            currency, issuer = token_key
            
            # Get price history
            prices = self.db.get_price_history(currency, issuer)
            if not prices:
                self.logger.debug(f"    No price history for {currency}")
                continue

            # Konvertera Decimal128 till Decimal
            max_price = max(p['price'] for p in prices)
            self.logger.debug(f"    Max price for {currency}: {max_price} XRP")

            # Find entry price (average of first 3 buys)
            entry_trades = sorted(
                [t for t in token_trades_list if t['buyer'] == wallet],
                key=lambda x: x['timestamp']
            )[:3]
            
            if entry_trades:
                # Konvertera Decimal128 till Decimal om nödvändigt
                total_entry_price = sum(t['price_xrp'] for t in entry_trades)
                avg_entry_price = total_entry_price / len(entry_trades)
                roi = (max_price - avg_entry_price) / avg_entry_price
                
                self.logger.debug(f"    Entry: {avg_entry_price:.6f} XRP")
                self.logger.debug(f"    ROI: {roi*100:.1f}%")
                
                if roi >= self.min_roi:
                    success_count += 1
                    self.logger.debug(f"    ✨ Success! ROI: {roi*100:.1f}%")

        return success_count

    async def _calculate_consistency(self, trustlines: List[Dict]) -> float:
        """Calculate activity consistency score (0-1)"""
        if not trustlines:
            return 0

        sorted_lines = sorted(trustlines, key=lambda x: x['timestamp'])
        time_gaps = []
        for i in range(1, len(sorted_lines)):
            gap = sorted_lines[i]['timestamp'] - sorted_lines[i-1]['timestamp']
            time_gaps.append(gap.total_seconds() / 3600)  # Convert to hours

        if not time_gaps:
            return 0

        avg_gap = sum(time_gaps) / len(time_gaps)
        variance = sum((g - avg_gap) ** 2 for g in time_gaps) / len(time_gaps)
        std_dev = variance ** 0.5

        max_expected_std_dev = 168  # 1 week in hours
        consistency = 1 - min(std_dev / max_expected_std_dev, 1)
        
        self.logger.debug(f"  Consistency metrics:")
        self.logger.debug(f"    Average gap: {avg_gap:.1f}h")
        self.logger.debug(f"    Standard deviation: {std_dev:.1f}h")
        
        return consistency

    def _save_alpha_wallets(self, scored_wallets: List[tuple]):
        """Save high-scoring wallets to file"""
        try:
            with open(self.output_file, 'w') as f:
                f.write("PUBLIC_ADDRESS,SCORE\n")
                for wallet, score in scored_wallets:
                    f.write(f"{wallet},{score:.2f}\n")
            self.logger.debug(f"Wrote {len(scored_wallets)} wallets to {self.output_file}")
        except Exception as e:
            self.logger.error(f"❌ Error saving alpha wallets: {e}")

async def main():
    """Run wallet scorer"""
    db = XRPLDatabase()
    scorer = WalletScorer(db)
    
    try:
        await scorer.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await scorer.stop()

if __name__ == "__main__":
    asyncio.run(main())