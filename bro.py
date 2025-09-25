#!/usr/bin/env python3
"""
First-time setup script for owner's Telethon user account
Run this ONCE to authenticate your personal account
"""

import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELETHON_API_ID'))
API_HASH = os.getenv('TELETHON_API_HASH')

async def setup_user_account():
    """One-time setup for owner's personal Telethon account"""
    
    # Create user client with different session name
    client = TelegramClient('data/owner_session', API_ID, API_HASH)
    
    print("Setting up owner's Telethon account...")
    print("You'll need to enter your phone number and verification code")
    
    # Start client - will ask for phone and code
    await client.start()
    
    # Test it works
    me = await client.get_me()
    print(f"\n✅ Successfully authenticated as: {me.first_name} (@{me.username})")
    print(f"User ID: {me.id}")
    
    # List some groups to verify
    print("\n📋 Your groups (first 5):")
    async for dialog in client.iter_dialogs(limit=5):
        if dialog.is_group:
            print(f"  • {dialog.name} (ID: {dialog.id})")
    
    print("\n✅ Setup complete! The session is saved to data/owner_session.session")
    print("You can now use the user client in your bot")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(setup_user_account())