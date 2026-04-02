"""
WUHSU LAB — Agentic Cybersecurity Learning Environment
PySide6 Desktop Launcher (Chunk 1 — Auto-Server)

This module:
1. Auto-starts the FastAPI WebSocket gateway (server.py) as a subprocess
2. Waits for the server to become ready
3. Creates the main application window with QWebEngineView
4. Loads the UI from the running server (token injection happens via Jinja2)
5. Cleans up the server subprocess on exit
"""

import sys
import os
import atexit
import subprocess
import time
import urllib.request

# ─── Fix QWebEngineView white-screen on Linux VMs / Kali ───
# Must be set BEFORE importing any Qt modules
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--ignore-gpu-blocklist "
    "--enable-gpu-rasterization "
    "--enable-features=NetworkServiceInProcess "
    "--no-sandbox"
)

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtGui import QIcon

# ─── Constants ───
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVER_SCRIPT = os.path.join(_BASE_DIR, "server.py")
_SERVER_URL = "http://127.0.0.1:8000"
_MAX_WAIT_SECONDS = 10  # Max time to wait for server readiness

# Global handle so atexit can clean it up
_server_process = None


def _is_server_running() -> bool:
    """Check if the FastAPI server is responding on port 8000."""
    try:
        urllib.request.urlopen(_SERVER_URL, timeout=1)
        return True
    except Exception:
        return False


def start_server():
    """Launch server.py as a background subprocess and wait until it's ready.

    If the server is already running (e.g. from a manual start), this
    function simply returns without spawning a duplicate.
    """
    global _server_process

    # Already running? Just use it.
    if _is_server_running():
        print("[WUHSU Launcher] Server already running — connecting.")
        return

    print("[WUHSU Launcher] Starting server.py …")

    # Use the same Python interpreter that is running main.py
    python_exe = sys.executable
    # Open a log file for the server process
    server_log = open(os.path.join(_BASE_DIR, "server_output.txt"), "w")

    _server_process = subprocess.Popen(
        [python_exe, _SERVER_SCRIPT],
        cwd=_BASE_DIR,
        stdout=server_log,
        stderr=server_log,
        # Hide the console window on Windows
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    # Register cleanup so the server dies when the app closes
    atexit.register(_stop_server)

    # Poll until the server is ready (or timeout)
    deadline = time.time() + _MAX_WAIT_SECONDS
    while time.time() < deadline:
        if _is_server_running():
            print("[WUHSU Launcher] Server is ready.")
            return
        # Check if process crashed
        if _server_process.poll() is not None:
            print("[WUHSU Launcher] ERROR — server.py exited unexpectedly.")
            sys.exit(1)
        time.sleep(0.3)

    print("[WUHSU Launcher] ERROR — server did not start within "
          f"{_MAX_WAIT_SECONDS}s.")
    _stop_server()
    sys.exit(1)


def _stop_server():
    """Terminate the server subprocess if we started it."""
    global _server_process
    if _server_process and _server_process.poll() is None:
        print("[WUHSU Launcher] Shutting down server …")
        _server_process.terminate()
        try:
            _server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None


class WuhsuDesktopApp(QMainWindow):
    """Main application window for WUHSU LAB.

    Embeds a full-screen QWebEngineView that renders the React/Three.js/xterm.js
    interface defined in index.html. All visual UI lives in the web layer;
    this class only manages the native window chrome and lifecycle.
    """

    def __init__(self):
        super().__init__()

        # --- 1. Window Configuration ---
        self.setWindowTitle("WUHSU LAB - Agentic Cybersecurity Environment")
        self.resize(1400, 900)          # Default startup size
        self.setMinimumSize(1024, 768)  # Prevent shrinking too small

        # (Optional) Frameless mode for full hacker aesthetic:
        # self.setWindowFlag(Qt.FramelessWindowHint)

        # --- 2. Main Layout (zero margins → HTML fills entire window) ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- 3. Initialize the Chromium WebEngine ---
        self.browser = QWebEngineView()
        
        # Auto-grant WebRTC Camera/Microphone permissions
        self.browser.page().featurePermissionRequested.connect(self.on_feature_permission_requested)

        # --- 4. Load the UI entry point (FastAPI Server) ---
        server_url = QUrl(_SERVER_URL)
        self.browser.setUrl(server_url)

        # --- 5. Finalize Layout ---
        layout.addWidget(self.browser)

    def on_feature_permission_requested(self, security_origin: QUrl, feature: QWebEnginePage.Feature):
        """Auto-grant WebRTC media permissions (camera/mic)."""
        if feature in (
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture,
        ):
            self.browser.page().setFeaturePermission(
                security_origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            )
        else:
            self.browser.page().setFeaturePermission(
                security_origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
            )

    def closeEvent(self, event):
        """Ensure the server subprocess is cleaned up on window close."""
        _stop_server()
        event.accept()


if __name__ == "__main__":
    # 1. Start the backend server (or connect to existing one)
    start_server()

    # 2. Create the Qt Application instance
    app = QApplication(sys.argv)

    # Force Fusion style for consistent dark-mode native dialogs
    app.setStyle("Fusion")

    # 3. Instantiate and show the main window
    window = WuhsuDesktopApp()
    window.show()

    # 4. Start the Qt event loop
    sys.exit(app.exec())
