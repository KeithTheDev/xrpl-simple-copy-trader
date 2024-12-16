import asyncio
import json
import os
from decimal import Decimal
from typing import Any, Dict

from dotenv import load_dotenv
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import StreamParameter, Subscribe
from xrpl.models.transactions import Payment, TrustSet
from xrpl.utils import xrp_to_drops
from xrpl.wallet import Wallet

# Load environment variables
load_dotenv()

class XRPLTokenMonitor:
    def __init__(self, target_wallet: str, follower_seed: str, websocket_url: str):
        self.target_wallet = target_wallet
        self.follower_wallet = Wallet.from_seed(follower_seed)
        self.websocket_url = websocket_url
        self.client = None
        self.initial_purchase_amount = os.getenv('INITIAL_PURCHASE_AMOUNT', '1')
        self.min_trust_line_amount = os.getenv('MIN_TRUST_LINE_AMOUNT', '1000')
        self.max_trust_line_amount = os.getenv('MAX_TRUST_LINE_AMOUNT', '10000')

    async def connect(self):
        """Establish connection to XRPL"""
        print(f"Connecting to {self.websocket_url}...")
        self.client = AsyncWebsocketClient(self.websocket_url)
        await self.client.open()
        print("Connected to XRPL")
        print(f"Follower wallet address: {self.follower_wallet.classic_address}")

        # Subscribe to target wallet transactions
        subscribe_request = Subscribe(
            streams=[StreamParameter.TRANSACTIONS],
            accounts=[self.target_wallet]
        )
        
        try:
            response = await self.client.send(subscribe_request)
            print(f"Subscription response: {response}")
            print(f"Subscribed to target wallet: {self.target_wallet}")
        except Exception as e:
            print(f"Subscription error: {str(e)}")
            raise

    async def handle_transaction(self, tx: Dict[str, Any]):
        """Process incoming transactions"""
        transaction_data = tx.get("transaction", {})
        # *** CHANGE MADE HERE: Check that transaction's Account matches the target_wallet ***
        if transaction_data.get("TransactionType") == "TrustSet" and transaction_data.get("Account") == self.target_wallet:
            await self.handle_trust_set(transaction_data)

    async def handle_trust_set(self, tx: Dict[str, Any]):
        """Handle TrustSet transactions"""
        limit_amount = tx.get("LimitAmount", {})
        if not isinstance(limit_amount, dict):
            return

        currency = limit_amount.get("currency")
        issuer = limit_amount.get("issuer")
        limit = limit_amount.get("value")

        if not all([currency, issuer, limit]):
            return

        print(f"\nDetected new trust line from target wallet:")
        print(f"Currency: {currency}")
        print(f"Issuer: {issuer}")
        print(f"Limit: {limit}")

        # Set our own trust line
        try:
            await self.set_trust_line(currency, issuer, limit)
            # Make a small purchase
            await self.make_small_purchase(currency, issuer)
        except Exception as e:
            print(f"Error: {str(e)}")

    async def set_trust_line(self, currency: str, issuer: str, limit: str):
        """Set a trust line for the token"""
        print(f"Setting trust line for {currency}...")
        
        # Use the configured trust line amount, but don't exceed the original limit
        trust_limit = min(
            float(limit), 
            float(self.max_trust_line_amount)
        )
        trust_limit = max(
            trust_limit, 
            float(self.min_trust_line_amount)
        )
        
        trust_set_tx = TrustSet(
            account=self.follower_wallet.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=str(trust_limit)
            )
        )
        
        try:
            response = await submit_and_wait(
                transaction=trust_set_tx,
                client=self.client,
                wallet=self.follower_wallet
            )
            print(f"Trust line set: {response.result.get('meta').get('TransactionResult')}")
            
            if response.result.get('meta').get('TransactionResult') != "tesSUCCESS":
                raise Exception(f"Trust line setting failed: {response.result.get('meta').get('TransactionResult')}")
                
        except Exception as e:
            print(f"Error setting trust line: {str(e)}")
            raise

    async def make_small_purchase(self, currency: str, issuer: str):
        """Make a small purchase of the token"""
        print(f"Attempting small purchase of {currency}...")
        
        payment = Payment(
            account=self.follower_wallet.classic_address,
            destination=issuer,
            amount=IssuedCurrencyAmount(
                currency=currency,
                issuer=issuer,
                value=self.initial_purchase_amount
            )
        )
        
        try:
            response = await submit_and_wait(
                transaction=payment,
                client=self.client,
                wallet=self.follower_wallet
            )
            print(f"Purchase attempt result: {response.result.get('meta').get('TransactionResult')}")
            
            if response.result.get('meta').get('TransactionResult') != "tesSUCCESS":
                raise Exception(f"Purchase failed: {response.result.get('meta').get('TransactionResult')}")
                
        except Exception as e:
            print(f"Error making purchase: {str(e)}")
            raise

    async def monitor(self):
        """Main monitoring loop"""
        print("Starting monitoring...")
        try:
            async for message in self.client:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        print(f"Failed to parse message: {message}")
                        continue
                else:
                    data = message
                
                if "type" in data and data["type"] == "transaction":
                    await self.handle_transaction(data)
                
        except KeyboardInterrupt:
            print("\nStopping monitor...")
        except Exception as e:
            print(f"Error in monitoring loop: {str(e)}")
        finally:
            if self.client:
                await self.client.close()

async def main():
    # Load configuration from environment variables
    target_wallet = os.getenv('TARGET_WALLET')
    follower_seed = os.getenv('FOLLOWER_SEED')
    websocket_url = os.getenv('XRPL_WEBSOCKET_URL')

    # Validate required environment variables
    if not all([target_wallet, follower_seed, websocket_url]):
        print("Error: Missing required environment variables.")
        print("Please ensure TARGET_WALLET, FOLLOWER_SEED, and XRPL_WEBSOCKET_URL are set in .env")
        return

    monitor = XRPLTokenMonitor(target_wallet, follower_seed, websocket_url)
    try:
        await monitor.connect()
        await monitor.monitor()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
    finally:
        if monitor.client:
            await monitor.client.close()

if __name__ == "__main__":
    asyncio.run(main())