# xrpl_transaction_parser.py

import logging
from typing import Dict, Any, Optional, Tuple, Union
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TrustSetInfo:
    """Information extracted from a TrustSet transaction"""
    wallet: str
    value: str
    currency: str
    issuer: str
    tx_hash: str = "unknown"
    timestamp: datetime = None
    test_mode: bool = False
    is_removal: bool = False

@dataclass
class PaymentInfo:
    """Information extracted from a Payment transaction"""
    buyer: str
    seller: str
    value: Decimal
    delivered_amount: Decimal
    currency: str
    issuer: str
    tx_hash: str = "unknown"
    timestamp: datetime = None
    test_mode: bool = False

class XRPLTransactionParser:
    """Utility class for parsing XRPL transactions"""
    
    def __init__(self, logger_name: str = "XRPLTransactionParser"):
        """Initialize the parser with logging"""
        self.logger = logging.getLogger(logger_name)

    def parse_trust_set(self, tx: Dict[str, Any], test_mode: bool = False) -> Optional[TrustSetInfo]:
        """
        Parse a TrustSet transaction.
        
        Args:
            tx: Transaction data from XRPL
            test_mode: Whether this is running in test mode
            
        Returns:
            TrustSetInfo if valid TrustSet transaction, None otherwise
        """
        try:
            limit_amount = tx.get("LimitAmount", {})
            if not isinstance(limit_amount, dict):
                return None

            currency = limit_amount.get("currency")
            issuer = limit_amount.get("issuer")
            value = limit_amount.get("value")
            wallet = tx.get("Account")
            tx_hash = tx.get("hash", "unknown")

            if not all([currency, issuer, value is not None, wallet]):
                return None

            return TrustSetInfo(
                wallet=wallet,
                value=value,
                currency=currency,
                issuer=issuer,
                tx_hash=tx_hash,
                timestamp=datetime.now(),
                test_mode=test_mode,
                is_removal=(value == "0")
            )

        except Exception as e:
            self.logger.error(f"Error parsing TrustSet transaction: {e}")
            return None

    def parse_payment(self, tx: Dict[str, Any], min_value: float = 0, 
                     test_mode: bool = False) -> Optional[PaymentInfo]:
        """
        Parse a Payment transaction.
        
        Args:
            tx: Transaction data from XRPL
            min_value: Minimum value to consider (for filtering small payments)
            test_mode: Whether this is running in test mode
            
        Returns:
            PaymentInfo if valid token Payment transaction above min_value, None otherwise
        """
        try:
            amount = tx.get("Amount")
            if not isinstance(amount, dict):  # Skip XRP payments
                return None

            currency = amount.get("currency")
            issuer = amount.get("issuer")
            value = Decimal(str(amount.get("value", "0")))
            
            buyer = tx.get("Destination")
            seller = tx.get("Account")
            tx_hash = tx.get("hash", "unknown")

            if not all([currency, issuer, buyer, seller]) or value < min_value:
                return None

            # Handle delivered amount (actual amount that was transferred)
            delivered_amount = tx.get("DeliveredAmount", amount)
            if isinstance(delivered_amount, dict):
                actual_value = Decimal(str(delivered_amount.get("value", value)))
            else:
                actual_value = value

            return PaymentInfo(
                buyer=buyer,
                seller=seller,
                value=value,
                delivered_amount=actual_value,
                currency=currency,
                issuer=issuer,
                tx_hash=tx_hash,
                timestamp=datetime.now(),
                test_mode=test_mode
            )

        except Exception as e:
            self.logger.error(f"Error parsing Payment transaction: {e}")
            return None

    def get_token_key(self, currency: str, issuer: str) -> str:
        """Create a unique key for a token"""
        return f"{currency}:{issuer}"

    def parse_transaction(self, data: Dict[str, Any], 
                        min_payment_value: float = 0,
                        test_mode: bool = False) -> Tuple[str, Optional[Union[TrustSetInfo, PaymentInfo]]]:
        """
        Parse any XRPL transaction and return its type and parsed info.
        
        Args:
            data: Transaction data from XRPL
            min_payment_value: Minimum value for payment transactions
            test_mode: Whether this is running in test mode
            
        Returns:
            Tuple of (transaction_type, parsed_info)
            where parsed_info is TrustSetInfo, PaymentInfo, or None depending on type
        """
        try:
            if not data.get("validated", False):
                return "unvalidated", None

            tx = data.get("transaction", {})
            tx_type = tx.get("TransactionType")

            if tx_type == "TrustSet":
                return "TrustSet", self.parse_trust_set(tx, test_mode)
            elif tx_type == "Payment":
                return "Payment", self.parse_payment(tx, min_payment_value, test_mode)
            else:
                return tx_type, None

        except Exception as e:
            self.logger.error(f"Error parsing transaction: {e}")
            return "error", None

    def is_successful_transaction(self, data: Dict[str, Any]) -> bool:
        """Check if a transaction was successful"""
        try:
            return (data.get("validated", False) and 
                   data.get("meta", {}).get("TransactionResult") == "tesSUCCESS")
        except Exception as e:
            self.logger.error(f"Error checking transaction success: {e}")
            return False

    def extract_fees(self, tx: Dict[str, Any]) -> Optional[Decimal]:
        """Extract transaction fees in XRP"""
        try:
            fee = tx.get("Fee")
            if fee:
                return Decimal(str(int(fee))) / Decimal("1000000")  # Convert from drops to XRP
            return None
        except Exception as e:
            self.logger.error(f"Error extracting fees: {e}")
            return None