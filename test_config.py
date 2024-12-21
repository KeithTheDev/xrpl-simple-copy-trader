import pytest
from pathlib import Path
import yaml
from decimal import Decimal

from config import Config

# [Previous fixtures remain the same]

def test_deep_nested_config_override(tmp_path, monkeypatch):
    """Test deeply nested configuration overrides"""
    # Create default config with nested structure
    config_yaml = tmp_path / "config.yaml"
    default_data = {
        'advanced': {
            'trading': {
                'strategies': {
                    'default': {
                        'threshold': 0.1
                    }
                }
            }
        }
    }
    config_yaml.write_text(yaml.dump(default_data))

    # Create local config that overrides nested value
    config_local = tmp_path / "config.local.yaml"
    local_data = {
        'advanced': {
            'trading': {
                'strategies': {
                    'default': {
                        'threshold': 0.2
                    }
                }
            }
        }
    }
    config_local.write_text(yaml.dump(local_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # Verify deep override worked
    assert config.get('advanced', 'trading', 'strategies', 'default', 'threshold') == 0.2

def test_trading_limits_validation(tmp_path, monkeypatch):
    """Test validation of trading limits and amounts"""
    config_local = tmp_path / "config.local.yaml"
    invalid_data = {
        'trading': {
            'initial_purchase_amount': "-1",  # Invalid negative amount
            'min_trust_line_amount': "10000",
            'max_trust_line_amount': "1000"   # Invalid: max < min
        }
    }
    config_local.write_text(yaml.dump(invalid_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # These should use default values instead of invalid ones
    assert float(config.get('trading', 'initial_purchase_amount')) > 0
    assert float(config.get('trading', 'max_trust_line_amount')) >= float(config.get('trading', 'min_trust_line_amount'))

def test_security_critical_config(tmp_path, monkeypatch):
    """Test handling of security-critical configuration"""
    config_local = tmp_path / "config.local.yaml"
    security_data = {
        'wallets': {
            'target_wallet': "rValidXRPAddress123",
            'follower_seed': "sValidSeed123"
        },
        'network': {
            'websocket_url': "wss://malicious-site.com"  # Potentially malicious URL
        }
    }
    config_local.write_text(yaml.dump(security_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # Verify URL is properly validated (should only accept known XRPL endpoints)
    # This might need implementation in the Config class
    assert config.get('network', 'websocket_url').startswith('wss://')
    assert '.rippletest.net' in config.get('network', 'websocket_url') or 'xrpl.org' in config.get('network', 'websocket_url')

def test_numeric_value_handling(tmp_path, monkeypatch):
    """Test handling of numeric configuration values"""
    config_local = tmp_path / "config.local.yaml"
    numeric_data = {
        'trading': {
            'initial_purchase_amount': "1.000",  # String decimal
            'min_trust_line_amount': 1000,      # Integer
            'max_trust_line_amount': 10000.0    # Float
        }
    }
    config_local.write_text(yaml.dump(numeric_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # Verify all numeric values are handled consistently
    assert isinstance(float(config.get('trading', 'initial_purchase_amount')), float)
    assert float(config.get('trading', 'initial_purchase_amount')) == 1.0
    assert isinstance(config.get('trading', 'min_trust_line_amount'), int)
    assert isinstance(float(config.get('trading', 'max_trust_line_amount')), float)

def test_config_type_safety(tmp_path, monkeypatch):
    """Test type safety and conversion of configuration values"""
    config_local = tmp_path / "config.local.yaml"
    type_data = {
        'network': {
            'max_reconnect_attempts': "5",    # String instead of int
            'reconnect_delay_seconds': 5.0    # Float instead of int
        },
        'trading': {
            'initial_purchase_amount': 1      # Int instead of string
        }
    }
    config_local.write_text(yaml.dump(type_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # Verify type handling
    assert isinstance(config.get('network', 'max_reconnect_attempts'), int)
    assert isinstance(config.get('network', 'reconnect_delay_seconds'), int)
    assert isinstance(config.get('trading', 'initial_purchase_amount'), str)

def test_empty_and_none_values(tmp_path, monkeypatch):
    """Test handling of empty and None values in configuration"""
    config_local = tmp_path / "config.local.yaml"
    empty_data = {
        'wallets': {
            'target_wallet': None,
            'follower_seed': ""
        },
        'trading': None,
        'network': {
            'websocket_url': ""
        }
    }
    config_local.write_text(yaml.dump(empty_data))

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
    
    # Verify empty/None values don't override defaults
    assert config.get('network', 'websocket_url') == config.DEFAULT_CONFIG['network']['websocket_url']
    assert config.get('trading', 'initial_purchase_amount') == config.DEFAULT_CONFIG['trading']['initial_purchase_amount']

def test_duplicate_keys_handling(tmp_path, monkeypatch):
    """Test handling of duplicate keys in YAML"""
    config_local = tmp_path / "config.local.yaml"        
    # Create YAML with duplicate keys (using valid XRPL endpoints)
    duplicate_yaml = """
    network:
        websocket_url: "wss://s1.ripple.com:51233"
    network:
        websocket_url: "wss://s2.ripple.com:51233"
    """
    config_local.write_text(duplicate_yaml)

    monkeypatch.chdir(tmp_path)
    config = Config(str(config_local))
        
    # Should use the last valid value in case of duplicates
    assert config.get('network', 'websocket_url') == "wss://s2.ripple.com:51233"