"""
wuhsu_common.py — Shared resources for the Wuhsu Swarm
======================================================
This file houses the unified LLM instance and state definitions to prevent 
circular imports between the main Wuhsu Agent and its specialized nodes.
"""

import os
import logging
from typing import List, Any, Optional, TypedDict
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage
from dotenv import load_dotenv
from pathlib import Path

# ─── Load Environment ─────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".venv" / ".env")
load_dotenv(_BASE_DIR / ".env")

# ─── Shared State ────────────────────────────────────────────────────────────
class WuhsuState(TypedDict):
    messages: List[BaseMessage]

# ─── Unified LLM Engine ───────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY") or os.getenv("OLLAMA_API_KEY0", "")

logging.info(f"🧠 Shared Engine: Initializing ChatOllama with minimax-m2.7:cloud at {OLLAMA_BASE_URL}")

# Build auth headers if API key is present
_ollama_headers = {}
if OLLAMA_API_KEY:
    _ollama_headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

llm = ChatOllama(
    model="minimax-m2.7:cloud",
    base_url=OLLAMA_BASE_URL,
    temperature=0.2, # Low temperature for precise infosec reasoning
    format="json",   # CRITICAL: Forces MiniMax to strictly output valid JSON for Pydantic
    max_retries=3,
    client_kwargs={"headers": _ollama_headers} if _ollama_headers else {},
)

# ─── OSINT Utilities ─────────────────────────────────────────────────────────
def quick_ddg_search(query: str, max_results: int = 5) -> str:
    """A rapid search fallback for the Wuhsu Swarm."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return f"No results found for '{query}'."
            
            output = [f"Search results for: {query}"]
            for i, r in enumerate(results):
                output.append(f"[{i+1}] {r.get('title')}\nSource: {r.get('href')}\nSnippet: {r.get('body')[:200]}...")
            return "\n\n".join(output)
    except Exception as e:
        logging.error(f"DDG Search failed: {e}")
        return f"Search error for '{query}': {str(e)}"
