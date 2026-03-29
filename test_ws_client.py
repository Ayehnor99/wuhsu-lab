import asyncio
import websockets
import json
import urllib.request
import re

async def test_ws():
    # First get the token from the index page
    try:
        response = urllib.request.urlopen("http://127.0.0.1:8000")
        html = response.read().decode("utf-8")
        match = re.search(r'const SESSION_TOKEN = "(.*?)";', html)
        if not match:
            print("Token not found in HTML")
            return
        token = match.group(1)
        print(f"Found token: {token}")
    except Exception as e:
        print(f"Failed to fetch index: {e}")
        return

    uri = f"ws://127.0.0.1:8000/ws/terminal?token={token}"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            # Wait for some initial output (PowerShell banner)
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"Received message: {msg[:100]}")
            except asyncio.TimeoutError:
                print("Timed out waiting for message")
    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        if hasattr(e, 'status_code'):
            print(f"Status code: {e.status_code}")
        if hasattr(e, 'headers'):
            print(f"Headers: {e.headers}")

if __name__ == "__main__":
    asyncio.run(test_ws())
