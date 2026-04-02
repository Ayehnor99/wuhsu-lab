import asyncio
import json
import websockets

async def test_terminal_mirror():
    try:
        # Connect host to trigger room creation and global active_coop_room_id update
        host_ws = await websockets.connect("ws://127.0.0.1:8000/ws/multiplayer/TEST_ROOM?role=host")
        print("[+] Host connected to signaling")
        
        # Connect a mock terminal to the PTY endpoint
        terminal_ws = await websockets.connect("ws://127.0.0.1:8000/ws/terminal")
        print("[+] Terminal connected to PTY")
        
        # Send a command to the terminal to generate output
        print("[+] Sending 'ls' to terminal")
        await terminal_ws.send(json.dumps({"type": "input", "data": "ls\r"}))
        
        # Now wait for the mirror broadcast on the Host's signaling websocket
        try:
            while True:
                msg = await asyncio.wait_for(host_ws.recv(), timeout=2.0)
                payload = json.loads(msg)
                print(f"[!] Host received on signaling: {payload.get('type')}")
                if payload.get("type") == "terminal_mirror":
                    print(f"      Data: {payload.get('data')[:50]}...")
                    return True
        except asyncio.TimeoutError:
            print("[-] Timed out waiting for terminal_mirror on host signaling")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

asyncio.run(test_terminal_mirror())
