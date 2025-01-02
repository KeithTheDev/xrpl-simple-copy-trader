import yaml
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import logging
from xrpl.models.requests import Tx
from xrpl.clients import Client

class TokenFilter:
    """Filter for determining which tokens to track"""
    
    def __init__(self, config_path: str = "filter_rules.yaml"):
        """Initialize the token filter with rules from config file"""
        self.logger = logging.getLogger('TokenFilter')
        self.config = self._load_config(config_path)
        
        # Compile regex patterns for better performance
        self.ignored_patterns = [
            re.compile(pattern) 
            for pattern in self.config.get('ignored_currency_patterns', [])
        ]
        
    def _load_config(self, config_path: str) -> Dict:
        """Load filter configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.error(f"Error loading filter config: {e}")
            return {}
            
    async def should_track_token(self, 
                              currency: str, 
                              issuer: str, 
                              client: Client,
                              tx_hash: Optional[str] = None) -> bool:
        """
        Determine if a token should be tracked based on filtering rules
        and token age if tx_hash is provided.
        """
        # Check ignored currencies
        if currency in self.config.get('ignored_currencies', []):
            self.logger.debug(f"🚫 Token {currency}:{issuer} filtered: matches ignored currency list")
            return False
            
        # Check ignored issuers
        if issuer in self.config.get('ignored_issuers', []):
            self.logger.debug(f"🚫 Token {currency}:{issuer} filtered: issuer in ignored list")
            return False
            
        # Check currency patterns
        for pattern in self.ignored_patterns:
            if pattern.match(currency):
                self.logger.debug(f"🚫 Token {currency}:{issuer} filtered: matches pattern {pattern.pattern}")
                return False
        
        # If we have a transaction hash, check the token's age
        if tx_hash:
            token_age = await self._get_token_age(tx_hash, client)
            if token_age is not None:
                max_age = self.config.get('max_token_age_hours', 12)
                if token_age > max_age:
                    self.logger.debug(
                        f"Filtered out {currency}: age {token_age}h exceeds max {max_age}h"
                    )
                    return False
        
        return True
    
    async def _get_token_age(self, tx_hash: str, client: Client) -> Optional[float]:
        """Get the age of a token in hours based on its transaction timestamp"""
        try:
            # Query the transaction details
            tx_request = Tx(transaction=tx_hash)
            response = await client.request(tx_request)
            
            if response.is_successful():
                # Get transaction date
                tx_date = response.result.get('date')
                if tx_date:
                    # Calculate age
                    # XRPL timestamps are seconds since the Ripple epoch (January 1, 2000 00:00:00 UTC)
                    ripple_epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
                    tx_datetime = ripple_epoch + timedelta(seconds=tx_date)
                    age_hours = (datetime.now(timezone.utc) - tx_datetime).total_seconds() / 3600
                    return age_hours
                    
            self.logger.warning(f"Could not get transaction details for {tx_hash}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting token age for {tx_hash}: {e}")
            return None