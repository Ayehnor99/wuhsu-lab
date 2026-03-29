"""
WUHSU LAB Terminal — Pure Python CLI Client
=======================================
This terminal-native version of WUHSU LAB allows for a streamlined experience
without the overhead of a web browser or GUI.

Usage:
  python3 wuhsu_terminal.py
"""

import asyncio
import sys
import os
import json
import logging
import uuid
from wuhsu_agent import WuhsuService
from wuhsu_common import WuhsuState

# Disable excessive logging for a clean CLI experience
logging.getLogger("langchain").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

# ANSI Colors for a "hacker" terminal aesthetic
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    PURPLE = "\033[95m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

async def main_loop():
    session_id = str(uuid.uuid4())
    os.system("clear" if os.name == "posix" else "cls")
    
    print(f"{Colors.GREEN}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.GREEN}{Colors.BOLD}║             WUHSU LAB — AGENTIC TERMINAL v3.5                    ║{Colors.END}")
    print(f"{Colors.GREEN}{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
    print(f"{Colors.CYAN}Mentor Mode Active. Unified AI Engine (Ollama Cloud) Connected.{Colors.END}")
    print(f"{Colors.YELLOW}Type 'exit' or 'quit' to terminate session.\n{Colors.END}")

    while True:
        try:
            # Elegant prompt
            user_input = input(f"{Colors.BOLD}┌──({Colors.GREEN}wuhsu-swarm{Colors.BOLD})─[{Colors.YELLOW}~/kali{Colors.BOLD}]\n└─${Colors.END} ").strip()
            
            if user_input.lower() in ["exit", "quit"]:
                print(f"\n{Colors.PURPLE}[Wuhsu] Session terminated. Happy hacking. 🦾{Colors.END}")
                break
            
            if not user_input:
                continue

            print(f"\n{Colors.CYAN}Thinking...{Colors.END}", end="\r")
            
            # Simple terminal context simulation (could be expanded to read actual bash history)
            terminal_context = "User is in a pure Python CLI environment."
            
            response = await WuhsuService.process_query(session_id, user_input, terminal_context)
            
            # Clear "Thinking..." line
            print(" " * 20, end="\r")

            # Route indicators
            route = response.get("route", "CHAT")
            if route == "WEBCRAWLER":
                print(f"{Colors.PURPLE}[AGENT: WEBCRAWLER]{Colors.END}")
            elif route == "YOUTUBE_AGENT":
                print(f"{Colors.PURPLE}[AGENT: YOUTUBE]{Colors.END}")

            # Print main response
            print(f"{Colors.GREEN}{response.get('text', '')}{Colors.END}")

            # Handle UI Triggers in CLI (as text fallbacks)
            ui_trigger = response.get("ui_trigger")
            if ui_trigger:
                if route == "YOUTUBE_AGENT":
                    print(f"\n{Colors.YELLOW}📺 [VIDEO RECOMMENDED]: {ui_trigger}{Colors.END}")
                    print(f"{Colors.CYAN}Search YouTube for the query above for the best visual guide.{Colors.END}")

            print("-" * 60 + "\n")

        except KeyboardInterrupt:
            print(f"\n\n{Colors.PURPLE}[Wuhsu] Emergency disconnect. 🦾{Colors.END}")
            break
        except Exception as e:
            print(f"\n{Colors.RED}[ERROR] Logic failure: {e}{Colors.END}")

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except EOFError:
        pass
