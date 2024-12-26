import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from memecoin_monitor import XRPLTokenMonitor
from config import Config
from xrpl.asyncio.clients import AsyncWebsocketClient
import websockets.exceptions

class TestXRPLTokenMonitor:
    @pytest.fixture
    def config(self):
        config = Config()
        config.data = {
            'wallets': {
                'target_wallet': 'rTargetWallet',
                'follower_seed': 'sFollowerSeed'
            },
            'network': {
                'websocket_url': 'wss://test.net'
            },
            'trading': {
                'initial_purchase_amount': '1',
                'min_trust_line_amount': '1000',
                'max_trust_line_amount': '10000',
                'send_max_xrp': '85',
                'slippage_percent': '5'
            }
        }
        return config

    @pytest.fixture
    def monitor(self, config):
        return XRPLTokenMonitor(config, debug=True, test_mode=True)

    @pytest.fixture
    def mock_client(self):
        return AsyncMock(spec=AsyncWebsocketClient)

    @pytest.fixture
    def sample_trustset_tx(self):
        return {
            "TransactionType": "TrustSet",
            "Account": "rTargetWallet",
            "hash": "test_hash",
            "LimitAmount": {
                "currency": "TEST",
                "issuer": "rTestIssuer",
                "value": "1000"
            }
        }

    @pytest.mark.asyncio
    async def test_monitor_initialization(self, monitor):
        assert monitor.test_mode == True
        assert monitor.is_running == False
        assert monitor.ping_interval == 30
        assert monitor.ping_timeout == 10

    @pytest.mark.asyncio
    async def test_trustset_handling(self, monitor, mock_client, sample_trustset_tx):
        # Test handling of a valid TrustSet transaction
        await monitor.handle_trust_set(mock_client, sample_trustset_tx)
        # In test mode, should log but not make actual transactions
        mock_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_trustset_handling(self, monitor, mock_client):
        # Test with missing LimitAmount
        invalid_tx = {
            "TransactionType": "TrustSet",
            "Account": "rTargetWallet",
            "hash": "test_hash"
        }
        await monitor.handle_trust_set(mock_client, invalid_tx)
        mock_client.send.assert_not_called()

        # Test with wrong account
        wrong_account_tx = {
            "TransactionType": "TrustSet",
            "Account": "rWrongAccount",
            "hash": "test_hash",
            "LimitAmount": {
                "currency": "TEST",
                "issuer": "rTestIssuer",
                "value": "1000"
            }
        }
        await monitor.handle_trust_set(mock_client, wrong_account_tx)
        mock_client.send.assert_not_called()

    def test_transaction_logging(self, monitor, caplog):
        with caplog.at_level(logging.INFO):
            # Simulate transaction validation
            tx = {
                "hash": "test_hash",
                "TransactionType": "TrustSet"
            }
            asyncio.run(monitor._log_transaction(tx, True))
            assert "Transaction test_hash is now validated" in caplog.text

    @pytest.mark.asyncio
    async def test_reconnect_logic(self, monitor, mock_client):
        monitor_task = None
        reconnect_sleep_delays = []
        
        try:
            async def mock_sleep(delay, *args, **kwargs):
                reconnect_sleep_delays.append(delay)
                # Don't actually sleep, just record the delay
                
            # Set up a sequence of connection attempts
            mock_client.__aenter__.side_effect = [
                websockets.exceptions.ConnectionClosed(1006, "Connection lost"),
                mock_client,  # Second attempt succeeds
            ]
            
            def mock_client_factory(url):
                return mock_client
                
            with patch('xrpl.asyncio.clients.AsyncWebsocketClient', side_effect=mock_client_factory):
                with patch('asyncio.sleep', mock_sleep):
                    monitor.is_running = True
                    
                    # Run monitor briefly
                    monitor_task = asyncio.create_task(monitor.monitor())
                    
                    # Let a few event loop iterations happen
                    for _ in range(5):
                        await asyncio.sleep(0)
                        
                    print("\nAll sleep delays requested:")
                    for delay in reconnect_sleep_delays:
                        print(f"Sleep delay: {delay}")
                        
                    assert 5 in reconnect_sleep_delays, "5 second reconnect delay not found"
                    
        finally:
            if monitor_task:
                monitor.is_running = False
                monitor_task.cancel()
                try:
                    await monitor_task
                except (asyncio.CancelledError, Exception):
                    pass
            
    @pytest.mark.asyncio
    async def test_heartbeat(self, monitor, mock_client):
        heartbeat_task = None
        try:
            # Reduce ping interval for test
            monitor.ping_interval = 0.05  # 50ms instead of 30s
            monitor.last_pong = asyncio.get_event_loop().time()
            heartbeat_task = asyncio.create_task(monitor._heartbeat(mock_client))
            
            # Let it run long enough for a ping
            await asyncio.sleep(0.1)

            # Verify ping was sent
            mock_client.send.assert_called()
        finally:
            # Cancel and cleanup
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_stop_monitor(self, monitor):
        # Start monitor
        monitor.is_running = True
        
        # Stop monitor
        await monitor.stop()
        assert monitor.is_running == False

    @pytest.mark.asyncio
    async def test_purchase_validation(self, monitor, mock_client):
        # Test purchase validation in test mode
        await monitor.make_small_purchase(mock_client, "TEST", "rTestIssuer")
        # Should not make actual purchase in test mode
        mock_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_line_limits(self, monitor, mock_client):
        # Test trust line amount capping
        min_limit = float(monitor.config.get('trading', 'min_trust_line_amount'))
        max_limit = float(monitor.config.get('trading', 'max_trust_line_amount'))
        
        # Test with amount below minimum
        await monitor.set_trust_line(mock_client, "TEST", "rTestIssuer", str(min_limit / 2))
        # Test with amount above maximum
        await monitor.set_trust_line(mock_client, "TEST", "rTestIssuer", str(max_limit * 2))
        
        # In test mode, no actual transactions should be made
        mock_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_subscription(self, monitor, mock_client):
        monitor_task = None
        try:
            with patch('memecoin_monitor.AsyncWebsocketClient', return_value=mock_client):
                mock_client.__aenter__.return_value = mock_client
                monitor.is_running = True
                
                monitor_task = asyncio.create_task(monitor.monitor())
                await asyncio.sleep(0.1)  # Give it time to send Subscribe
                
                # Verify that Subscribe was sent
                assert any(
                    call.args and 'Subscribe' in str(call.args[0]) 
                    for call in mock_client.send.mock_calls
                )
        finally:
            if monitor_task:
                monitor.is_running = False
                monitor_task.cancel()
                try:
                    await monitor_task
                except (asyncio.CancelledError, Exception):
                    pass