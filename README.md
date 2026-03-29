# 🥋 WUHSU LAB
**The Agentic Cybersecurity Learning Environment**

![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![React](https://img.shields.io/badge/react-%2320232a.svg?style=for-the-badge&logo=react&logoColor=%2361DAFB)
![Kali](https://img.shields.io/badge/Kali_Linux-557C94?style=for-the-badge&logo=kali-linux&logoColor=white)

WUHSU LAB is a next-generation, AI-powered penetration testing sandbox. It combines a fully-armed Kali Linux Docker container with a 5-Agent LLM Swarm (powered by Ollama Cloud) that actively monitors your terminal, mentors you chunk-by-chunk, and visualizes your attacks in real-time.

## ✨ Core Features
*   **💻 Agentic Terminal Omniscience:** The Wuhsu Master AI watches your bash shell. If an `nmap` scan finishes or a command fails, the AI autonomously jumps into the chat to explain the output and suggest the next move.
*   **🧠 Local Second Brain (RAG):** Upload your OSCP notes or hacking PDFs. The AI vectorizes them locally (ChromaDB) and cites your own textbooks when answering your questions.
*   **🌐 Firecrawl OSINT Engine:** A dedicated WebCrawler agent that bypasses anti-bot protections to scrape real-time CVEs and Exploit-DB intel.
*   **📺 Tactical Sandbox:** Automatically finds and plays relevant YouTube tutorials based on your terminal struggles, or renders 3D networking animations.
*   **🛡️ Air-Gapped Security:** Runs entirely in your browser via a hardened Kali Linux Docker container. Hack safely without compromising your host machine.

## 🚀 Quick Start

### 1. Prerequisites
*   [Docker](https://docs.docker.com/get-docker/) & Docker Compose
*   An API Key from [Firecrawl](https://firecrawl.dev) (Free)
*   An Ollama Cloud endpoint (e.g., Qwen 3.5 or MiniMax)

### 2. Installation
Clone the repository and navigate into the directory:
```bash
git clone https://github.com/YOUR_USERNAME/wuhsu-lab.git
cd wuhsu-lab
```

### 3. Configuration
Copy the environment template and add your API keys:
```bash
cp .env.example .env
# Edit .env with your favorite editor (nano, vim)
```

### 4. Enter the Dojo
Launch the containerized environment:
```bash
docker-compose up --build -d
```
Open your browser (or install as a Chrome PWA for the native app experience) and navigate to:
👉 http://localhost:8000

## 🏗️ Architecture
*   **Frontend**: React, xterm.js, Three.js (Cupertino Glassmorphism UI)
*   **Backend**: Python, FastAPI, WebSockets, pty.fork()
*   **AI Swarm**: LangGraph, LangChain, Ollama (qwen3.5:397b-cloud / minimax-m2.7:cloud)
*   **Database**: aiosqlite (History/XP), ChromaDB (RAG Vectors)

## 🤝 Contributing
Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

## 📜 License
MIT
