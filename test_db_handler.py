import pytest
from datetime import datetime, timedelta
from db_handler import XRPLDatabase

class TestXRPLDatabase:
    @pytest.fixture
    def db(self):
        test_db = XRPLDatabase()
        test_db.db.trustlines.delete_many({})
        test_db.db.purchases.delete_many({})
        return test_db

    @pytest.fixture
    def sample_trustline(self):
        return {
            "currency": "TEST",
            "issuer": "rTestIssuer",
            "limit": "1000",
            "tx_hash": "test_hash"
        }

    @pytest.fixture
    def sample_purchase(self):
        return {
            "currency": "TEST",
            "issuer": "rTestIssuer",
            "amount": "100",
            "cost_xrp": "10",
            "tx_hash": "test_hash"
        }

    def test_add_trustline(self, db, sample_trustline):
        result = db.add_trustline(**sample_trustline, test_mode=True)
        assert result == True
        
        trustline = db.get_trustline(sample_trustline["currency"], sample_trustline["issuer"])
        assert trustline is not None
        assert trustline["currency"] == sample_trustline["currency"]
        assert trustline["test_mode"] == True

    def test_add_purchase(self, db, sample_purchase):
        result = db.add_purchase(**sample_purchase, test_mode=True)
        assert result == True
        
        purchases = db.get_purchases(sample_purchase["currency"], sample_purchase["issuer"])
        assert len(purchases) == 1
        assert purchases[0]["currency"] == sample_purchase["currency"]
        assert purchases[0]["test_mode"] == True

    def test_daily_stats(self, db, sample_trustline, sample_purchase):
        # Add mix of test and real transactions
        db.add_trustline(**sample_trustline, test_mode=True)
        db.add_trustline(**sample_trustline, test_mode=False)
        db.add_purchase(**sample_purchase, test_mode=True)
        db.add_purchase(**sample_purchase, test_mode=False)
        
        stats = db.get_daily_stats()
        assert stats["trust_lines"] == 1
        assert stats["test_trust_lines"] == 1
        assert stats["purchases"] == 1
        assert stats["test_purchases"] == 1

    def test_get_nonexistent_trustline(self, db):
        result = db.get_trustline("NONEXISTENT", "rNonexistent")
        assert result is None

    def test_get_empty_purchases(self, db):
        purchases = db.get_purchases("NONEXISTENT", "rNonexistent")
        assert len(purchases) == 0

    def test_old_transactions_excluded_from_daily_stats(self, db, sample_trustline, sample_purchase):
        # Add old transaction by manipulating timestamp
        old_trustline = sample_trustline.copy()
        old_trustline["timestamp"] = datetime.utcnow() - timedelta(days=2)
        db.db.trustlines.insert_one(old_trustline)
        
        # Add today's transaction
        db.add_trustline(**sample_trustline, test_mode=False)
        
        stats = db.get_daily_stats()
        assert stats["trust_lines"] == 1 # Only today's transaction