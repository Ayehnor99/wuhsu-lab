#!/bin/bash

# WUHSU LAB - Native Linux Installer
echo -e "\033[96m╔══════════════════════════════════════════════════════════════╗\033[0m"
echo -e "\033[96m║               🥋 WUHSU LAB NATIVE INSTALLER                 ║\033[0m"
echo -e "\033[96m╚══════════════════════════════════════════════════════════════╝\033[0m"

# 1. Define Paths
APP_DIR="$HOME/.wuhsu-lab"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo -e "\n[*] Preparing installation directories..."
mkdir -p "$APP_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$DESKTOP_DIR"

# 2. Copy Files to Application Directory
echo "[*] Copying files to $APP_DIR..."
rsync -a --exclude 'wuhsu-env' --exclude '.venv' --exclude '.git' --exclude '__pycache__' ./ "$APP_DIR/"

# 3. Create Virtual Environment
echo "[*] Setting up Python Virtual Environment..."
cd "$APP_DIR"
if ! python3 -m venv .venv; then
    echo -e "\033[91m❌ Error: Failed to create virtual environment.\033[0m"
    echo "Tip: On Kali Linux, you may need to install the venv package first:"
    echo -e "\033[93msudo apt update && sudo apt install -y python3-venv\033[0m"
    exit 1
fi
source .venv/bin/activate

# 4. Install Dependencies
echo "[*] Installing Python dependencies (this may take a minute)..."
echo "[*] Logs are being saved to $APP_DIR/install.log"
pip install --upgrade pip > "$APP_DIR/install.log" 2>&1
if ! pip install -r requirements.txt >> "$APP_DIR/install.log" 2>&1; then
    echo -e "\033[91m❌ Error: Failed to install Python dependencies. Check $APP_DIR/install.log for details.\033[0m"
    exit 1
fi

# Create required asset folders
mkdir -p "$APP_DIR/avatars"
mkdir -p "$APP_DIR/.wuhsu_vector_db"
mkdir -p "$APP_DIR/downloads/youtube"

# 5. Create the Smart Launcher Script
echo "[*] Creating the 'wuhsu' global command..."
cat << 'EOF' > "$BIN_DIR/wuhsu"
#!/bin/bash
# WUHSU LAB Smart Launcher
APP_DIR="$HOME/.wuhsu-lab"

echo "[*] Booting Wuhsu Master Gateway..."
cd "$APP_DIR"
source .venv/bin/activate

# Start the FastAPI server in the background and log output
uvicorn server:app --host 127.0.0.1 --port 8000 > "$APP_DIR/server_output.log" 2>&1 &
SERVER_PID=$!

# Wait 2 seconds for the server to bind to the port
sleep 2

# Launch the UI in Native App Mode
# Fallback to standard chrome/chromium depending on what the user has installed
if command -v chromium &> /dev/null; then
    chromium --app=http://127.0.0.1:8000
elif command -v google-chrome &> /dev/null; then
    google-chrome --app=http://127.0.0.1:8000
elif command -v brave-browser &> /dev/null; then
    brave-browser --app=http://127.0.0.1:8000
else
    echo "⚠️  No Chromium-based browser found. Opening in default browser."
    xdg-open http://127.0.0.1:8000
fi

# Once the browser window is closed, elegantly kill the backend server
echo "[*] Shutting down Wuhsu Master Gateway..."
kill $SERVER_PID
EOF

chmod +x "$BIN_DIR/wuhsu"

# 6. Create the Desktop Shortcut
echo "[*] Generating Application Menu Shortcut..."
cat << EOF > "$DESKTOP_DIR/wuhsu-lab.desktop"
[Desktop Entry]
Version=1.0
Name=WUHSU LAB
Comment=Agentic Cybersecurity Learning Environment
Exec=$BIN_DIR/wuhsu
Icon=$APP_DIR/avatars/ksm-logo.jpeg
Terminal=false
Type=Application
Categories=Education;Development;Security;
Keywords=cybersecurity;hacking;ai;kali;
EOF

# Make sure ~/.local/bin is in the user's PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "\n\033[93m⚠️  Warning: $HOME/.local/bin is not in your PATH.\033[0m"
    echo "Add this line to your ~/.zshrc or ~/.bashrc:"
    echo 'export PATH="$HOME/.local/bin:$PATH"'
fi

echo -e "\n\033[92m✅ Installation Complete!\033[0m"
echo -e "You can now launch the app by searching for \033[96m'WUHSU LAB'\033[0m in your application menu,"
echo -e "or by typing \033[96m'wuhsu'\033[0m in your terminal."
