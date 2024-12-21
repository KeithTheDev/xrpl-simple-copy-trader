import asyncio
import json
import logging
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import Subscribe

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the WebSocket URL and the account to monitor
WEBSOCKET_URL = "wss://s1.ripple.com/"
ACCOUNT = "r4MbVx6ZksLuwJQVT7x1majPpfVQFDFpK7"

async def listen_to_account():
    try:
        async with AsyncWebsocketClient(WEBSOCKET_URL) as client:
            logger.info(f"Connected to {WEBSOCKET_URL}")

            # Create a subscription request for the specified account
            subscribe_request = Subscribe(accounts=[ACCOUNT])
            await client.send(subscribe_request)
            logger.info(f"Subscribed to account: {ACCOUNT}")

            # Continuously listen for incoming messages
            async for message in client:
                logger.info(f"Received message: {json.dumps(message, indent=2)}")

    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(listen_to_account())