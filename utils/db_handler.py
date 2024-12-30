from datetime import datetime, timedelta
from typing import Dict, Optional, List
from decimal import Decimal
from pymongo import MongoClient, ASCENDING, DESCENDING
import logging
from bson.decimal128 import Decimal128

class XRPLDatabase:
    def __init__(self, uri: str = "mongodb://localhost:27017/"):
        self.client = MongoClient(uri)
        self.db = self.client.xrpl_monitor
        self.logger = logging.getLogger('XRPLDatabase')
        
        # Create indexes for both existing and new collections
        self._create_indexes()

    def _create_indexes(self):
        # Existing indexes for memecoin_monitor
        self.db.trustlines.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index("timestamp")

        # New indexes for analytics
        self.db.analytics_events.create_index([("timestamp", ASCENDING)])
        self.db.analytics_events.create_index([
            ("token.currency", ASCENDING), 
            ("token.issuer", ASCENDING)
        ])
        self.db.analytics_events.create_index([("event_type", ASCENDING)])
        self.db.analytics_events.create_index([("data.wallet", ASCENDING)])

        self.db.analytics_snapshots.create_index([
            ("token.currency", ASCENDING),
            ("token.issuer", ASCENDING),
            ("timestamp", DESCENDING)
        ])

        self.db.analytics_wallets.create_index("address", unique=True)
        self.db.analytics_wallets.create_index([("performance.success_rate", DESCENDING)])

    # Existing methods for memecoin_monitor
    def add_trustline(self, currency: str, issuer: str, limit: str, 
                     tx_hash: str, test_mode: bool = False) -> bool:
        # Existing implementation remains unchanged
        try:
            trustline = {
                "currency": currency,
                "issuer": issuer,
                "limit": limit,
                "timestamp": datetime.utcnow(),
                "hash": tx_hash,
                "test_mode": test_mode
            }
            result = self.db.trustlines.insert_one(trustline)
            self.logger.debug(f"Added trustline {result.inserted_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding trustline: {e}")
            return False

    def add_purchase(self, currency: str, issuer: str, amount: str, 
                    cost_xrp: str, tx_hash: str, test_mode: bool = False) -> bool:
        # Existing implementation remains unchanged
        try:
            purchase = {
                "currency": currency,
                "issuer": issuer,
                "amount": amount,
                "cost_xrp": cost_xrp,
                "timestamp": datetime.utcnow(),
                "hash": tx_hash,
                "test_mode": test_mode
            }
            result = self.db.purchases.insert_one(purchase)
            self.logger.debug(f"Added purchase {result.inserted_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding purchase: {e}")
            return False

    # New methods for analytics system
    def analytics_add_event(self, event_type: str, token: Dict, data: Dict) -> bool:
        """Add a new analytics event"""
        try:
            event = {
                "timestamp": datetime.utcnow(),
                "event_type": event_type,
                "token": token,
                "data": data
            }
            self.db.analytics_events.insert_one(event)
            return True
        except Exception as e:
            self.logger.error(f"Error adding analytics event: {e}")
            return False

    def analytics_add_trust_line(self, currency: str, issuer: str, 
                               wallet: str, limit: str, tx_hash: str) -> bool:
        """Record a new trust line event for analytics"""
        token = {"currency": currency, "issuer": issuer}
        data = {
            "wallet": wallet,
            "limit": self._convert_decimal(limit),
            "tx_hash": tx_hash
        }
        return self.analytics_add_event("trust_line", token, data)

    def analytics_add_trade(self, currency: str, issuer: str, amount: str,
                          price_xrp: str, buyer: str, seller: str, 
                          tx_hash: str) -> bool:
        """Record a new trade event for analytics"""
        token = {"currency": currency, "issuer": issuer}
        data = {
            "amount": self._convert_decimal(amount),
            "price_xrp": self._convert_decimal(price_xrp),
            "buyer": buyer,
            "seller": seller,
            "tx_hash": tx_hash
        }
        return self.analytics_add_event("trade", token, data)

    def analytics_add_price(self, currency: str, issuer: str, price: str, 
                          liquidity: str, source: str) -> bool:
        """Record a price check event for analytics"""
        token = {"currency": currency, "issuer": issuer}
        data = {
            "price": self._convert_decimal(price),
            "liquidity": self._convert_decimal(liquidity),
            "source": source
        }
        success = self.analytics_add_event("price_check", token, data)
        
        if success:
            # Also update the latest snapshot
            snapshot = {
                "timestamp": datetime.utcnow(),
                "token": token,
                "metrics": {
                    "price": self._convert_decimal(price),
                    "liquidity": self._convert_decimal(liquidity),
                    "source": source
                }
            }
            self.db.analytics_snapshots.insert_one(snapshot)
        return success

    def analytics_get_wallet_stats(self, wallet: str, days: int = 30) -> Dict:
        """Get comprehensive wallet statistics"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Get all trust line events for this wallet
            trust_events = self.db.analytics_events.find({
                "event_type": "trust_line",
                "data.wallet": wallet,
                "timestamp": {"$gte": cutoff_date}
            })
            
            stats = {
                "wallet": wallet,
                "period_days": days,
                "tokens_trusted": 0,
                "successful_picks": 0,
                "total_roi": Decimal('0'),
                "best_token": None
            }
            
            for event in trust_events:
                token = event["token"]
                stats["tokens_trusted"] += 1
                
                # Calculate ROI for this token
                roi = self._calculate_token_roi(token, event["timestamp"])
                if roi and roi > 0:
                    stats["successful_picks"] += 1
                    stats["total_roi"] += roi
                    
                    if not stats["best_token"] or roi > stats["best_token"]["roi"]:
                        stats["best_token"] = {
                            "token": token,
                            "roi": roi,
                            "timestamp": event["timestamp"]
                        }
            
            if stats["tokens_trusted"] > 0:
                stats["success_rate"] = stats["successful_picks"] / stats["tokens_trusted"]
                stats["average_roi"] = stats["total_roi"] / stats["tokens_trusted"]
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting wallet stats: {e}")
            return None

    def analytics_get_token_metrics(self, currency: str, issuer: str, 
                                  days: int = 30) -> Dict:
        """Get comprehensive token metrics"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Base query for this token
            token_query = {
                "token.currency": currency,
                "token.issuer": issuer,
                "timestamp": {"$gte": cutoff_date}
            }
            
            # Get trust line metrics
            trust_lines = self.db.analytics_events.count_documents({
                **token_query,
                "event_type": "trust_line"
            })
            
            # Get unique wallets with trust lines
            unique_wallets = len(self.db.analytics_events.distinct(
                "data.wallet",
                {**token_query, "event_type": "trust_line"}
            ))
            
            # Get price metrics
            price_docs = list(self.db.analytics_events.find(
                {**token_query, "event_type": "price_check"},
                sort=[("timestamp", ASCENDING)]
            ))
            
            price_metrics = {
                "first_price": None,
                "last_price": None,
                "price_change": None,
                "volatility": None
            }
            
            if price_docs:
                prices = [Decimal(str(doc["data"]["price"])) for doc in price_docs]
                price_metrics["first_price"] = prices[0]
                price_metrics["last_price"] = prices[-1]
                price_metrics["price_change"] = (
                    (prices[-1] - prices[0]) / prices[0] * 100
                )
                
                # Calculate price volatility
                if len(prices) > 1:
                    price_metrics["volatility"] = self._calculate_volatility(prices)
            
            return {
                "token": {"currency": currency, "issuer": issuer},
                "period_days": days,
                "trust_lines": trust_lines,
                "unique_wallets": unique_wallets,
                "price_metrics": price_metrics,
                "timestamp": datetime.utcnow()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting token metrics: {e}")
            return None

    # Helper methods
    def _convert_decimal(self, value: str) -> Decimal128:
        """Convert string to MongoDB Decimal128"""
        return Decimal128(Decimal(str(value)))

    def _calculate_token_roi(self, token: Dict, from_time: datetime) -> Optional[Decimal]:
        """Calculate ROI for a token from a specific time"""
        try:
            # Get first price after trust
            first_price = self.db.analytics_events.find_one({
                "event_type": "price_check",
                "token.currency": token["currency"],
                "token.issuer": token["issuer"],
                "timestamp": {"$gte": from_time}
            }, sort=[("timestamp", ASCENDING)])
            
            if not first_price:
                return None
                
            # Get latest price
            latest_price = self.db.analytics_events.find_one({
                "event_type": "price_check",
                "token.currency": token["currency"],
                "token.issuer": token["issuer"]
            }, sort=[("timestamp", DESCENDING)])
            
            if not latest_price:
                return None
                
            # Calculate ROI
            initial = Decimal(str(first_price["data"]["price"]))
            final = Decimal(str(latest_price["data"]["price"]))
            
            return ((final - initial) / initial) * 100
            
        except Exception as e:
            self.logger.error(f"Error calculating token ROI: {e}")
            return None

    def _calculate_volatility(self, prices: List[Decimal]) -> Decimal:
        """Calculate price volatility (standard deviation of returns)"""
        try:
            if len(prices) < 2:
                return Decimal('0')
                
            returns = []
            for i in range(1, len(prices)):
                returns.append((prices[i] - prices[i-1]) / prices[i-1])
            
            mean = sum(returns) / len(returns)
            squared_diff_sum = sum((r - mean) ** 2 for r in returns)
            return (squared_diff_sum / (len(returns) - 1)).sqrt()
            
        except Exception as e:
            self.logger.error(f"Error calculating volatility: {e}")
            return Decimal('0')