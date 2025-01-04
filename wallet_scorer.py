import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Set
from pathlib import Path

from utils.db_handler import XRPLDatabase

class WalletScorer:
    """Analyzes wallet behavior and scores wallets based on their success with new tokens"""
    
    def __init__(
        self,
        db_handler: XRPLDatabase,
        analysis_interval: int = 3600,  # 1 hour
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
        
        # Set up logger
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
            # Get active wallets from last 30 days
            cutoff = datetime.now() - timedelta(days=30)
            active_wallets = self.db.get_active_wallets(cutoff)
            self.logger.info(f"📊 Found {len(active_wallets)} active wallets to analyze")

            # Score each wallet
            scored_wallets = []
            for i, wallet in enumerate(active_wallets, 1):
                self.logger.info(f"🔍 Analyzing wallet {i}/{len(active_wallets)}: {wallet}")
                
                trustlines = self.db.get_wallet_trustlines(wallet)
                self.logger.info(f"  Found {len(trustlines)} trustlines")
                
                trades = self.db.get_wallet_all_trades(wallet)
                self.logger.info(f"  Found {len(trades)} trades")
                
                score = await self._calculate_wallet_score(wallet)
                self.logger.info(f"  Score components for {wallet}:")
                
                # Get detailed stats
                if trustlines:
                    early_count = await self._count_early_adoptions(wallet, trustlines)
                    self.logger.info(f"    - Early adoptions: {early_count}/{len(trustlines)}")
                
                success_count = await self._analyze_trading_success(wallet)
                self.logger.info(f"    - Successful trades (>200% ROI): {success_count}")
                
                consistency = await self._calculate_consistency(trustlines)
                self.logger.info(f"    - Activity consistency score: {consistency:.2f}")
                
                self.logger.info(f"  📈 Final score: {score:.2f}")
                
                if score and score >= 7:
                    scored_wallets.append((wallet, score))
                    self.logger.info(f"⭐ High performer found! Wallet {wallet} scored {score:.2f}")

            # Sort by score descending
            scored_wallets.sort(key=lambda x: x[1], reverse=True)
            
            if scored_wallets:
                self.logger.info("\n🏆 Top performing wallets:")
                for i, (wallet, score) in enumerate(scored_wallets[:5], 1):
                    self.logger.info(f"  #{i}: {wallet} (score: {score:.2f})")
            else:
                self.logger.info("😔 No high performing wallets found this round")

            # Save to file
            self._save_alpha_wallets(scored_wallets)
            self.logger.info(f"💾 Saved {len(scored_wallets)} alpha wallets to {self.output_file}")

        except Exception as e:
            self.logger.error(f"❌ Error in scoring loop: {e}")

    
    async def _analyze_trading_success(self, wallet: str) -> int:
        """Count successful trades (ROI > min_roi)"""
        success_count = 0
        trades = self.db.get_wallet_all_trades(wallet)
        
        # Group trades by token
        token_trades: Dict[tuple, List[Dict]] = {}
        for trade in trades:
            key = (trade['currency'], trade['issuer'])
            token_trades.setdefault(key, []).append(trade)

        self.logger.debug(f"Analyzing {len(token_trades)} different tokens traded by {wallet}")
        
        # Analyze each token's trades
        for token_key, token_trades_list in token_trades.items():
            currency, issuer = token_key
            self.logger.debug(f"  Checking {currency}: {len(token_trades_list)} trades")
            
            # Get max price the token reached
            max_price = self.db.get_token_max_price(currency, issuer)
            if not max_price:
                self.logger.debug(f"    No max price found for {currency}")
                continue

            # Find entry price (average of first 3 buys)
            entry_trades = sorted(
                [t for t in token_trades_list if t['buyer'] == wallet],
                key=lambda x: x['timestamp']
            )[:3]
            
            if entry_trades:
                avg_entry_price = sum(t['price_xrp'] for t in entry_trades) / len(entry_trades)
                roi = (max_price - avg_entry_price) / avg_entry_price
                
                self.logger.debug(f"    Entry: {avg_entry_price:.6f} XRP")
                self.logger.debug(f"    Max: {max_price:.6f} XRP")
                self.logger.debug(f"    ROI: {roi*100:.1f}%")
                
                if roi >= self.min_roi:
                    success_count += 1
                    self.logger.debug(f"    ✨ Successful trade! ({roi*100:.1f}% > {self.min_roi*100}%)")

        return success_count
    
    async def _calculate_wallet_score(self, wallet: str) -> float:
        """Calculate a wallet's alpha score (1-10)"""
        try:
            # Get wallet's trustlines
            trustlines = self.db.get_wallet_trustlines(wallet)
            if not trustlines:
                return 0

            # Analyze early adoption rate
            total_tokens = len({(t['currency'], t['issuer']) for t in trustlines})
            early_adoptions = await self._count_early_adoptions(wallet, trustlines)
            early_rate = early_adoptions / max(total_tokens, 1)

            # Analyze trading success
            successful_trades = await self._analyze_trading_success(wallet)
            trade_success_rate = successful_trades / max(total_tokens, 1)

            # Calculate consistency score (regular activity over time)
            consistency_score = await self._calculate_consistency(trustlines)

            # Weighted scoring (early adoption: 40%, trading success: 40%, consistency: 20%)
            score = (
                (early_rate * 4.0) +
                (trade_success_rate * 4.0) +
                (consistency_score * 2.0)
            )

            # Update database
            self.db.update_wallet_alpha_score(
                wallet=wallet,
                alpha_score=score,
                calculation_time=datetime.now()
            )

            return score

        except Exception as e:
            self.logger.error(f"❌ Error calculating score for {wallet}: {e}")
            return 0

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

        # Analyze each token's trades
        for token_key, token_trades_list in token_trades.items():
            currency, issuer = token_key
            
            # Get max price the token reached
            max_price = self.db.get_token_max_price(currency, issuer)
            if not max_price:
                continue

            # Find entry price (average of first 3 buys)
            entry_trades = sorted(
                [t for t in token_trades_list if t['buyer'] == wallet],
                key=lambda x: x['timestamp']
            )[:3]
            
            if entry_trades:
                avg_entry_price = sum(t['price_xrp'] for t in entry_trades) / len(entry_trades)
                roi = (max_price - avg_entry_price) / avg_entry_price
                
                if roi >= self.min_roi:
                    success_count += 1

        return success_count

    async def _calculate_consistency(self, trustlines: List[Dict]) -> float:
        """Calculate activity consistency score (0-1)"""
        if not trustlines:
            return 0

        # Sort trustlines by timestamp
        sorted_lines = sorted(trustlines, key=lambda x: x['timestamp'])
        
        # Calculate average time between activities
        time_gaps = []
        for i in range(1, len(sorted_lines)):
            gap = sorted_lines[i]['timestamp'] - sorted_lines[i-1]['timestamp']
            time_gaps.append(gap.total_seconds() / 3600)  # Convert to hours

        if not time_gaps:
            return 0

        # Calculate consistency score based on standard deviation of gaps
        avg_gap = sum(time_gaps) / len(time_gaps)
        variance = sum((g - avg_gap) ** 2 for g in time_gaps) / len(time_gaps)
        std_dev = variance ** 0.5

        # Convert to 0-1 score (lower std_dev = higher consistency)
        max_expected_std_dev = 168  # 1 week in hours
        consistency = 1 - min(std_dev / max_expected_std_dev, 1)
        
        return consistency

    def _save_alpha_wallets(self, scored_wallets: List[tuple]):
        """Save high-scoring wallets to file"""
        try:
            with open(self.output_file, 'w') as f:
                f.write("PUBLIC_ADDRESS,SCORE\n")
                for wallet, score in scored_wallets:
                    f.write(f"{wallet},{score:.2f}\n")
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