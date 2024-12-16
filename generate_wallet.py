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

print("\nAdd these values to your config.local.yaml:")
print(f"target_wallet: {wallet.classic_address}")
print(f"follower_seed: {wallet.seed}")