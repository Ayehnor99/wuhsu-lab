"""
screen_share_server.py — Enterprise WebRTC Screen Share Signaling Server
=========================================================================
Provides:
  - POST /screen/rooms  → Create a new screen-share room (returns room_id, invite_token, ice_servers)
  - screen_share_websocket() → WebSocket signaling handler for presenter/viewer negotiation

Security:
  - JWT-based invite tokens for viewer authentication
  - Presenter creates room, viewers must present valid token to join
  - All messages are role-validated before forwarding
"""

import os
import json
import hmac
import hashlib
import base64
import time
import uuid
import logging
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

audit_logger = logging.getLogger("wuhsu.audit")

# ── JWT Secret (per-process, rotates on restart) ──
_JWT_SECRET = os.urandom(32).hex()

# ── Room Storage ──
_rooms: Dict[str, dict] = {}

# ── ICE Servers ──
DEFAULT_ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]

router = APIRouter(prefix="/screen", tags=["screen-share"])


# ═══════════════════════════════════════
# JWT Helpers (lightweight, no dependency)
# ═══════════════════════════════════════
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _create_token(room_id: str, role: str = "viewer", ttl: int = 3600) -> str:
    """Create a minimal JWT token for room access."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "room_id": room_id,
        "role": role,
        "exp": int(time.time()) + ttl,
        "jti": uuid.uuid4().hex[:8],
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())
    signature = hmac.new(
        _JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    sig = _b64url_encode(signature)
    return f"{header}.{payload}.{sig}"


def _verify_token(token: str, room_id: str) -> bool:
    """Verify a JWT token for a specific room."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False

        header_part, payload_part, sig_part = parts

        # Verify signature
        expected_sig = hmac.new(
            _JWT_SECRET.encode(),
            f"{header_part}.{payload_part}".encode(),
            hashlib.sha256,
        ).digest()
        actual_sig = _b64url_decode(sig_part)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return False

        # Verify payload
        payload_data = json.loads(_b64url_decode(payload_part))

        if payload_data.get("room_id") != room_id:
            return False
        if payload_data.get("exp", 0) < time.time():
            return False

        return True
    except Exception:
        return False


# ═══════════════════════════════════════
# REST API
# ═══════════════════════════════════════
class CreateRoomRequest(BaseModel):
    presenter_id: str = "anonymous"
    title: str = "Screen Share"


class CreateRoomResponse(BaseModel):
    room_id: str
    invite_token: str
    ice_servers: list
    title: str


@router.post("/rooms", response_model=CreateRoomResponse)
async def create_room(req: CreateRoomRequest):
    """Create a new screen-share room. Returns room_id and invite_token for viewers."""
    room_id = uuid.uuid4().hex[:12]
    invite_token = _create_token(room_id, role="viewer", ttl=7200)

    _rooms[room_id] = {
        "presenter_id": req.presenter_id,
        "title": req.title,
        "created_at": time.time(),
        "presenter_ws": None,
        "viewers": {},  # viewer_id -> WebSocket
    }

    audit_logger.info(f"🎬 [Screen Share] Room created: {room_id} by {req.presenter_id}")

    return CreateRoomResponse(
        room_id=room_id,
        invite_token=invite_token,
        ice_servers=DEFAULT_ICE_SERVERS,
        title=req.title,
    )


# ═══════════════════════════════════════
# WebSocket Signaling Handler
# ═══════════════════════════════════════
async def screen_share_websocket(
    websocket: WebSocket,
    room_id: str,
    role: str = "viewer",
    token: str = "",
    user_id: str = "anonymous",
    display_name: str = "Guest",
):
    """
    Enterprise WebRTC signaling handler.

    Presenter: Creates offers, sends ICE candidates targeted at specific viewers.
    Viewer:    Receives offers, sends answers and ICE candidates back to presenter.

    Message types handled:
      - viewer_joined (server → presenter): A new viewer connected
      - webrtc_offer (presenter → viewer): SDP offer with target_viewer_id
      - webrtc_answer (viewer → presenter): SDP answer
      - webrtc_ice (bidirectional): ICE candidates
    """

    # ── Room validation ──
    if room_id not in _rooms:
        await websocket.close(code=4004, reason="Room not found")
        return

    room = _rooms[room_id]

    # ── Viewer token validation ──
    if role == "viewer":
        if not token or not _verify_token(token, room_id):
            audit_logger.warning(
                f"🚨 [Screen Share] Viewer rejected for room {room_id} — invalid token"
            )
            await websocket.close(code=4001, reason="Invalid or expired token")
            return

    await websocket.accept()
    audit_logger.info(
        f"🎬 [Screen Share] {role} '{display_name}' ({user_id}) joined room {room_id}"
    )

    # ── Register connection ──
    if role == "presenter":
        room["presenter_ws"] = websocket
    else:
        viewer_key = user_id if user_id != "anonymous" else f"guest_{uuid.uuid4().hex[:6]}"
        room["viewers"][viewer_key] = websocket

        # Notify presenter that a viewer joined
        if room["presenter_ws"]:
            try:
                await room["presenter_ws"].send_text(
                    json.dumps(
                        {
                            "type": "viewer_joined",
                            "viewer_id": viewer_key,
                            "display_name": display_name,
                        }
                    )
                )
            except Exception:
                pass

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if role == "presenter":
                # Presenter sends offers and ICE candidates to specific viewers
                if msg_type == "webrtc_offer":
                    target_id = msg.get("target_viewer_id")
                    target_ws = room["viewers"].get(target_id)
                    if target_ws:
                        await target_ws.send_text(
                            json.dumps({"type": "webrtc_offer", "sdp": msg.get("sdp")})
                        )

                elif msg_type == "webrtc_ice":
                    target_id = msg.get("target_viewer_id")
                    if target_id:
                        target_ws = room["viewers"].get(target_id)
                        if target_ws:
                            await target_ws.send_text(
                                json.dumps(
                                    {
                                        "type": "webrtc_ice",
                                        "candidate": msg.get("candidate"),
                                    }
                                )
                            )
                    else:
                        # Broadcast ICE to all viewers
                        for v_ws in room["viewers"].values():
                            try:
                                await v_ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "webrtc_ice",
                                            "candidate": msg.get("candidate"),
                                        }
                                    )
                                )
                            except Exception:
                                pass

            elif role == "viewer":
                # Viewers send answers and ICE candidates back to presenter
                if msg_type in ("webrtc_answer", "webrtc_ice"):
                    if room["presenter_ws"]:
                        # Tag with viewer identity so presenter can route
                        forwarded = {**msg, "from_viewer": viewer_key}
                        await room["presenter_ws"].send_text(json.dumps(forwarded))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        audit_logger.error(f"🎬 [Screen Share] Error in room {room_id}: {e}")
    finally:
        # ── Cleanup ──
        if role == "presenter":
            room["presenter_ws"] = None
            # Notify all viewers that presenter left
            for v_ws in list(room["viewers"].values()):
                try:
                    await v_ws.send_text(
                        json.dumps({"type": "presenter_left"})
                    )
                    await v_ws.close()
                except Exception:
                    pass
            # Remove the room
            _rooms.pop(room_id, None)
            audit_logger.info(f"🎬 [Screen Share] Room {room_id} closed (presenter left)")
        else:
            room["viewers"].pop(viewer_key, None)
            audit_logger.info(
                f"🎬 [Screen Share] Viewer '{display_name}' left room {room_id}"
            )
