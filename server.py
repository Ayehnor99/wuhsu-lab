import os
from pathlib import Path
import sys
import json
import secrets
import logging
import asyncio
import uuid
import re
import time
import shutil
import uvicorn
from datetime import datetime
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from wuhsu_agent import WuhsuService
from wuhsu_common import llm
from langchain_core.messages import HumanMessage, SystemMessage
from rag_service import RAGService
from fastapi import BackgroundTasks
from youtube_agent import YouTubeAgent
import yt_downloader

# ─── Detect Platform ───
IS_WINDOWS = sys.platform == "win32"

# ═══════════════════════════════════════
# 0. Security: Session Token & Audit Log
# ═══════════════════════════════════════

# Generate a cryptographically secure token on every server start
SESSION_TOKEN = secrets.token_urlsafe(32)

# Configure audit logger → .wuhsu_audit.log (hidden file)
_base_dir = os.path.dirname(os.path.abspath(__file__))
_audit_path = os.path.join(_base_dir, ".wuhsu_audit.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(_audit_path), logging.StreamHandler()]
)
audit_logger = logging.getLogger("wuhsu.audit")

app = FastAPI(title="WUHSU LAB Gateway")

# Jinja2 template engine — serves index.html from the project root
templates = Jinja2Templates(directory=_base_dir)

# Directory for secure avatars
AVATAR_DIR = os.path.join(_base_dir, "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

# Mount directory to serve images to the React UI
app.mount("/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")

# Directory for frontend assets
STATIC_DIR = os.path.join(_base_dir, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB Limit

# ═══════════════════════════════════════
# 0.5 WebSocket Connection Manager
# ═══════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()


# ═══════════════════════════════════════
# 1. Serve the UI (with token injection)
# ═══════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Serve the main WUHSU LAB HTML interface with the session token injected."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "session_token": SESSION_TOKEN},
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/debug")
async def get_debug():
    return {"status": "ok", "routes": [route.path for route in app.routes]}


# ═══════════════════════════════════════
# 1.5  Wuhsu AI Chat Endpoint
# ═══════════════════════════════════════
class ChatRequest(BaseModel):
    query: str
    session_id: str = ""
    terminal_context: str = ""

class DownloadRequest(BaseModel):
    url: str


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Send a user query to WuhsuService and return structured JSON."""
    # Default session_id if not provided
    session_id = req.session_id or str(uuid.uuid4())
    try:
        result = await WuhsuService.process_query(
            session_id=session_id,
            query=req.query,
            terminal_context=req.terminal_context,
        )
        return {"status": "ok", **result}
    except ValueError as ve:
        return {"status": "error", "text": str(ve)}
    except Exception as e:
        return {"status": "error", "text": str(e)}

class CommandIntent(BaseModel):
    intent: str

@app.post("/api/generate-command")
async def generate_command(req: CommandIntent):
    """Translate natural language intent to a raw bash command."""
    try:
        prompt = (
            "You are a bash command generator. Translate the following intent into a single raw bash command. "
            "Return ONLY the command in a JSON object with key 'command'. No markdown, no explanation.\n\n"
            f"Intent: {req.intent}"
        )
        
        # Use the shared LLM (configured for JSON)
        messages = [
            SystemMessage(content="You are a bash command generator. Output valid JSON only."),
            HumanMessage(content=prompt)
        ]
        
        response = await llm.ainvoke(messages)
        content = response.content
        
        # Parse JSON (handle potential markdown backticks)
        if isinstance(content, str):
            # Clean markdown formatting if present
            clean_content = content.replace("```json", "").replace("```", "").strip()
            
            # If still has some text before/after JSON, try regex extraction
            match = re.search(r"({.*})", clean_content, re.DOTALL)
            if match:
                clean_content = match.group(1)
            
            try:
                data = json.loads(clean_content)
                command = data.get("command", "")
            except json.JSONDecodeError:
                # Fallback: try to just use the string if it's not JSON
                command = content.strip()
        elif isinstance(content, dict):
             command = content.get("command", "")
        else:
             command = str(content)
             
        print(f"DEBUG: Generated Command for intent '{req.intent}': {repr(command)}", flush=True)
        return {"command": command}
        
    except Exception as e:
        return {"command": f"# Error generating command: {str(e)}"}


@app.post("/api/upload-avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """Secure image upload endpoint preventing RCE and XSS."""
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 5MB.")
    
    try:
        # 1. Verify Magic Bytes (Pillow throws error if not a real image)
        image = Image.open(BytesIO(contents))
        image.verify()
        
        # 2. Re-open to strip malicious EXIF/metadata payloads
        image = Image.open(BytesIO(contents))
        
        # 3. Drop alpha channels if converting to JPEG to neuter certain exploits
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
            
        # 4. Randomized naming prevents Path Traversal attacks (e.g. ../../)
        safe_filename = f"{uuid.uuid4().hex}.jpg"
        save_path = os.path.join(AVATAR_DIR, safe_filename)
        
        # 5. Re-encode and save
        image.save(save_path, format="JPEG", quality=85)
        
        avatar_url = f"/avatars/{safe_filename}"
        audit_logger.info("🛡️ [Security] Successfully sanitized and saved avatar: %s", safe_filename)
        
        return {"status": "success", "avatar_url": avatar_url}
        
    except UnidentifiedImageError:
        raise HTTPException(status_code=415, detail="Invalid image file format.")
    except Exception as e:
        audit_logger.error("Avatar upload error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error.")


# ═══════════════════════════════════════
# 1.55  RAG Document Upload Endpoint
# ═══════════════════════════════════════
# Allowed extensions based on the article's recommendations
ALLOWED_RAG_EXTENSIONS = {'.txt', '.pdf', '.md', '.log', '.csv'}

@app.post("/api/upload-rag")
async def upload_rag_document(file: UploadFile = File(...)):
    """Secure endpoint to upload personal notes/PDFs for the Second Brain."""
    
    # 1. Strict File Extension Filtering
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_RAG_EXTENSIONS:
        audit_logger.warning(f"Blocked RAG upload: Unsupported extension {file_ext}")
        return {"status": "error", "message": f"Unsupported file. Allowed formats: {', '.join(ALLOWED_RAG_EXTENSIONS)}"}
        
    file_location = os.path.join(_base_dir, f"temp_rag_{uuid.uuid4().hex}{file_ext}")
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)

        # 2. Process via the new Batch/Memory-managed service
        chunks = RAGService.ingest_document(file_location, file.filename)

        os.remove(file_location)
        return {
            "status": "success",
            "message": f"Successfully processed {chunks} data chunks into the Wuhsu Matrix.",
        }
    except Exception as e:
        audit_logger.error("RAG upload error: %s", e)
        # Ensure temp file is cleaned up even on failure
        if os.path.exists(file_location):
            os.remove(file_location)
        return {"status": "error", "message": str(e)}

# ─── YouTube Intelligence API ───
@app.get("/api/search-youtube")
async def api_search_youtube(q: str = Query(...)):
    """Direct search for the YouTube Intel Agent."""
    agent = YouTubeAgent()
    results = agent.search(q)
    return results

async def process_video_download(embed_url: str):
    """Converts embed URL to watch URL, downloads it securely, and notifies the user."""
    try:
        # Convert https://www.youtube.com/embed/VIDEO_ID?autoplay=1 to a standard watch URL
        watch_url = embed_url
        match = re.search(r"embed/([^?]+)", embed_url)
        if match:
            video_id = match.group(1)
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            
        audit_logger.info(f"📥[Downloader] Starting background download for: {watch_url}")
        
        # Define an explicit path inside the project folder so it doesn't get lost in /root/
        base_dir = os.path.dirname(os.path.abspath(__file__))
        save_path = Path(base_dir) / "downloads" / "youtube"
        save_path.mkdir(parents=True, exist_ok=True)
        
        # We force 'best' format which is pre-merged, removing complex FFmpeg dependencies
        safe_opts = {
            "format": "best",
            "postprocessors":[] 
        }
        
        # Run the synchronous yt-dlp download in a separate thread
        import yt_downloader
        await asyncio.to_thread(
            yt_downloader.download, 
            watch_url, 
            output_dir=save_path, 
            extra_opts=safe_opts
        )
        
        # Send a success notification to the Wuhsu Chat UI and force the UI to switch to the Chat Tab
        success_msg = json.dumps({
            "type": "chat_reply",
            "text": f"✅ **[System]** Video downloaded successfully!\nSaved to: `{save_path}`\n\n```json_ui_trigger\n{{\"action\": \"UI_UPDATE\", \"panel\": \"CHAT\"}}\n```"
        })
        await manager.broadcast(success_msg)
        
    except Exception as e:
        audit_logger.error(f"❌ [Downloader] Failed: {e}")
        error_msg = json.dumps({
            "type": "chat_reply",
            "text": f"❌ **[System]** Video download failed. Error: `{str(e)}`\n\n```json_ui_trigger\n{{\"action\": \"UI_UPDATE\", \"panel\": \"CHAT\"}}\n```"
        })
        await manager.broadcast(error_msg)

@app.post("/api/download-video")
async def api_download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    """Trigger the background downloader."""
    if not req.url:
        return {"status": "error", "message": "No URL provided."}
    background_tasks.add_task(process_video_download, req.url)
    return {"status": "success", "message": "Download initiated in the background."}


# ═══════════════════════════════════════
# 1.6 Chat WebSocket (Proactive Notifications)
# ═══════════════════════════════════════
@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket, token: str = Query(...)):
    audit_logger.info(f"🔄 WebSocket connection attempt on /ws/chat from {websocket.client.host}")
    if token != SESSION_TOKEN:
        audit_logger.warning(f"❌ WS Token Rejected. Expected: {SESSION_TOKEN}, Got: {token}")
        await websocket.close(code=1008)
        return
        
    # manager.connect(websocket) already calls await websocket.accept()
    await manager.connect(websocket)
    audit_logger.info(f"✅ WS Connection Accepted from {websocket.client.host}")
    try:
        while True:
            # We now expect JSON from the frontend: {"query": "...", "term_id": "..."}
            payload_str = await websocket.receive_text()
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                # Fallback for older non-JSON auto_help messages or keep-alives
                continue
                
            payload_message = payload.get("query", "")
            payload_session_id = payload.get("session_id", str(uuid.uuid4()))
            active_term_id = payload.get("term_id", "default")
            
            # Map the terminal to the current session so proactive help is context-aware
            terminal_to_session_map[active_term_id] = payload_session_id
            
            audit_logger.info(f"Chat Query: {payload_message} (Session: {payload_session_id}, Term: {active_term_id})")
            
            # Fetch the context for the terminal the user is currently looking at
            current_context = global_terminal_contexts.get(active_term_id)
            
            # Smart Fallback: If specific term_id is empty/missing, take the first available one
            if (not current_context or current_context == "") and global_terminal_contexts:
                # Get the most recently used terminal context
                active_term_id = list(global_terminal_contexts.keys())[-1]
                current_context = global_terminal_contexts[active_term_id]
                audit_logger.info(f"Retrieved fallback context from terminal: {active_term_id}")
            
            if not current_context:
                current_context = "No active terminal output detected."
            
            try:
                # 1. Send an initial message to clear the "thinking" dots in the UI
                await manager.broadcast(json.dumps({"type": "stream_start"}))
                
                # 2. WuhsuService accepts terminal_context
                # Note: Now using a generator to stream intermediate UI triggers
                async for update in WuhsuService.process_query(
                    session_id=payload_session_id,
                    query=payload_message,
                    terminal_context=current_context
                ):
                    # 3. Stream or send the text response
                    if update.get("text"):
                        await manager.broadcast(json.dumps({
                            "type": "chat_reply",
                            "text": update.get("text", "")
                        }))
                    
                    # 4. If there's a UI trigger in the final chunk, send it
                    if update.get("final"):
                        if update.get("ui_trigger") and update.get("route") not in ["YOUTUBE_AGENT", "WEBCRAWLER"]:
                            ui_payload = json.dumps({
                                "action": "UI_UPDATE",
                                "panel": update.get("route", "CHAT"),
                                "animation": update.get("ui_trigger", "")
                            })
                            await manager.broadcast(json.dumps({
                                "type": "chat_reply",
                                "text": f"```json_ui_trigger\n{ui_payload}\n```"
                            }))

                    
            except Exception as e:
                await manager.broadcast(json.dumps({
                    "type": "chat_reply",
                    "text": f"`[Error] LLM Exception: {str(e)}`"
                }))
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ═══════════════════════════════════════
# 2. Authenticated WebSocket Terminal
# ═══════════════════════════════════════

from typing import Dict, List, Optional
global_terminal_contexts: Dict[str, str] = {}
terminal_to_session_map = {} # Track which session is active on which terminal

async def _validate_token(websocket: WebSocket) -> bool:
    """Check the ?token= query parameter against SESSION_TOKEN.
    Returns True if valid, False (and closes ws) if rejected."""
    token = websocket.query_params.get("token")
    if token != SESSION_TOKEN:
        audit_logger.warning("REJECTED WebSocket — invalid token from %s (Expected: %s, Got: %s)", 
                             websocket.client.host, SESSION_TOKEN, token)
        await websocket.close(code=1008)  # Policy Violation
        return False
    return True


if IS_WINDOWS:
    # ──────────────────────────────────
    # WINDOWS: Use winpty for PTY
    # ──────────────────────────────────
    from winpty import PtyProcess  # type: ignore

    @app.websocket("/ws/terminal")
    async def terminal_socket(websocket: WebSocket):
        await websocket.accept()

        # ── Token gate ──
        if not await _validate_token(websocket):
            return

        audit_logger.info("SESSION START (Windows/winpty) from %s", websocket.client.host)

        # Spawn an interactive PowerShell via winpty
        proc = PtyProcess.spawn("powershell.exe")

        async def read_from_pty():
            """Reads output from the shell and sends it to xterm.js."""
            loop = asyncio.get_event_loop()
            while proc.isalive():
                try:
                    data = await loop.run_in_executor(None, proc.read, 4096)
                    if data:
                        await websocket.send_text(data)
                except EOFError:
                    break
                except Exception:
                    await asyncio.sleep(0.01)

        pty_task = asyncio.create_task(read_from_pty())

        # Buffer for line-level audit logging
        input_buffer = ""

        try:
            while True:
                client_data = await websocket.receive_text()

                # Handle JSON control messages (resize)
                try:
                    msg = json.loads(client_data)
                    if isinstance(msg, dict) and msg.get("type") == "resize":
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)
                        proc.setwinsize(rows, cols)
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass

                # ── Hardened Audit Logging ──
                # Accumulate keystrokes until ENTER (\r or \n)
                input_buffer += client_data
                if "\r" in input_buffer or "\n" in input_buffer:
                    clean_line = input_buffer.strip().replace("\r", "").replace("\n", "")
                    
                    # Simple Redaction: If the line looks like it might be a password
                    # or follows a known sudo/login context, we suppress it.
                    # Note: This is an extra layer of defense.
                    is_sensitive = any(kw in clean_line.lower() for kw in ["password", "secret", "key"]) or len(clean_line) > 30
                    
                    if not is_sensitive and clean_line:
                        audit_logger.info("CMD: %s", clean_line)
                    elif is_sensitive:
                        audit_logger.info("CMD: [REDACTED SENSITIVE INPUT]")
                    
                    input_buffer = ""

                proc.write(client_data)
        except WebSocketDisconnect:
            audit_logger.info("SESSION END (disconnect)")
        except Exception as e:
            audit_logger.error("SESSION ERROR: %s", e)
        finally:
            pty_task.cancel()
            try:
                proc.close(force=True)
            except Exception:
                pass

else:
    # ──────────────────────────────────
    # LINUX / KALI: Use native pty.fork()
    # ──────────────────────────────────
    import pty
    import fcntl
    import struct
    import termios
    import signal

    @app.websocket("/ws/terminal")
    async def terminal_socket(websocket: WebSocket, token: str = Query(...), term_id: str = Query("default")):
        if token != SESSION_TOKEN:
            audit_logger.warning("REJECTED WebSocket — invalid token from %s", websocket.client.host)
            await websocket.close(code=1008)
            return

        await websocket.accept()
        audit_logger.info("SESSION START (Linux/pty.fork) from %s for term_id: %s", websocket.client.host, term_id)

        # ─── THE BULLETPROOF PTY SPAWN ───
        # pty.fork() handles setsid() and ioctl(TIOCSCTTY) automatically at the C-level
        pid, fd = pty.fork()

        if pid == 0:
            # --- CHILD PROCESS ---
            # Set up a clean environment for the terminal
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["LANG"] = "en_US.UTF-8"
            
            # Execute Bash directly. '-l' makes it a login shell so colors and .bashrc load!
            # This completely replaces the Python child process with Bash.
            os.execvpe("/bin/bash", ["bash", "-l"], env)
        else:
            # --- PARENT PROCESS (FastAPI) ---
            master_fd = fd
            
            # Make the master_fd non-blocking so the async loop doesn't freeze
            fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            # Initialize the context buffer
            global_terminal_contexts[term_id] = ""

            # Watcher State
            last_error_time = 0
            last_prompt_check_time = 0
            error_debounce_seconds = 15.0 # Increased debounce
            is_command_running = False     # State machine for proactive help
            
            error_patterns =[r"command not found", r"Permission denied", r"Syntax error", r"unrecognized option"]
            combined_error_regex = re.compile("|".join(error_patterns), re.IGNORECASE)
            PROMPT_REGEX = re.compile(r"(?m)^(?:.*[\$#>]|.*\(.*?\).*[\$#>])$")

            async def read_from_pty():
                nonlocal last_error_time, last_prompt_check_time, is_command_running
                while True:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break # Bash exited
                        
                        text_data = data.decode("utf-8", errors="replace")
                        # Safely update context buffer
                        current_val = global_terminal_contexts.get(term_id, "")
                        global_terminal_contexts[term_id] = (current_val + text_data)[-4000:]
                        
                        try:
                            await websocket.send_text(text_data)
                        except Exception:
                            break
                        
                        # --- Proactive Watcher ---
                        current_time = time.time()
                        
                        # 1. Error Detection
                        if (current_time - last_error_time) > error_debounce_seconds:
                            if combined_error_regex.search(text_data):
                                last_error_time = current_time
                                snippet = text_data[-300:].replace("\n", " ").strip()
                                asyncio.create_task(trigger_autonomous_help(snippet, "error"))

                        # 2. Prompt Detection (Only fire if a command was recently started)
                        if is_command_running and (current_time - last_prompt_check_time) > 1.5:
                            recent_text = global_terminal_contexts.get(term_id, "")[-100:]
                            if PROMPT_REGEX.search(recent_text):
                                last_prompt_check_time = current_time
                                is_command_running = False # Reset state until next command
                                asyncio.create_task(trigger_autonomous_help(global_terminal_contexts[term_id][-1000:], "proactive"))
                                
                    except BlockingIOError:
                        await asyncio.sleep(0.01)
                    except OSError:
                        break # PTY Closed

            async def trigger_autonomous_help(terminal_context: str, trigger_type: str):
                """Ask Wuhsu for help and push to chat WebSocket."""
                try:
                    session_id = terminal_to_session_map.get(term_id, "system_auto_trigger")
                    
                    if trigger_type == "error":
                        query = f"[SYSTEM AUTO-TRIGGER: ERROR] User received an error. Analyze: {terminal_context[-300:]}. Provide 1-sentence fix."
                    else:
                        query = "[SYSTEM AUTO-TRIGGER: PROACTIVE] Command finished. Analyze the terminal output. If everything is fine, say nothing. If there is a lesson or a fix, provide it briefly."
                    
                    result = await WuhsuService.process_query(
                        session_id=session_id,
                        query=query,
                        terminal_context=terminal_context
                    )
                    
                    response_text = result.get("text", "").strip()
                    # Don't send empty, redundant, or silent NO_RESPONSE messages
                    if not response_text or response_text.upper() == "NO_RESPONSE" or "[SYSTEM" in response_text:
                        return

                    await manager.broadcast(json.dumps({
                        "type": "auto_help",
                        "text": f"🛡️ [Wuhsu Guardian]\n{response_text}",
                        "from": "wuhsu"
                    }))

                except Exception as e:
                    audit_logger.error(f"Auto-help failed: {e}")

            pty_task = asyncio.create_task(read_from_pty())
            input_buffer = ""

            try:
                while True:
                    client_data = await websocket.receive_text()

                    # Handle JSON resizing
                    try:
                        msg = json.loads(client_data)
                        if isinstance(msg, dict) and msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except (json.JSONDecodeError, ValueError):
                        pass

                    # Write keystrokes securely to the master_fd
                    try:
                        # If user hits Enter, we mark a command as running for proactive analysis
                        # If user hits Enter with some command text, mark as running
                        if ("\r" in client_data or "\n" in client_data) and len(client_data.strip()) > 0:
                            is_command_running = True
                            
                        os.write(master_fd, client_data.encode("utf-8"))
                    except OSError:
                        break # Terminal closed

            except WebSocketDisconnect:
                audit_logger.info("SESSION END (disconnect)")
            finally:
                pty_task.cancel()
                try:
                    os.close(master_fd)
                except OSError:
                    pass
                
                # Securely terminate the child bash process
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                
                if term_id in global_terminal_contexts:
                    del global_terminal_contexts[term_id]


# ═══════════════════════════════════════
# 3. Launch the Gateway (localhost only)
# ═══════════════════════════════════════
if __name__ == "__main__":
    print("=" * 56)
    print("  WUHSU LAB — Agentic Cybersecurity Gateway (Hardened)")
    print(f"  Platform: {'Windows' if IS_WINDOWS else 'Linux/Kali'}")
    print(f"  Bind:     127.0.0.1:8000 (localhost only)")
    print(f"  Token:    {SESSION_TOKEN}")
    print(f"  Routes:   {[route.path for route in app.routes]}")
    print("=" * 56)
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
