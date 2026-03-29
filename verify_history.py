import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
_BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(_BASE_DIR))

from wuhsu_agent import WuhsuService

async def verify():
    print("[*] Starting Verification of Conversation History...")
    session_id = "verify_session_999"
    
    # Step 1: First Query
    print(f"\n[1] Sending first query: 'My favorite tool is nmap.'")
    resp1 = await WuhsuService.process_query(
        session_id=session_id,
        query="My favorite tool is nmap.",
        terminal_context=""
    )
    print(f"Assistant: {resp1['text'][:100]}...")

    # Step 2: Follow-up Query
    print(f"\n[2] Sending follow-up query: 'What was the tool I just mentioned?'")
    resp2 = await WuhsuService.process_query(
        session_id=session_id,
        query="What was the tool I just mentioned?",
        terminal_context=""
    )
    print(f"Assistant: {resp2['text']}")

    # Step 3: Check for 'nmap' in second response
    if "nmap" in resp2['text'].lower():
        print("\n✅ SUCCESS: Agent remembered the context!")
    else:
        print("\n❌ FAILURE: Agent forgot the context.")

if __name__ == "__main__":
    asyncio.run(verify())
