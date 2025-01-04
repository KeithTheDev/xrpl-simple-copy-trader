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

        self.db.token_analysis.create_index([
            ("currency", ASCENDING), 
            ("issuer", ASCENDING), 
            ("timestamp", DESCENDING)
        ])
        self.db.token_analysis.create_index([("status", ASCENDING)])
        self.db.token_analysis.create_index([("creation_date", ASCENDING)])
        self.db.token_analysis.create_index([("last_activity", DESCENDING)])
        self.db.token_analysis.create_index([("first_price_time", ASCENDING)])
        self.db.token_analysis.create_index([("current_price", DESCENDING)])

        self.db.wallet_analysis.create_index([("address", ASCENDING)], unique=True)
        self.db.wallet_analysis.create_index([("alpha_score", DESCENDING)])
        self.db.wallet_analysis.create_index([("last_active", DESCENDING)])

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
        """
        Add a new trade to the database and update related collections.
        
        Args:
            currency: Token currency code
            issuer: Token issuer address
            buyer: Buyer's wallet address
            seller: Seller's wallet address
            amount: Trade amount
            price_xrp: Price in XRP
            tx_hash: Transaction hash

        Returns:
            bool: True if trade was added successfully
        """
        try:
            # Validate addresses to prevent null values in wallet_analysis
            if not buyer or not seller or buyer == "null" or seller == "null":
                self.logger.warning(f"Invalid address detected: buyer={buyer}, seller={seller}")
                return False

            # Create trade record
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

            # Add trade to purchases collection
            self.db.purchases.insert_one(trade)
            
            # Update token price tracking
            self.update_token_prices(currency, issuer, price_xrp)
            
            # Update token status to active since there's trading activity
            self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {
                    "$set": {
                        "status": "active",
                        "last_updated": datetime.now(),
                        "last_trade": datetime.now()
                    }
                }
            )

            # Update wallet activity timestamps
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
                "last_updated": datetime.now(),
                "tracking_url": f"https://xmagnetic.org/tokens/{currency}+{issuer}?network=mainnet"
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

    def update_token_prices(self, currency: str, issuer: str, 
                        current_price: Decimal) -> bool:
        try:
            token = self.db.token_analysis.find_one(
                {"currency": currency, "issuer": issuer}
            )
            
            update_data = {
                "current_price": Decimal128(current_price),
                "last_updated": datetime.now()
            }

            # Set first price if not exists
            if not token or "first_price" not in token:
                update_data["first_price"] = Decimal128(current_price)
                update_data["first_price_time"] = datetime.now()
            
            # Update max price if needed
            if not token or "max_price" not in token or current_price > Decimal(str(token["max_price"])):
                update_data["max_price"] = Decimal128(current_price)
                update_data["max_price_time"] = datetime.now()

            self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": update_data},
                upsert=True
            )
            return True
        except Exception as e:
            self.logger.error(f"Error updating token prices: {e}")
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
            trades = list(self.db.purchases.find(
                {
                    "$or": [{"buyer": wallet}, {"seller": wallet}],
                    "currency": currency,
                    "issuer": issuer
                },
                {"amount": 1, "price_xrp": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", ASCENDING))

            for trade in trades:
                if isinstance(trade.get('price_xrp'), Decimal128):
                    trade['price_xrp'] = trade['price_xrp'].to_decimal()
                if isinstance(trade.get('amount'), Decimal128):
                    trade['amount'] = trade['amount'].to_decimal()
            
            return trades
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

    def get_token_trustline_position(self, currency: str, issuer: str, timestamp: datetime) -> int:
        try:
            earlier_trustlines = self.db.trustlines.count_documents({
                "currency": currency,
                "issuer": issuer,
                "timestamp": {"$lte": timestamp},
                "limit": {"$ne": "0"}
            })
            return earlier_trustlines + 1
        except Exception as e:
            self.logger.error(f"Error getting trustline position: {e}")
            return float('inf')

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
            self.logger.error(f"Error updating alpha score: {e}")
            return False

    def get_price_history(self, currency: str, issuer: str, 
                         start_time: Optional[datetime] = None,
                         end_time: Optional[datetime] = None) -> List[Dict]:
        """Get token price history from trade data"""
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

            trades = list(self.db.purchases.find(
                query,
                {"price_xrp": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", ASCENDING))

            return [{
                "price": Decimal(str(trade["price_xrp"])), 
                "timestamp": trade["timestamp"]
            } for trade in trades]
            
        except Exception as e:
            self.logger.error(f"Error getting price history: {e}")
            return []

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
        
    def get_token_max_price(self, currency: str, issuer: str) -> Optional[Decimal]:
        """
        Retrieve the maximum price for a given token.
        """
        try:
            token = self.db.token_analysis.find_one(
                {"currency": currency, "issuer": issuer},
                {"max_price": 1, "_id": 0}
            )
            if token and "max_price" in token:
                return Decimal(str(token["max_price"]))
        except Exception as e:
            self.logger.error(f"Error getting max price: {e}")
        return None
    
    def update_token_max_price(
        self,
        currency: str,
        issuer: str,
        price: Decimal,
        timestamp: datetime
    ) -> None:
        """
        Update the maximum price for the specified token.
        """
        try:
            self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {
                    "$set": {
                        "max_price": str(price),
                        "max_price_updated": timestamp
                    }
                },
                upsert=True
            )
        except Exception as e:
            self.logger.error(f"Error updating token max price: {e}")

    def update_token_price(
        self,
        currency: str,
        issuer: str,
        price: Decimal,
        timestamp: datetime
    ) -> None:
        """
        Update the current price for the specified token.

        :param currency: The currency code of the token.
        :param issuer: The issuer address of the token.
        :param price: The current price of the token as a Decimal.
        :param timestamp: The datetime when the price was updated.
        """
        try:
            self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {
                    "$set": {
                        "current_price": str(price),
                        "current_price_updated": timestamp
                    }
                },
                upsert=True
            )
            self.logger.debug(
                f"Updated current price for {currency} issued by {issuer} to {price} XRP at {timestamp}"
            )
        except Exception as e:
            self.logger.error(f"Error updating token price for {currency} issued by {issuer}: {e}")