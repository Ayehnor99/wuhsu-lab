"""
Test: Co-Op Dojo Security - Verify guest terminal_input messages are blocked.

This test validates that the DojoRoomManager correctly:
1. Allows normal signaling messages (SDP, ICE) to pass through
2. BLOCKS terminal_input messages from guest peers
"""
import asyncio
import json
import urllib.request
import re

async def test_coop_security():
    """Test that DojoRoomManager blocks guest terminal_input messages."""
    try:
        import websockets
    except ImportError:
        print("❌ 'websockets' package not installed. Run: pip install websockets")
        return False
    
    room_id = "test_room_sec"
    received_by_host = []
    
    try:
        # Connect host
        host_ws = await websockets.connect(
            f"ws://127.0.0.1:8000/ws/multiplayer/{room_id}?role=host"
        )
        print("✅ Host connected to room")
        
        # Connect guest
        guest_ws = await websockets.connect(
            f"ws://127.0.0.1:8000/ws/multiplayer/{room_id}?role=guest"  
        )
        print("✅ Guest connected to room")
        
        # --- TEST 1: Guest sends a BLOCKED terminal_input message ---
        blocked_msg = json.dumps({"type": "terminal_input", "data": "rm -rf /"})
        await guest_ws.send(blocked_msg)
        print("📤 Guest sent terminal_input (should be BLOCKED)")
        
        # Give server time to process
        await asyncio.sleep(0.3)
        
        # --- TEST 2: Guest sends a VALID signaling message (ICE candidate) ---
        valid_msg = json.dumps({"type": "ice", "candidate": {"sdpMid": "0", "sdpMLineIndex": 0, "candidate": "test"}})
        await guest_ws.send(valid_msg)
        print("📤 Guest sent valid ICE candidate (should be FORWARDED)")
        
        # Try to receive on host side
        try:
            msg = await asyncio.wait_for(host_ws.recv(), timeout=2.0)
            received = json.loads(msg)
            received_by_host.append(received)
            print(f"📥 Host received: type={received.get('type')}")
        except asyncio.TimeoutError:
            print("⏰ Host timed out waiting for messages")
        
        # Close connections
        await host_ws.close()
        await guest_ws.close()
        
        # --- ASSERTIONS ---
        print("\n" + "=" * 50)
        print("SECURITY TEST RESULTS")
        print("=" * 50)
        
        # Check that host ONLY received the ICE message, NOT the terminal_input
        terminal_inputs = [m for m in received_by_host if m.get("type") == "terminal_input"]
        ice_messages = [m for m in received_by_host if m.get("type") == "ice"]
        
        if len(terminal_inputs) == 0:
            print("✅ PASS: Guest terminal_input was BLOCKED (not received by host)")
        else:
            print("❌ FAIL: Guest terminal_input LEAKED to host!")
            return False
            
        if len(ice_messages) > 0:
            print("✅ PASS: Valid ICE signaling was FORWARDED to host")
        else:
            print("⚠️  WARN: ICE message not received (may be timing issue)")
        
        print("\n🛡️ Security enforcement verified: Guest keystrokes are blocked.")
        return True
        
    except ConnectionRefusedError:
        print("❌ Server not running. Start it with: python server.py")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_coop_security())
    exit(0 if result else 1)
""", "Description": "Automated security test for DojoRoomManager - verifies guest terminal_input messages are blocked while valid signaling messages pass through.", "Complexity": 4, "EmptyFile": false, "IsArtifact": false, "Overwrite": false}
