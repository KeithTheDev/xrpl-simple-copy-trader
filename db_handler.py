from typing import Dict, Optional
from datetime import datetime
from pymongo import MongoClient
import logging

class XRPLDatabase:
    def __init__(self, uri: str = "mongodb://localhost:27017/"):
        self.client = MongoClient(uri)
        self.db = self.client.xrpl_monitor
        self.logger = logging.getLogger('XRPLDatabase')
        
        # Ensure indexes
        self.db.trustlines.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index("timestamp")

    def add_trustline(self, currency: str, issuer: str, limit: str, 
                     tx_hash: str, test_mode: bool = False) -> bool:
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

    def get_trustline(self, currency: str, issuer: str) -> Optional[Dict]:
        try:
            return self.db.trustlines.find_one({"currency": currency, "issuer": issuer})
        except Exception as e:
            self.logger.error(f"Error getting trustline: {e}")
            return None

    def get_purchases(self, currency: str, issuer: str) -> list:
        try:
            return list(self.db.purchases.find(
                {"currency": currency, "issuer": issuer}
            ).sort("timestamp", -1))
        except Exception as e:
            self.logger.error(f"Error getting purchases: {e}")
            return []

    def get_daily_stats(self) -> Dict:
        pipeline = [
            {
                "$match": {
                    "timestamp": {
                        "$gte": datetime.utcnow().replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "trust_lines": {
                        "$sum": {"$cond": [{"$eq": ["$test_mode", False]}, 1, 0]}
                    },
                    "purchases": {
                        "$sum": {"$cond": [{"$eq": ["$test_mode", False]}, 1, 0]}
                    },
                    "test_trust_lines": {
                        "$sum": {"$cond": [{"$eq": ["$test_mode", True]}, 1, 0]}
                    },
                    "test_purchases": {
                        "$sum": {"$cond": [{"$eq": ["$test_mode", True]}, 1, 0]}
                    }
                }
            }
        ]
        
        try:
            trustline_stats = list(self.db.trustlines.aggregate(pipeline))
            purchase_stats = list(self.db.purchases.aggregate(pipeline))
            
            stats = {
                "trust_lines": 0,
                "purchases": 0,
                "test_trust_lines": 0,
                "test_purchases": 0
            }
            
            if trustline_stats:
                stats.update(trustline_stats[0])
            if purchase_stats:
                stats.update(purchase_stats[0])
                
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting daily stats: {e}")
            return {
                "trust_lines": 0,
                "purchases": 0,
                "test_trust_lines": 0,
                "test_purchases": 0
            }