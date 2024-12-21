# XRPL Token Monitor

A robust, production-ready Python implementation for monitoring and automatically mirroring trust line operations on the XRP Ledger (XRPL). This tool provides real-time monitoring of specified wallets, automatic trust line replication, and configurable token purchasing capabilities.

## Key Features

- **Real-time Transaction Monitoring**: Establishes WebSocket connections to track XRPL transactions in real-time
- **Intelligent Trust Line Management**: 
  - Automatically detects and validates trust line operations
  - Implements configurable limits for trust line amounts
  - Ensures safe and controlled exposure levels
- **Automated Token Purchases**:
  - Configurable purchase amounts
  - Built-in safety mechanisms
  - Transaction validation
- **Production-Ready Features**:
  - Comprehensive error handling
  - Automatic reconnection logic
  - Detailed logging system
  - Test mode for safe deployment validation
  - Configuration management with local overrides

## System Requirements

- Python 3.10 or higher
- Network access for XRPL WebSocket connections
- Sufficient system memory for continuous operation
- Storage space for logging (if enabled)

## Installation

1. **Set Up Python Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Generate Configuration**:
   ```bash
   cp example.config.local.yaml config.local.yaml
   ```

## Wallet Setup

Use the included wallet generation utility to create new XRPL wallets:

```bash
python generate_wallet.py
```

The script will output wallet details in this format:
```json
{
  "public_address": "rXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "seed": "sXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
}
```

## Configuration

### Basic Configuration
Update `config.local.yaml` with:
- Target wallet address (wallet to monitor)
- Follower wallet seed (your operational wallet)
- WebSocket endpoint URL
- Trading parameters

### Advanced Settings

#### Trust Line Controls
```yaml
trading:
  min_trust_line_amount: "100"
  max_trust_line_amount: "10000"
  initial_purchase_amount: "10"
```

#### Logging Configuration
```yaml
logging:
  filename: "monitor.log"
  format: "%(asctime)s - %(levelname)s - %(message)s"
```

## Running the Monitor

### Standard Operation
```bash
python main.py
```

### Debug Mode
```bash
python main.py --debug
```

### Test Mode
```bash
python main.py --test
```

## Operational Features

### Error Handling
- Automatic reconnection on network issues
- Transaction validation
- Comprehensive error logging
- Graceful shutdown handling

### Safety Mechanisms
- Test mode for validation
- Configurable trust line limits
- Transaction amount constraints
- Automatic error recovery

### Monitoring and Logging
- Detailed transaction logging
- Operation status tracking
- Error reporting
- Performance metrics (when enabled)

## Troubleshooting

### Common Issues

1. **Connection Errors**
   - Verify network connectivity
   - Check WebSocket endpoint availability
   - Confirm firewall settings

2. **Transaction Failures**
   - Ensure sufficient XRP balance
   - Verify trust line limits
   - Check transaction parameters

3. **Configuration Issues**
   - Validate YAML syntax
   - Confirm wallet credentials
   - Check file permissions

### Debug Mode
Enable detailed logging with:
```bash
python main.py --debug
```

## Best Practices

1. **Production Deployment**
   - Use a dedicated server/instance
   - Implement proper monitoring
   - Regular log rotation
   - Secure credential management

2. **Risk Management**
   - Start with test mode
   - Use conservative trust line limits
   - Monitor transaction patterns
   - Regular balance checks

3. **Maintenance**
   - Regular log review
   - Performance monitoring
   - Configuration updates
   - System updates

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to your branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Security Considerations

- Secure storage of wallet seeds
- Regular security audits
- Network security best practices
- Access control implementation

## Support

For issues and feature requests, please use the GitHub issue tracker.

---

**Disclaimer**: This software is provided "as is" without warranty of any kind. Use at your own risk.