A Simple XRPL Copy-Trader

This repository provides a degen-friendly, easy-to-get-started, Python-based copy-trader for the XRP Ledger (XRPL). The tool connects to an XRPL WebSocket endpoint, subscribes to transaction streams for a specified target wallet, and automatically responds to newly created trust lines by setting a corresponding trust line and attempting a small token purchase.

## Features

- **Automatic Trust Line Detection**: Monitors a target XRPL account for new `TrustSet` transactions.
- **Responsive Trust Line Creation**: When a trust line is detected from the target wallet, the follower (your) account automatically sets a corresponding trust line.
- **Small Purchase Attempt**: After establishing the trust line, the tool attempts a small token purchase to confirm and exercise that trust line.

## Prerequisites

- **Python 3.7+**: Ensure Python is installed and up-to-date.
- **Pip & Virtual Environment**: Use a virtual environment for isolated dependency management.
- **Network Access**:  
  - Testnet endpoint example: `wss://s.altnet.rippletest.net:51233`
- **Funded XRPL Accounts**:  
  - **Target Wallet**: The account whose transactions you’ll monitor.  
  - **Follower Wallet**: The account that will respond by setting trust lines and making purchases. **Important:** This follower account must be funded on the XRPL testnet to avoid `actNotFound` errors.

## Environment Variables

Create a `.env` file in the repository root with the following variables:

- `TARGET_WALLET`: The XRPL classic address of the target wallet.
- `FOLLOWER_SEED`: The secret seed for the follower account. **Keep this secret.**
- `XRPL_WEBSOCKET_URL`: The XRPL WebSocket endpoint.

Optional environment variables:
- `INITIAL_PURCHASE_AMOUNT`: How much of the issued currency to purchase after setting a trust line. Default: `1`.
- `MIN_TRUST_LINE_AMOUNT`: Minimum trust line amount to set. Default: `1000`.
- `MAX_TRUST_LINE_AMOUNT`: Maximum trust line amount to set. Default: `10000`.

**How MIN and MAX Trust Line Amounts Work:**
When a new trust line is detected, the code takes the trust limit specified in that transaction and ensures it falls within the range defined by `MIN_TRUST_LINE_AMOUNT` and `MAX_TRUST_LINE_AMOUNT`. If the original limit is lower than `MIN_TRUST_LINE_AMOUNT`, it is raised to that minimum. If it exceeds `MAX_TRUST_LINE_AMOUNT`, it is capped at that maximum. This mechanism helps maintain a controlled and safe exposure level for your trust lines.

** Example `.env`:**

   ```env
   TARGET_WALLET=rXXXXXXXXXXXXXXX
   FOLLOWER_SEED=sXXXXXXXXXXXXXXX
   XRPL_WEBSOCKET_URL=wss://s.altnet.rippletest.net:51233
   INITIAL_PURCHASE_AMOUNT=1
   MIN_TRUST_LINE_AMOUNT=1000
   MAX_TRUST_LINE_AMOUNT=10000
   ```


## Generating a Follower Wallet

Use the included `wallet_generator.py` script to quickly create a new wallet and retrieve its seed and address. **Note:** This is primarily useful for testnet development, not for production use.

   ```bash
   python wallet_generator.py
   ```
Example Output:


   ```json
   {
     "public_address": "rExampleAddress123...",
     "seed": "sExampleSeed123..."
   }
   ```

Add this to your .env file:
FOLLOWER_SEED=sExampleSeed123...
Your public address is: rExampleAddress123...

Copy the FOLLOWER_SEED into your .env file and fund the newly created address with testnet XRP from the XRP Testnet Faucet.


## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/KeithTheDev/xrpl-simple-copytrader.git
   cd xrpl-simple-copytrader
   ```
2. **Create and Activate a Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. Set Up Environment Variables: Create your .env file as described above.

## Running the Monitor

After ensuring both the target and follower accounts are funded:

   ```bash
   python main.py
   ```

## Common Issues

- **`actNotFound: Account not found`**:  
  The follower account is not active on the ledger. Fund it via the [XRP Testnet Faucet](https://xrpl.org/xrp-testnet-faucet.html).

- **Unexpected TrustSet Transactions**:  
  Ensure the code checks the transaction’s `Account` field to verify that the target wallet is the originator before reacting.

## Contributing

Contributions are welcome!  
Please open an issue or submit a pull request with improvements, fixes, or ideas.

## License

This project is licensed under the [MIT License](LICENSE).