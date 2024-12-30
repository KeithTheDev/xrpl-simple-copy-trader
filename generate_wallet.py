# generate_wallet.py

import json
from xrpl.wallet import Wallet

# Generate a new wallet
wallet = Wallet.create()

wallet_info = {
    "follower_wallet": wallet.classic_address,   # Public XRPL address
    "follower_seed": wallet.seed                 # Private seed (keep secret!)
}

print("\nWallet Details:")
print(json.dumps(wallet_info, indent=2))

print("\nAdd these values to your config.local.yaml:")
print("wallets:")
print(f"  follower_wallet: \"{wallet.classic_address}\"  # Your public XRPL address")
print(f"  follower_seed: \"{wallet.seed}\"  # Your private seed - keep this secret!")
print("  target_wallet: \"\"  # Add the public address (starting with 'r') of the wallet you want to follow")