# db_handler.py 
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
        self._create_indexes()

    def _create_indexes(self):
        # Core indexes
        self.db.trustlines.create_index([
            ("currency", ASCENDING), 
            ("issuer", ASCENDING)
        ])
        self.db.trustlines.create_index([("timestamp", ASCENDING)])
        self.db.trustlines.create_index([("wallet", ASCENDING)])
        
        self.db.purchases.create_index([
            ("currency", ASCENDING), 
            ("issuer", ASCENDING)
        ])
        self.db.purchases.create_index([("timestamp", ASCENDING)])
        self.db.purchases.create_index([("buyer", ASCENDING)])
        self.db.purchases.create_index([("seller", ASCENDING)])

        # Price tracking indexes
        self.db.token_prices.create_index([
            ("currency", ASCENDING),
            ("issuer", ASCENDING),
            ("timestamp", DESCENDING)
        ])
        self.db.token_max_prices.create_index([
            ("currency", ASCENDING),
            ("issuer", ASCENDING)
        ], unique=True)

        # Analytics indexes
        self.db.token_analysis.create_index([
            ("currency", ASCENDING), 
            ("issuer", ASCENDING), 
            ("timestamp", DESCENDING)
        ])
        self.db.token_analysis.create_index([("status", ASCENDING)])
        self.db.token_analysis.create_index([("creation_date", ASCENDING)])
        self.db.token_analysis.create_index([("last_activity", DESCENDING)])

        # Wallet analytics
        self.db.wallet_analysis.create_index([("address", ASCENDING)], unique=True)
        self.db.wallet_analysis.create_index([("alpha_score", DESCENDING)])
        self.db.wallet_analysis.create_index([("last_active", DESCENDING)])

    # Token price methods
    def update_token_price(self, currency: str, issuer: str, price: Decimal, timestamp: datetime) -> bool:
        try:
            price_data = {
                "currency": currency,
                "issuer": issuer,
                "price": Decimal128(price),
                "timestamp": timestamp
            }
            self.db.token_prices.insert_one(price_data)
            return True
        except Exception as e:
            self.logger.error(f"Error updating token price: {e}")
            return False

    def get_token_max_price(self, currency: str, issuer: str) -> Optional[Decimal]:
        try:
            result = self.db.token_max_prices.find_one({
                "currency": currency,
                "issuer": issuer
            })
            return Decimal(str(result["price"])) if result and "price" in result else None
        except Exception as e:
            self.logger.error(f"Error getting max price: {e}")
            return None

    def update_token_max_price(self, currency: str, issuer: str, price: Decimal, timestamp: datetime) -> bool:
        try:
            self.db.token_max_prices.update_one(
                {"currency": currency, "issuer": issuer},
                {
                    "$set": {
                        "price": Decimal128(price),
                        "timestamp": timestamp
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error updating max price: {e}")
            return False

    def get_price_history(self, currency: str, issuer: str, 
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       limit: int = 1000) -> List[Dict]:
        try:
            query = {"currency": currency, "issuer": issuer}
            if start_time or end_time:
                time_query = {}
                if start_time:
                    time_query["$gte"] = start_time
                if end_time:
                    time_query["$lte"] = end_time
                if time_query:
                    query["timestamp"] = time_query

            prices = list(self.db.token_prices.find(
                query,
                {"price": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", ASCENDING).limit(limit))

            return [{"price": Decimal(str(p["price"])), "timestamp": p["timestamp"]} for p in prices]
        except Exception as e:
            self.logger.error(f"Error getting price history: {e}")
            return []

    # Token tracking methods
    def get_active_tokens(self, min_age_hours: int = 0, 
                       max_age_hours: Optional[int] = None) -> List[Dict]:
        query = {"status": "active"}
        
        if min_age_hours or max_age_hours:
            time_query = {}
            now = datetime.now()
            if min_age_hours:
                time_query["$lte"] = now - timedelta(hours=min_age_hours)
            if max_age_hours:
                time_query["$gte"] = now - timedelta(hours=max_age_hours)
            if time_query:
                query["creation_date"] = time_query

        try:
            return list(self.db.token_analysis.find(
                query,
                {"currency": 1, "issuer": 1, "_id": 0}
            ))
        except Exception as e:
            self.logger.error(f"Error getting active tokens: {e}")
            return []

    def add_trustline(self, currency: str, issuer: str, wallet: str,
                   limit: str, tx_hash: str) -> bool:
        try:
            trustline = {
                "currency": currency,
                "issuer": issuer,
                "wallet": wallet,
                "limit": limit,
                "timestamp": datetime.utcnow(),
                "tx_hash": tx_hash
            }
            self.db.trustlines.insert_one(trustline)
            
            # Update wallet's first seen time if new
            self.db.wallet_analysis.update_one(
                {"address": wallet},
                {
                    "$min": {"first_seen": datetime.utcnow()},
                    "$max": {"last_active": datetime.utcnow()}
                },
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error adding trustline: {e}")
            return False
        
    def add_trade(self, currency: str, issuer: str, buyer: str, 
                seller: str, amount: Decimal, price_xrp: Decimal,
                tx_hash: str) -> bool:
        try:
            trade = {
                "currency": currency,
                "issuer": issuer,
                "buyer": buyer,
                "seller": seller,
                "amount": Decimal128(amount),
                "price_xrp": Decimal128(price_xrp),
                "timestamp": datetime.utcnow(),
                "tx_hash": tx_hash
            }
            self.db.purchases.insert_one(trade)
            
            # Update wallet activity times
            now = datetime.utcnow()
            self.db.wallet_analysis.update_many(
                {"address": {"$in": [buyer, seller]}},
                {"$max": {"last_active": now}},
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error adding trade: {e}")
            return False

    def mark_token_for_analysis(self, currency: str, issuer: str, 
                            tx_hash: str) -> bool:
        try:
            data = {
                "currency": currency,
                "issuer": issuer,
                "status": "pending",
                "first_seen_tx": tx_hash,
                "timestamp": datetime.now(),
                "last_updated": datetime.now()
            }
            result = self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": data},
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error marking for analysis: {e}")
            return False

    def mark_token_too_old(self, currency: str, issuer: str) -> bool:
        try:
            result = self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": {
                    "status": "too_old",
                    "last_updated": datetime.now()
                }}
            )
            return True
        except Exception as e:
            self.logger.error(f"Error marking as too old: {e}")
            return False

    def is_token_too_old(self, currency: str, issuer: str) -> bool:
        try:
            result = self.db.token_analysis.find_one({
                "currency": currency,
                "issuer": issuer,
                "status": "too_old"
            })
            return result is not None
        except Exception as e:
            self.logger.error(f"Error checking if too old: {e}")
            return False

    def get_unanalyzed_tokens(self, cutoff_time: datetime) -> List[Dict]:
        try:
            pending = list(self.db.token_analysis.find(
                {"status": "pending"},
                {"currency": 1, "issuer": 1, "first_seen_tx": 1, "_id": 0}
            ))

            expired = list(self.db.token_analysis.find({
                "last_updated": {"$lt": cutoff_time},
                "status": "active"
            }, {
                "currency": 1, "issuer": 1, "first_seen_tx": 1, "_id": 0
            }))

            # Combine and deduplicate
            seen = set()
            unique_tokens = []
            for token in pending + expired:
                key = (token["currency"], token["issuer"])
                if key not in seen:
                    seen.add(key)
                    unique_tokens.append(token)
            
            return unique_tokens
        except Exception as e:
            self.logger.error(f"Error getting unanalyzed tokens: {e}")
            return []

    def update_token_analysis(self, currency: str, issuer: str,
                          creation_date: Optional[datetime],
                          total_supply: Optional[Decimal],
                          unique_holders: int,
                          creator_address: Optional[str],
                          is_frozen: bool,
                          last_activity: Optional[datetime]) -> bool:
        try:
            # Create tracking URL
            tracking_url = f"https://xmagnetic.org/tokens/{currency}+{issuer}?network=mainnet"
            
            analysis = {
                "currency": currency,
                "issuer": issuer,
                "status": "active",
                "timestamp": datetime.now(),
                "creation_date": creation_date,
                "total_supply": Decimal128(total_supply) if total_supply else None,
                "unique_holders": unique_holders,
                "creator_address": creator_address,
                "is_frozen": is_frozen,
                "last_activity": last_activity,
                "last_updated": datetime.now(),
                "tracking_url": tracking_url
            }
            
            self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": analysis},
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error updating token analysis: {e}")
            return False

    def get_wallet_trustlines(self, wallet: str, since: Optional[datetime] = None) -> List[Dict]:
        try:
            query = {"wallet": wallet}
            if since:
                query["timestamp"] = {"$gte": since}
            
            return list(self.db.trustlines.find(
                query,
                {"currency": 1, "issuer": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", ASCENDING))
        except Exception as e:
            self.logger.error(f"Error getting wallet trustlines: {e}")
            return []

    def get_wallet_token_trades(self, wallet: str, currency: str, issuer: str) -> List[Dict]:
        try:
            return list(self.db.purchases.find(
                {
                    "$or": [{"buyer": wallet}, {"seller": wallet}],
                    "currency": currency,
                    "issuer": issuer
                },
                {"amount": 1, "price_xrp": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", ASCENDING))
        except Exception as e:
            self.logger.error(f"Error getting wallet trades: {e}")
            return []

    def get_token_trustline_count(self, currency: str, issuer: str) -> int:
        try:
            return self.db.trustlines.count_documents({
                "currency": currency,
                "issuer": issuer,
                "limit": {"$ne": "0"}
            })
        except Exception as e:
            self.logger.error(f"Error getting trustline count: {e}")
            return 0

    def get_active_wallets(self, since: datetime) -> List[str]:
        try:
            active_wallets = set()
            
            trustline_wallets = self.db.trustlines.distinct("wallet", {"timestamp": {"$gte": since}})
            active_wallets.update(trustline_wallets)
            
            trade_wallets = self.db.purchases.distinct("buyer", {"timestamp": {"$gte": since}})
            active_wallets.update(trade_wallets)
            seller_wallets = self.db.purchases.distinct("seller", {"timestamp": {"$gte": since}})
            active_wallets.update(seller_wallets)
            
            return list(active_wallets)
        except Exception as e:
            self.logger.error(f"Error getting active wallets: {e}")
            return []

    def update_wallet_alpha_score(self, wallet: str, alpha_score: float,
                              calculation_time: datetime) -> bool:
        try:
            self.db.wallet_analysis.update_one(
                {"address": wallet},
                {
                    "$set": {
                        "alpha_score": alpha_score,
                        "score_updated": calculation_time
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error updating wallet alpha score: {e}")
            return False

    def get_top_alpha_wallets(self, limit: int = 100) -> List[Dict]:
        try:
            return list(self.db.wallet_analysis.find(
                {"alpha_score": {"$exists": True}},
                {
                    "address": 1,
                    "alpha_score": 1,
                    "first_seen": 1,
                    "last_active": 1,
                    "_id": 0
                }
            ).sort("alpha_score", DESCENDING).limit(limit))
        except Exception as e:
            self.logger.error(f"Error getting top alpha wallets: {e}")
            return []

    def get_wallet_performance_history(self, wallet: str) -> List[Dict]:
        try:
            return list(self.db.wallet_analysis.find(
                {"address": wallet},
                {
                    "alpha_score": 1,
                    "score_updated": 1,
                    "_id": 0
                }
            ).sort("score_updated", ASCENDING))
        except Exception as e:
            self.logger.error(f"Error getting wallet history: {e}")
            return []

    def backfill_tracking_urls(self) -> bool:
        """Add tracking URLs to existing token analyses that don't have them"""
        try:
            result = self.db.token_analysis.update_many(
                {"tracking_url": {"$exists": False}},
                [{
                    "$set": {
                        "tracking_url": {
                            "$concat": [
                                "https://xmagnetic.org/tokens/",
                                "$currency",
                                "+",
                                "$issuer",
                                "?network=mainnet"
                            ]
                        }
                    }
                }]
            )
            self.logger.info(f"Updated {result.modified_count} tokens with tracking URLs")
            return True
        except Exception as e:
            self.logger.error(f"Error backfilling tracking URLs: {e}")
            return False
        
        # Add to db_handler.py

def get_token_trustline_position(self, currency: str, issuer: str, timestamp: datetime) -> int:
    """Get the position of a trustline in a token's timeline (1st, 2nd, etc)"""
    try:
        # Get all trustlines for this token up to this timestamp
        earlier_trustlines = self.db.trustlines.count_documents({
            "currency": currency,
            "issuer": issuer,
            "timestamp": {"$lte": timestamp},
            "limit": {"$ne": "0"}  # Exclude removed trustlines
        })
        return earlier_trustlines + 1
    except Exception as e:
        self.logger.error(f"Error getting trustline position: {e}")
        return float('inf')  # Return infinity to exclude from early adopter count

def get_wallet_all_trades(self, wallet: str) -> List[Dict]:
    """Get all trades for a wallet (both buys and sells)"""
    try:
        return list(self.db.purchases.find(
            {
                "$or": [{"buyer": wallet}, {"seller": wallet}]
            },
            {
                "currency": 1,
                "issuer": 1,
                "buyer": 1,
                "seller": 1,
                "amount": 1,
                "price_xrp": 1,
                "timestamp": 1,
                "_id": 0
            }
        ).sort("timestamp", ASCENDING))
    except Exception as e:
        self.logger.error(f"Error getting wallet trades: {e}")
        return []