# XRPL Alpha wallet finder & Copy trader


This README is out of date, and will be updated by Claude "wen tokens". Until then, here's the important stuff:

## Important stuff here, everything else is outdated

- The Alpha wallet finder is WORK IN PROGRESS. It starts and runs, hopefully.
- The Alpha wallet finder ONLY "works" on Mac for now.
- The Copy trader can start on Mac and Windows. The Linux script hasn't been tested.

To get this running at all:

- Python 3.10.16 or this will probably fail. Create an venv and do the usual pip install -r requirement.txt.
- Create your own config.local.yaml. Look at example.config.local.yaml and create your own config.local.yaml.
- To start the Copy trader on Mac: zsh start_copy_trader_on_mac.sh
- To start the Copy trader on Windows: start_copytrader_on_windows.cmd in Powershell
- To use the Copy trader: http://localhost:8000
- To start the Alpha wallet finder (only Mac compatible): zsh alpha_wallet_finder_scripts/run_alpha_wallet_finder.sh

## Old README, not too interesting

A comprehensive Python toolkit for monitoring and analyzing token activities on the XRP Ledger (XRPL). This project consists of two main components: a token monitor for following and replicating trust line operations, and a market monitor for analyzing token trading patterns and trends.

## Features

### Token Monitor (`memecoin_monitor.py`)
- Follow specific wallet's trust line operations in real-time
- Automatic trust line replication
- Smart token purchase system with built-in safety mechanisms
- Heartbeat monitoring
- Exponential backoff for reconnection attempts
- MongoDB storage for transactions and analysis
- Clean web interface for monitoring

## System Requirements

- Python 3.10 (specifically 3.10, not newer versions)
- MongoDB 4.x+
- Mac OS or Linux
- Active XRPL node connection
- Dependencies listed in `requirements.txt`

## Installation

1. **Ensure you have Python 3.10 installed**:
   ```bash
   # On Mac with Homebrew:
   brew install python@3.10
   
   # Verify version
   python3.10 --version  # Should show 3.10.x
   ```

2. **Clone the repository and set up environment**:
   ```bash
   git clone [repository-url]
   cd xrpl-token-monitor
   python3.10 -m venv venv   # Important: Use python3.10 specifically
   source venv/bin/activate  # Windows: .\venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up MongoDB**:
   On Mac:
   ```bash
   brew tap mongodb/brew
   brew install mongodb-community
   brew services start mongodb-community
   ```

## Configuration

The configuration consists of three main components:
1. A default configuration (`config.yaml`)
2. Your local configuration (`config.local.yaml`)
3. Your wallet (generated with `generate_wallet.py`)

### Setting Up Your Configuration

1. **First, create your wallet**:
   ```bash
   python generate_wallet.py
   ```
   This will output something like:
   ```
   Wallet Details:
   {
     "follower_wallet": "rXXXXXXXXXXXXXXX",
     "follower_seed": "sXXXXXXXXXXXXXXX"
   }
   ```
   IMPORTANT: 
   - The follower_wallet is your public XRPL address
   - The follower_seed is your private key - keep it secret and safe!

2. **Create your local configuration**:
   
   Create a new file called `config.local.yaml` with:
   ```yaml
   wallets:
     target_wallet: "rABCD..."    # Public address of the wallet you want to follow
     follower_seed: "sEFGH..."    # Your private seed from generate_wallet.py
     follower_wallet: "rIJKL..."  # Your public address from generate_wallet.py (optional)

   network:
     websocket_url: "wss://xrplcluster.com"  # XRPL node
   ```

   The three wallet settings are:
   - `target_wallet`: The public address (starts with 'r') of the wallet you want to follow
   - `follower_seed`: The private key (starts with 's') for your wallet - KEEP THIS SECRET!
   - `follower_wallet`: Your wallet's public address (optional, will be calculated from seed)

3. **Optional Settings**:
   ```yaml
   trading:
     initial_purchase_amount: "1"      # Amount to purchase on new trust lines
     min_trust_line_amount: "1000"     # Minimum trust line limit
     max_trust_line_amount: "10000"    # Maximum trust line limit
     send_max_xrp: "85"               # Maximum XRP to spend per purchase
     slippage_percent: "5"            # Allowed slippage percentage

   logging:
     level: "INFO"                     # DEBUG for more verbose output
     filename: "xrpl_trader.log"       # Log file location
   ```

## Usage

The system can be run in two modes:

1. **Web Interface (recommended)**:
   ```bash
   ./start.sh                  # Start web monitor
   ./start.sh --test          # Test mode (no real transactions)
   ./start.sh --debug         # Debug mode (more logging)
   ./start.sh --port 3000     # Custom port (default: 8000)
   ```

2. **Direct Monitor**:
   ```bash
   ./start.sh memecoin        # Start memecoin monitor directly
   ```

## Safety Features

- Test mode for safe testing
- Configurable transaction limits
- Heartbeat monitoring
- Auto-reconnection with exponential backoff
- Transaction validation

## Development

### Testing

Remember: Whether you're coding from sunny Silicon Valley or rainy Sheffield, investing in tests pays off through:
- **Fewer Production Incidents**: Tests catch bugs early
- **Easier Refactoring**: Tests catch regressions
- **Documentation**: Tests serve as executable docs
- **Faster Development**: Early issue detection saves time

Run tests with:
```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=.

# Run specific test file
pytest test_memecoin_monitor.py
```

### Project Structure
```
├── memecoin_monitor.py     # Main token monitor implementation
├── config.py              # Configuration management
├── web_server.py          # Web interface
├── start.sh              # Main start script
├── utils/
│   ├── db_handler.py     # MongoDB interface
│   ├── xrpl_base_monitor.py
│   ├── xrpl_transaction_parser.py
│   └── xrpl_logger.py
├── templates/
│   └── index.html        # Web UI template
└── config/
    ├── config.yaml       # Default config
    └── config.local.yaml # Your local config (create this)
```

## Support

For issues and feature requests, please use the GitHub issue tracker.

## Disclaimer

This software is provided "as is" without warranty of any kind. Use at your own risk. The authors and contributors are not responsible for any trading losses or other damages that may occur from using this software.