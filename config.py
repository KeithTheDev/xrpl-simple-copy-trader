# config.py

import os
import yaml
from typing import Any, Dict
from pathlib import Path
from urllib.parse import urlparse

class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""
    pass

class Config:
    # Allowed XRPL websocket endpoints
    ALLOWED_ENDPOINTS = [
        '.rippletest.net',
        'xrpl.org',
        'ripple.com',
        "xrplcluster.com" 
    ]

    # Default configuration values
    DEFAULT_CONFIG = {
        'network': {
            'websocket_url': "wss://s.altnet.rippletest.net:51233",
            'max_reconnect_attempts': 5,
            'reconnect_delay_seconds': 5
        },
        'wallets': {
            'target_wallet': "",    # Public address of wallet to follow/copy
            'follower_seed': "",    # Private seed for your own wallet
            'follower_wallet': ""   # Public address for your wallet (calculated from seed)
        },
        'trading': {
            'initial_purchase_amount': "1",
            'min_trust_line_amount': "1000",
            'max_trust_line_amount': "10000",
            'send_max_xrp': "85",
            'slippage_percent': "5"
        },
        'logging': {
            'level': "INFO",
            'format': "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            'filename': "xrpl_trader.log"
        }
    }

    def __init__(self, config_path: str = "config.local.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        
    def _validate_and_update_follower_wallet(self) -> None:
        """Validate follower_seed and update follower_wallet"""
        try:
            from xrpl.wallet import Wallet
            
            follower_seed = self.get('wallets', 'follower_seed')
            if follower_seed:
                follower_wallet = Wallet.from_seed(follower_seed)
                # Update follower_wallet in config
                if 'wallets' not in self.config:
                    self.config['wallets'] = {}
                self.config['wallets']['follower_wallet'] = follower_wallet.classic_address
        except Exception as e:
            print(f"\nError validating follower_seed: {e}")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML files with fallback to defaults"""
        # Start with default config
        config = self.DEFAULT_CONFIG.copy()
        
        try:
            # Try to load default config file
            with open("config.yaml", 'r') as f:
                default_file_config = yaml.safe_load(f) or {}
                config = self._merge_configs(config, default_file_config)
                print("Loaded config.yaml successfully.")
        except FileNotFoundError:
            print("Warning: Config file config.yaml not found")
        except yaml.YAMLError as e:
            print(f"Error parsing config file config.yaml: {e}")
        
        # Try to load local config if it exists and is specified
        if self.config_path and self.config_path != "config.yaml":
            try:
                with open(self.config_path, 'r') as f:
                    local_config = yaml.safe_load(f) or {}
                    config = self._merge_configs(config, local_config)
                    print(f"Loaded {self.config_path} successfully.")
            except FileNotFoundError:
                print(f"Warning: Config file {self.config_path} not found")
            except yaml.YAMLError as e:
                print(f"Error parsing config file {self.config_path}: {e}")

        # Update follower_wallet from seed if needed
        self._validate_and_update_follower_wallet()
        
        # Log the merged configuration for debugging
        print("Merged Configuration:")
        print(yaml.dump(config, sort_keys=False))
        
        return config
    
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two configurations"""
        merged = base.copy()
        
        for key, value in override.items():
            if isinstance(value, dict) and key in merged and merged[key] is not None:
                merged[key] = self._merge_configs(merged[key], value)
            elif value is not None:  # Only override if value is not None
                merged[key] = value
                
        return merged
    
    def get(self, *keys: str, fallback: Any = None, default: Any = None) -> Any:
        """Get a configuration value using dot notation"""
        value = self.config
        for key in keys:
            try:
                value = value[key]
                if value is None:
                    return fallback if fallback is not None else default
            except (KeyError, TypeError):
                return fallback if fallback is not None else default
        return value

    def validate(self) -> bool:
        """Validate required configuration values"""
        try:
            from xrpl.wallet import Wallet
            
            target_wallet = self.get('wallets', 'target_wallet')
            follower_seed = self.get('wallets', 'follower_seed')
            follower_wallet = self.get('wallets', 'follower_wallet')
            websocket_url = self.get('network', 'websocket_url')

            if not os.path.exists(self.config_path):
                print(f"\nError: {self.config_path} not found")
                print("Run generate_wallet.py first to create your follower wallet")
                print(f"Then copy example.config.local.yaml to {self.config_path} and update wallet settings")
                return False

            if not target_wallet:
                print("\nError: Missing target_wallet in config")
                print(f"Add the public address of the wallet you want to follow to {self.config_path}")
                print("This should be a public XRPL address starting with 'r'")
                return False

            if not follower_seed:
                print("\nError: Missing follower_seed in config")
                print("Run generate_wallet.py to create a new wallet - this will give you both")
                print("the public address (follower_wallet) and private seed (follower_seed)")
                print(f"Then add the follower_seed to {self.config_path}")
                print("\nNOTE: Keep your follower_seed secret! Never share it with anyone!")
                return False
                
            if not websocket_url:
                print("\nError: Missing websocket_url in config")
                print("Add a valid XRPL websocket URL to config.local.yaml")
                return False

            # Validate target wallet format
            if not target_wallet.startswith('r'):
                print(f"\nError: Invalid target_wallet format: {target_wallet}")
                print("The target wallet must be a public XRPL address starting with 'r'")
                return False

            # Validate follower seed and wallet combination
            try:
                calc_wallet = Wallet.from_seed(follower_seed)
                if follower_wallet and calc_wallet.classic_address != follower_wallet:
                    print("\nWarning: follower_wallet in config doesn't match the address derived from follower_seed")
                    print(f"Expected: {calc_wallet.classic_address}")
                    print(f"Found: {follower_wallet}")
                    print("Using the correct address derived from seed.")
                    self.config['wallets']['follower_wallet'] = calc_wallet.classic_address
                elif not follower_wallet:
                    self.config['wallets']['follower_wallet'] = calc_wallet.classic_address
                
                print(f"\nValidated follower wallet configuration:")
                print(f"Public address: {calc_wallet.classic_address}")
            except Exception as e:
                print(f"\nError: Invalid follower_seed format: {e}")
                print("Run generate_wallet.py to generate a valid wallet")
                print("This will give you both your public address and private seed")
                return False

            return True
            
        except Exception as e:
            print(f"\nError validating config: {e}")
            return False