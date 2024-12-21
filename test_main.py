import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
import logging

from main import XRPLTokenMonitor
from config import Config

pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_config():
    config = Mock(spec=Config)
    def mock_get(*args, **kwargs):
        config_values = {
            ('wallets', 'target_wallet'): 'rTargetWalletAddress',
            ('wallets', 'follower_seed'): 'sEdTM1uX8pu2do5XvTnutH6HsouMaM2',
            ('network', 'websocket_url'): 'wss://test.net',
            ('trading', 'initial_purchase_amount'): '1',
            ('trading', 'min_trust_line_amount'): '1000',
            ('trading', 'max_trust_line_amount'): '10000',
            ('logging',): {'filename': 'xrpl_trader.log', 'format': '%(message)s'},
        }
        return config_values.get(args, kwargs.get('default'))
    config.get.side_effect = mock_get
    return config

@pytest.fixture
def mock_client():
    return AsyncMock()

@pytest.fixture
def monitor(mock_config):
    with patch('main.Wallet') as MockWallet:
        MockWallet.from_seed.return_value = Mock(classic_address="rTestAddress123")
        return XRPLTokenMonitor(mock_config)

@pytest.fixture
def monitor_test_mode(mock_config):
    with patch('main.Wallet') as MockWallet:
        MockWallet.from_seed.return_value = Mock(classic_address="rTestAddress123")
        return XRPLTokenMonitor(mock_config, test_mode=True)

async def test_handle_trust_set_test_mode(monitor_test_mode, mock_client, caplog):
    """Test handling TrustSet transaction in test mode"""
    test_tx = {
        "TransactionType": "TrustSet",
        "Account": monitor_test_mode.target_wallet,
        "LimitAmount": {
            "currency": "USD",
            "issuer": "rIssuerAddress",
            "value": "5000"
        }
    }
    
    await monitor_test_mode.handle_trust_set(mock_client, test_tx)
    
    assert "Target wallet set new trust line:" in caplog.text
    assert "TEST MODE: Would set trust line for USD" in caplog.text
    assert not mock_client.send.called

async def test_debug_logging(mock_config, caplog):
    """Test debug mode logging setup"""
    with patch('main.Wallet') as MockWallet:
        MockWallet.from_seed.return_value = Mock(classic_address="rTestAddress123")
        monitor = XRPLTokenMonitor(mock_config, debug=True)
        
        assert monitor.logger.level == logging.DEBUG
        assert "Debug mode enabled" in caplog.text

async def test_transaction_validation(monitor, mock_client):
    """Test transaction validation"""
    # Invalid transaction (missing LimitAmount)
    invalid_tx = {
        "TransactionType": "TrustSet",
        "Account": monitor.target_wallet
    }
    
    await monitor.handle_trust_set(mock_client, invalid_tx)
    assert not mock_client.send.called

    # Wrong account
    wrong_account_tx = {
        "TransactionType": "TrustSet",
        "Account": "rWrongAddress",
        "LimitAmount": {
            "currency": "USD",
            "issuer": "rIssuerAddress",
            "value": "5000"
        }
    }
    
    await monitor.handle_trust_set(mock_client, wrong_account_tx)
    assert not mock_client.send.called

async def test_successful_trust_set(monitor, mock_client):
    """Test successful trust set operation"""
    # Mock Payment response
    mock_payment_response = Mock()
    mock_payment_response.result = {'meta': {'TransactionResult': 'tesSUCCESS'}}
    
    # Mock TrustSet response
    mock_trust_response = Mock()
    mock_trust_response.result = {'meta': {'TransactionResult': 'tesSUCCESS'}}
    
    test_tx = {
        "TransactionType": "TrustSet",
        "Account": monitor.target_wallet,
        "LimitAmount": {
            "currency": "USD",
            "issuer": "rIssuerAddress",
            "value": "5000"
        }
    }

    # Setup submit_and_wait to return different responses for TrustSet and Payment
    submit_responses = [mock_trust_response, mock_payment_response]
    mock_submit = AsyncMock(side_effect=submit_responses)

    with patch('main.submit_and_wait', mock_submit):
        await monitor.handle_trust_set(mock_client, test_tx)
        
        # Verify both trust line and purchase were attempted
        assert mock_submit.call_count == 2
        
        # Check that both calls were made with the correct transaction types
        first_call = mock_submit.call_args_list[0]
        second_call = mock_submit.call_args_list[1]
        assert first_call[1]['transaction'].transaction_type == "TrustSet"
        assert second_call[1]['transaction'].transaction_type == "Payment"