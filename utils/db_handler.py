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
        self.ANALYSIS_VALID_HOURS = 24

    def _create_indexes(self):
        # Core indexes
        self.db.trustlines.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index([("currency", 1), ("issuer", 1)])
        self.db.purchases.create_index("timestamp")

        # Analytics indexes
        self.db.analytics_events.create_index([("timestamp", ASCENDING)])
        self.db.analytics_events.create_index([("token.currency", ASCENDING), ("token.issuer", ASCENDING)])
        self.db.analytics_events.create_index([("event_type", ASCENDING)])
        self.db.analytics_events.create_index([("data.wallet", ASCENDING)])

        self.db.analytics_snapshots.create_index([("token.currency", ASCENDING), ("token.issuer", ASCENDING), ("timestamp", DESCENDING)])

        self.db.analytics_wallets.create_index("address", unique=True)
        self.db.analytics_wallets.create_index([("performance.success_rate", DESCENDING)])
        
        # Token analysis indexes
        self.db.token_analysis.create_index([("currency", ASCENDING), ("issuer", ASCENDING), ("timestamp", DESCENDING)])
        self.db.token_analysis.create_index([("last_activity", DESCENDING)])
        self.db.token_analysis.create_index([("creation_date", ASCENDING)])
        self.db.token_analysis.create_index([("status", ASCENDING)])

    def add_trustline(self, currency: str, issuer: str, limit: str, tx_hash: str, test_mode: bool = False) -> bool:
        try:
            trustline = {
                "currency": currency,
                "issuer": issuer,
                "limit": limit,
                "timestamp": datetime.utcnow(),
                "hash": tx_hash,
                "test_mode": test_mode
            }
            self.db.trustlines.insert_one(trustline)
            self.logger.debug(f"Added trustline {currency}:{issuer}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding trustline: {e}")
            return False

    def add_purchase(self, currency: str, issuer: str, amount: str, cost_xrp: str, tx_hash: str, test_mode: bool = False) -> bool:
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
            self.db.purchases.insert_one(purchase)
            self.logger.debug(f"Added purchase {currency}:{issuer}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding purchase: {e}")
            return False

    def mark_token_for_analysis(self, currency: str, issuer: str, tx_hash: str) -> bool:
        try:
            data = {
                "currency": currency,
                "issuer": issuer,
                "status": "pending",
                "first_seen_tx": tx_hash,
                "timestamp": datetime.now(),
                "last_updated": datetime.now()
            }
            self.logger.debug(f"📝 Marking for analysis: {currency}:{issuer}")
            result = self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": data},
                upsert=True
            )
            self.logger.debug(f"✓ Analysis mark result: {result.modified_count} modified, {result.upserted_id and 'new' or 'existing'}")
            return True
        except Exception as e:
            self.logger.error(f"Error marking for analysis: {e}")
            return False

    def mark_token_too_old(self, currency: str, issuer: str) -> bool:
        try:
            self.logger.debug(f"⌛ Marking as too old: {currency}:{issuer}")
            result = self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": {
                    "status": "too_old",
                    "last_updated": datetime.now()
                }}
            )
            self.logger.debug(f"✓ Too old mark result: {result.modified_count} modified")
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
            is_old = result is not None
            self.logger.debug(f"Age check for {currency}:{issuer} - Too old: {is_old}")
            return is_old
        except Exception as e:
            self.logger.error(f"Error checking if too old: {e}")
            return False

    def get_unanalyzed_tokens(self, cutoff_time: datetime) -> List[Dict]:
        try:
            self.logger.debug("🔍 Looking for unanalyzed tokens...")
            # Get pending tokens
            pending = list(self.db.token_analysis.find({
                "status": "pending"
            }, {
                "currency": 1,
                "issuer": 1,
                "first_seen_tx": 1,
                "_id": 0
            }))
            self.logger.debug(f"Found {len(pending)} pending tokens")

            # Get expired active tokens
            expired = list(self.db.token_analysis.find({
                "last_updated": {"$lt": cutoff_time},
                "status": "active"
            }, {
                "currency": 1,
                "issuer": 1,
                "first_seen_tx": 1,
                "_id": 0
            }))
            self.logger.debug(f"Found {len(expired)} expired tokens")

            # Combine and deduplicate
            all_tokens = pending + expired
            seen = set()
            unique_tokens = []
            for token in all_tokens:
                key = (token["currency"], token["issuer"])
                if key not in seen:
                    seen.add(key)
                    unique_tokens.append(token)
            
            self.logger.debug(f"Total unique tokens to analyze: {len(unique_tokens)}")
            if unique_tokens:
                self.logger.debug("First few tokens:")
                for t in unique_tokens[:3]:
                    self.logger.debug(f"- {t['currency']}:{t['issuer']}")
            
            return unique_tokens
            
        except Exception as e:
            self.logger.error(f"Error getting unanalyzed tokens: {e}")
            return []

    def store_token_analysis(self, currency: str, issuer: str, 
                           creation_date: Optional[datetime],
                           total_supply: Optional[Decimal],
                           unique_holders: int,
                           creator_address: Optional[str],
                           is_frozen: bool,
                           last_activity: Optional[datetime],
                           status: str = "active") -> bool:
        try:
            analysis = {
                "currency": currency,
                "issuer": issuer,
                "timestamp": datetime.now(),
                "creation_date": creation_date,
                "total_supply": self._convert_decimal(str(total_supply)) if total_supply else None,
                "unique_holders": unique_holders,
                "creator_address": creator_address,
                "is_frozen": is_frozen,
                "last_activity": last_activity,
                "status": status,
                "last_updated": datetime.now()
            }
            
            result = self.db.token_analysis.update_one(
                {"currency": currency, "issuer": issuer},
                {"$set": analysis},
                upsert=True
            )
            self.logger.debug(f"✓ Stored analysis for {currency}:{issuer}")
            return True
        except Exception as e:
            self.logger.error(f"Error storing analysis: {e}")
            return False

    def analytics_add_event(self, event_type: str, token: Dict, data: Dict) -> bool:
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

    def analytics_add_trust_line(self, currency: str, issuer: str, wallet: str, limit: str, tx_hash: str) -> bool:
        token = {"currency": currency, "issuer": issuer}
        data = {
            "wallet": wallet,
            "limit": self._convert_decimal(limit),
            "tx_hash": tx_hash
        }
        return self.analytics_add_event("trust_line", token, data)

    def analytics_add_trade(self, currency: str, issuer: str, amount: str,
                          price_xrp: str, buyer: str, seller: str, tx_hash: str) -> bool:
        token = {"currency": currency, "issuer": issuer}
        data = {
            "amount": self._convert_decimal(amount),
            "price_xrp": self._convert_decimal(price_xrp),
            "buyer": buyer,
            "seller": seller,
            "tx_hash": tx_hash
        }
        return self.analytics_add_event("trade", token, data)

    def _convert_decimal(self, value: str) -> Decimal128:
        return Decimal128(Decimal(str(value)))