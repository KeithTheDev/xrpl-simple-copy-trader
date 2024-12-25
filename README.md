# XRPL Token Monitor & Market Analyzer

A comprehensive Python toolkit for monitoring and analyzing token activities on the XRP Ledger (XRPL). This project consists of two main components: a token monitor for following and replicating trust line operations, and a market monitor for analyzing token trading patterns and trends.

## Features

### Token Monitor (`main.py`)
- Real-time monitoring of specified wallets' trust line operations
- Automatic trust line replication with configurable limits
- Smart token purchase system with built-in safety mechanisms
- Heartbeat monitoring for connection health
- Exponential backoff for reconnection attempts

### Market Monitor (`market_monitor.py`)
- Tracks token trust line adoption rates
- Monitors trading volumes and patterns
- Identifies "hot" tokens based on configurable metrics
- Persistent storage of token statistics
- Automatic data saving at configurable intervals

## System Requirements

- Python 3.10+
- Active XRPL node connection
- Dependencies listed in `requirements.txt`

## Installation

1. **Clone the repository and set up environment**:
   ```bash
   git clone [repository-url]
   cd xrpl-token-monitor
   python -m venv venv
   source venv/bin/activate  # Windows: .\venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the application**:
   ```bash
   cp example.config.local.yaml config.local.yaml
   ```

## Configuration

The application uses a layered configuration system with three levels:
- Default configuration (`config.yaml`)
- Local configuration (`config.local.yaml`)
- Command-line overrides (where applicable)

### Essential Settings (`config.local.yaml`)

```yaml
wallets:
  target_wallet: "rXXXXXXXXXXXXXXX"  # Wallet to monitor
  follower_seed: "sXXXXXXXXXXXXXXX"  # Your operational wallet seed

network:
  websocket_url: "wss://s.altnet.rippletest.net:51233"  # XRPL node

trading:
  initial_purchase_amount: "1"      # Amount to purchase on new trust lines
  min_trust_line_amount: "1000"     # Minimum trust line limit
  max_trust_line_amount: "10000"    # Maximum trust line limit
  send_max_xrp: "85"               # Maximum XRP to spend per purchase
  slippage_percent: "5"            # Allowed slippage percentage
```

### Market Monitoring Settings

```yaml
monitoring:
  min_trade_volume: 1000    # Minimum trade volume to track
  min_trust_lines: 5        # Trust lines threshold for "hot" tokens
  save_interval_minutes: 5   # Data save frequency
  data_file: "token_data.json"
```

## Usage

### Generate a New Wallet

```zsh
python3 generate_wallet.py
```

### Token Monitor

Experimental: The XPRL token monitor solution is started through a script. The script will start a webserver. Open http://0.0.0.0:8000 and start the token monitor from the web UI.

Standard mode:
```zsh
./start.sh
```

Test mode (no actual transactions):
```zsh
./start.sh --test
```

Debug mode:
```zsh
./start.sh --debug
```

### Market Monitor

Standard mode:
```bash
python market_monitor.py
```

With custom parameters:
```bash
python market_monitor.py --min-volume 5000 --min-trust-lines 10
```

## Safety Features

### Token Monitor
- Test mode for safe testing
- Configurable transaction limits
- Heartbeat monitoring
- Automatic reconnection with backoff
- Transaction validation checks

### Market Monitor
- Persistent data storage
- Configurable thresholds
- Regular data backups
- Error handling and recovery

## Development

### Testing

The project includes comprehensive test coverage using pytest. And yes, unit tests are crucial for maintaining code quality and reliability - even if you happen to be coding from somewhere in "the Industrial North" of England. Whether you're in Silicon Valley or Sheffield, investing in tests pays off through:

- **Reduced Production Incidents**: Tests catch bugs before they reach production, saving both time and reputation
- **Easier Refactoring**: With good test coverage, you can confidently modify code knowing the tests will catch regressions
- **Documentation**: Tests serve as executable documentation showing how components should behave
- **Faster Development**: While writing tests takes time initially, it saves time by catching issues early when they're cheaper to fix

The project's test suite includes:

- **test_config.py**: Validates configuration handling, type safety, and security settings
- **test_main.py**: Tests core monitoring functionality, transaction handling, and error recovery

Run the tests:
```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=.

# Run specific test file
pytest test_memecoin_monitor.py

# Run tests with detailed output
pytest -v

# Run tests and show locals in tracebacks
pytest -l
```

### Project Structure
```
├── memecoin_monitor.py              # Token monitor implementation
├── market_monitor.py    # Market analysis implementation
├── config.py           # Configuration management
├── generate_wallet.py  # Wallet generation utility
├── web_server.py       # Webserver for the monitoring web UI
├── start.sh            # Start script for Mac
├── startOnLinux.sh     # Start script for Linux - not tested
├── tests/
│   ├── test_memecoin_monitor.py
│   ├── test_config.py
│   └── test_websocket.py
└── config/
    ├── config.yaml
    └── example.config.local.yaml
```

## Error Handling

The application implements multiple layers of error handling:
- Network connection failures with automatic recovery
- Transaction validation and verification
- Configuration validation
- Data persistence errors
- WebSocket connection monitoring

## Best Practices for Production

1. **Security**:
   - Secure storage of wallet seeds
   - Regular security audits
   - Network security best practices
   - Access control implementation

2. **Monitoring**:
   - Set up external monitoring
   - Configure detailed logging
   - Regular log rotation
   - Health checks

3. **Maintenance**:
   - Regular backups of token data
   - System updates
   - Configuration reviews
   - Performance monitoring

## Support

For issues and feature requests, please use the GitHub issue tracker.

## License

MIT License - See LICENSE file for details.

## Disclaimer

This software is provided "as is" without warranty of any kind. Use at your own risk. The authors and contributors are not responsible for any trading losses or other damages that may occur from using this software.