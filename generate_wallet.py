import json

from xrpl.wallet import Wallet

# Generate a new wallet
wallet = Wallet.create()

wallet_info = {
    "public_address": wallet.classic_address,
    "seed": wallet.seed
}

print("\nWallet Details:")
print(json.dumps(wallet_info, indent=2))

print("\nAdd this to your .env file:")
print(f"FOLLOWER_SEED={wallet.seed}")
print(f"Your public address is: {wallet.classic_address}")