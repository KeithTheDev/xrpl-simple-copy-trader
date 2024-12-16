import os
import yaml
from typing import Any, Dict
from pathlib import Path

class Config:
    def __init__(self, config_path: str = "config.local.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML files"""
        # Load default config
        default_config = self._load_yaml("config.yaml")
        
        # Load local config if it exists
        local_config = {}
        if os.path.exists(self.config_path):
            local_config = self._load_yaml(self.config_path)
            
        # Merge configurations
        config = self._merge_configs(default_config, local_config)
        return config
    
    def _load_yaml(self, file_path: str) -> Dict[str, Any]:
        """Load YAML file"""
        try:
            with open(file_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"Warning: Config file {file_path} not found")
            return {}
        except yaml.YAMLError as e:
            print(f"Error parsing config file {file_path}: {e}")
            return {}
    
    def _merge_configs(self, default: Dict[str, Any], local: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two configurations"""
        merged = default.copy()
        
        for key, value in local.items():
            if isinstance(value, dict) and key in merged:
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
                
        return merged
    
    def get(self, *keys: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation"""
        value = self.config
        for key in keys:
            try:
                value = value[key]
            except (KeyError, TypeError):
                return default
        return value

    def validate(self) -> bool:
        """Validate required configuration values"""
        required_values = [
            ('wallets', 'target_wallet'),
            ('wallets', 'follower_seed'),
            ('network', 'websocket_url'),
        ]
        
        for keys in required_values:
            value = self.get(*keys)
            if not value:
                print(f"Missing required configuration: {'.'.join(keys)}")
                return False
        return True