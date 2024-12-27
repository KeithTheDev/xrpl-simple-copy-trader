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
            'target_wallet': "",
            'follower_seed': ""
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
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML files with fallback to defaults"""
        # Start with default config
        config = self.DEFAULT_CONFIG.copy()
        
        try:
            # Try to load default config file
            with open("config.yaml", 'r') as f:
                default_file_config = yaml.safe_load(f) or {}
                config = self._merge_configs(config, default_file_config)
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
            except FileNotFoundError:
                print(f"Warning: Config file {self.config_path} not found")
            except yaml.YAMLError as e:
                print(f"Error parsing config file {self.config_path}: {e}")
        
        # Validate and sanitize configuration
        self._validate_and_convert_types(config)
        return config
    
    def _validate_and_convert_types(self, config: Dict[str, Any]) -> None:
        """Validate and convert configuration values to correct types"""
        # Network settings
        if 'network' in config:
            net_config = config['network']
            
            # Validate websocket URL
            if 'websocket_url' in net_config:
                url = net_config['websocket_url']
                if not self._is_valid_websocket_url(url):
                    net_config['websocket_url'] = self.DEFAULT_CONFIG['network']['websocket_url']
            
            # Convert numeric values to correct types
            if 'max_reconnect_attempts' in net_config:
                try:
                    net_config['max_reconnect_attempts'] = int(net_config['max_reconnect_attempts'])
                except (ValueError, TypeError):
                    net_config['max_reconnect_attempts'] = self.DEFAULT_CONFIG['network']['max_reconnect_attempts']
            
            if 'reconnect_delay_seconds' in net_config:
                try:
                    net_config['reconnect_delay_seconds'] = int(float(net_config['reconnect_delay_seconds']))
                except (ValueError, TypeError):
                    net_config['reconnect_delay_seconds'] = self.DEFAULT_CONFIG['network']['reconnect_delay_seconds']

        # Trading settings
        if 'trading' in config:
            trade_config = config['trading']
            
            # Validate amount values
            for key in ['initial_purchase_amount', 'min_trust_line_amount', 'max_trust_line_amount']:
                if key in trade_config:
                    try:
                        value = float(str(trade_config[key]))
                        if value <= 0:
                            trade_config[key] = self.DEFAULT_CONFIG['trading'][key]
                        elif key == 'initial_purchase_amount':
                            trade_config[key] = str(value)  # Keep as string
                        else:
                            trade_config[key] = int(value)  # Convert to int for trust line amounts
                    except (ValueError, TypeError):
                        trade_config[key] = self.DEFAULT_CONFIG['trading'][key]
            
            # Ensure max >= min for trust line amounts
            try:
                if float(trade_config['max_trust_line_amount']) < float(trade_config['min_trust_line_amount']):
                    trade_config['max_trust_line_amount'] = self.DEFAULT_CONFIG['trading']['max_trust_line_amount']
                    trade_config['min_trust_line_amount'] = self.DEFAULT_CONFIG['trading']['min_trust_line_amount']
            except (KeyError, ValueError, TypeError):
                pass

    def _is_valid_websocket_url(self, url: str) -> bool:
        """Validate websocket URL"""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('ws', 'wss'):
                return False
            return any(endpoint in parsed.netloc for endpoint in self.ALLOWED_ENDPOINTS)
        except Exception:
            return False
    
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
            websocket_url = self.get('network', 'websocket_url')

            if not os.path.exists(self.config_path):
                print(f"\nError: {self.config_path} not found")
                print(f"Copy example.config.local.yaml to {self.config_path} and update the wallet settings")
                return False

            if not target_wallet:
                print("\nError: Missing target_wallet in config")
                print(f"Add a target wallet address to {self.config_path} (NOT in config.yaml)")
                print("This file is not source controlled and safe for secrets")
                return False

            if not follower_seed:
                print("\nError: Missing follower_seed in config")
                print("Run generate_wallet.py to create a new wallet")
                print(f"Then add the seed to {self.config_path} (NOT in config.yaml)")
                print("This file is not source controlled and safe for secrets")
                return False
                
            if not websocket_url:
                print("\nError: Missing websocket_url in config")
                print("Add a valid XRPL websocket URL to config.local.yaml")
                return False

            # Validate follower seed format
            try:
                Wallet.from_seed(follower_seed)
            except Exception as e:
                print(f"\nError: Invalid follower_seed format: {e}")
                print("Run generate_wallet.py to generate a valid wallet")
                return False

            return True
            
        except Exception as e:
            print(f"\nError validating config: {e}")
            return False