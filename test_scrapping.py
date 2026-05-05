import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from datetime import datetime

# --- CONFIGURATION ---
API_ID=36476816
API_HASH='ec3b8735da59c916f1b0b281a14cfe84'
CHANNEL_USERNAME = 'ADSapple'    # Replace with target channel username (without @)
SESSION_NAME = 'user_session' # Name for the session file
LIMIT = 5                 # Number of messages to fetch
# ---------------------



async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    await client.start() # This will ask for your PHONE NUMBER and CODE
    print("Client Created")

    try:
        entity = await client.get_entity(CHANNEL_USERNAME)
        print(f"Connected to: {entity.title}")

        messages = await client.get_messages(entity, limit=LIMIT)
        
        for msg in messages:
            print(f"[{msg.date}] {msg.text[:50]}...")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())