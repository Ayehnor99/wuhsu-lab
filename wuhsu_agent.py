"""
WUHSU LAB — Agentic Cybersecurity Learning Environment
Chunk 4.1: Secure Wuhsu Master Supervisor Service (Powered by Qwen 3.5)

THREAT MODEL:
  • Data Exfiltration  → Local aiosqlite only, no cloud DBs
  • DoS / Rate Limits  → API key rotation + model fallback degradation
  • Prompt Injection    → Pydantic-enforced JSON output; LLM cannot execute commands
"""

import os
import json
import time
import logging
import asyncio
import re
import random
import aiosqlite
from typing import List, Dict, Any, Optional, TypedDict
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ==========================================
# 0.5 XP & PROGRESSION SYSTEM
# ==========================================
class XpAward(BaseModel):
    skill: str = Field(description="The name of the skill being awarded XP (e.g., 'Network Reconnaissance').")
    amount: int = Field(description="Amount of XP to award (typically 5-20).")
    reason: str = Field(description="Brief justification for the award.")

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from webcrawler_agent import webcrawler_node
from youtube_node import youtube_agent_node
from rag_service import RAGService

# Load .env from the .venv directory (project-specific location)
_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".venv" / ".env")
load_dotenv(_BASE_DIR / ".env")

# Import the shared LLM and State from wuhsu_common to prevent circular imports
from wuhsu_common import WuhsuState, llm as common_llm

# 1. THE FAST CONVERSATIONAL MODEL (Drops format="json" for instant streaming & beautiful markdown)
# We use the same base config as the shared engine but with different parameters
fast_chat_llm = ChatOllama(
    model="minimax-m2.7:cloud",
    base_url=common_llm.base_url,
    temperature=0.6,
    max_tokens=250,
    client_kwargs=common_llm.client_kwargs
)

# 2. THE ROUTING MODEL (Keeps JSON for strict backend routing)
router_llm = ChatOllama(
    model=common_llm.model,
    base_url=common_llm.base_url,
    temperature=0.2,
    format="json",
    client_kwargs=common_llm.client_kwargs
)

# Shared LLM reference (legacy support)
llm = common_llm

# ==========================================
# 2. THE HYPER-BREVITY MASTER PROMPT
# ==========================================
WUHSU_SYSTEM_PROMPT = """You are WUHSU MASTER, an elite Cybersecurity Mentor.
You have direct visibility into the user's [LIVE TERMINAL CONTEXT].

CRITICAL COMMUNICATION RULES (STRICTLY ENFORCED):
1. EXTREME BREVITY: You MUST limit your response to MAXIMUM 3 SHORT SENTENCES or a small markdown table. 
2. NO ESSAYS: Never output a wall of text. Humans cannot read long text in a chat window. Do not overwhelm the beginner.
3. CHUNK-BY-CHUNK: Teach ONE concept at a time. Wait for the user to respond or execute the command before continuing.
4. COMMAND HIGHLIGHTING: You MUST wrap EVERY bash command in single backticks (e.g., `nmap -sV`).

OUTPUT FORMAT:
**[Observation]** (1 short sentence acknowledging the terminal state).
**[Analysis]** (1-2 sentences OR a small markdown table explaining the concept).
**[Next Move]** (The exact next bash command they should run).
"""

# ==========================================
# 3. THREAT MITIGATION: STRUCTURED OUTPUT
# ==========================================
class WuhsuDecision(BaseModel):
    internal_thought: str = Field(
        description="Analyze the terminal context and user query. Does the user need a video tutorial? Is there an unknown error or CVE that requires a web search? Think step-by-step."
    )
    route: str = Field(
        description="Strict routing: Must be 'CHAT', 'WEBCRAWLER', 'YOUTUBE_AGENT', or 'MANAGER_AGENT'."
    )
    response: Any = Field(description="WuhsuMaster's conversational reply or search query parameters.")
    ui_trigger: Optional[str] = Field(
        default=None,
        description="If routing to 3D, put animation name. If YouTube or Web, put the search query. Otherwise null.",
    )
    xp_award: Optional[XpAward] = Field(
        default=None,
        description="Optional XP award if the user performed a successful action."
    )


# ==========================================
# 4. WUHSU SERVICE
# ==========================================
class WuhsuService:
    DB_PATH = str(_BASE_DIR / ".wuhsu_history.db")

    @classmethod
    async def init_db(cls):
        """Initializes local SQLite databases for Chat History AND User Skills."""
        async with aiosqlite.connect(cls.DB_PATH) as db:
            # 1. Chat History Table
            await db.execute(
                """CREATE TABLE IF NOT EXISTS chatbot_logs
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, query TEXT, response TEXT, status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
            )
            # 2. 🌟 NEW: User Skills Table (Persistent XP Tracking)
            await db.execute(
                """CREATE TABLE IF NOT EXISTS user_skills
                   (skill_name TEXT UNIQUE, xp INTEGER DEFAULT 0)"""
            )
            await db.commit()

    @classmethod
    async def add_xp(cls, skill_name: str, amount: int):
        """Adds XP to a specific skill, creating it if it doesn't exist."""
        try:
            async with aiosqlite.connect(cls.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO user_skills (skill_name, xp) 
                       VALUES (?, ?) 
                       ON CONFLICT(skill_name) DO UPDATE SET xp = xp + ?""",
                    (skill_name, amount, amount)
                )
                await db.commit()
        except Exception as e:
            logging.error(f"Failed to save XP to DB: {e}")

    @classmethod
    async def get_skills(cls) -> List[Dict[str, Any]]:
        """Retrieves all user skills and XP for the React Dashboard."""
        try:
            async with aiosqlite.connect(cls.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT skill_name, xp FROM user_skills ORDER BY xp DESC")
                rows = await cursor.fetchall()
                return [{"name": row["skill_name"], "xp": row["xp"]} for row in rows]
        except Exception as e:
            logging.error(f"Failed to fetch skills: {e}")
            return []

    @classmethod
    async def process_query(
        cls, session_id: str, query: str, terminal_context: str = ""
    ):
        """Main secure processing loop. Yields intermediate and final updates."""

        if not query or len(query.strip()) < 2:
            yield {"text": "Query rejected: Invalid length."}
            return

        try:
            await cls.init_db()
            history = await cls._get_conversation_history(session_id)

            # 1. Search the user's local vector DB (The Second Brain)
            try:
                rag_context = RAGService.search_knowledge_base(query)
            except Exception:
                rag_context = ""

            rag_injection = ""
            if rag_context:
                logging.info("📚 [RAG] Relevant notes found. Switching to NotebookLLM Explainer Mode.")
                rag_injection = f"""
==================================================[NOTEBOOK LLM MODE ACTIVATED]
The user has uploaded personal study documents. Here are the exact excerpts from their database:

{rag_context}

YOUR NEW DIRECTIVES FOR THIS RESPONSE:
1. DEEP-DIVE EXPLANATION: You must act as an elite, highly intelligent professor. Do not just repeat the text. Synthesize it, break it down, and explain the *underlying concepts* using analogies if necessary.
2. THE FEYNMAN TECHNIQUE: Explain the concepts so clearly that a beginner can understand them chunk-by-chunk.
3. STRICT CITATION: You MUST cite your sources. Whenever you state a fact from the text, append the citation like this: `[Source: uploaded document]`.
4. NO HALLUCINATIONS: If the uploaded text does not contain the answer, say "Your uploaded documents do not cover this, but based on my general knowledge..."
5. COMMAND HIGHLIGHTING: You MUST wrap EVERY bash or terminal command in SINGLE BACKTICKS (e.g., `nmap -sV`) or TRIPLE BACKTICKS. If you do not wrap commands in backticks, the user's interface will crash and hide the command.
==================================================
"""

            # Technical system prompt for the ROUTER
            router_system_prompt = (
                f"CURRENT DATE: {time.strftime('%Y-%m-%d')}\n"
                "You are the Wuhsu Routing Engine. Your task is to analyze the user query and the LIVE TERMINAL CONTEXT.\n"
                f"[LIVE TERMINAL CONTEXT]:\n{terminal_context}\n"
                "INSTRUCTIONS:\n"
                "1. Use 'internal_thought' to analyze the terminal output BEFORE deciding the route.\n"
                "2. Output a JSON object with 'internal_thought', 'route', 'response', 'ui_trigger', and 'xp_award'.\n"
                "\n"
                "AUTONOMOUS ROUTING RULES (BE PROACTIVE!):\n"
                "- WEBCRAWLER: Do NOT wait for the user to say 'search'. If the terminal shows an unfamiliar Error Code, a specific CVE, a new software version, or an exploit failure, AUTONOMOUSLY route to WEBCRAWLER. Set 'ui_trigger' to the search query. Also use this if the user asks for news, current events, latest CVEs, or asks to 'search', 'crawl', 'fetch', or 'look up' something on the internet/web.\n"
                "- YOUTUBE_AGENT: Do NOT wait for the user to ask for a video. If the terminal shows the user repeatedly failing to use a complex tool (e.g., Hashcat, Metasploit, Nmap), AUTONOMOUSLY route to YOUTUBE_AGENT to give them a tutorial. Set 'ui_trigger' to the tool name. Also use this for video or tutorial requests.\n"
                "- MANAGER_AGENT: If the user explicitly asks about their progress, XP, or dashboard stats.\n"
                "- CHAT: If you know the answer directly, or if the user is just conversing. ALWAYS provide the NEXT BASH COMMAND they should run.\n"
            )

            messages = [SystemMessage(content=router_system_prompt + rag_injection)]
            for h in history:
                messages.append(HumanMessage(content=h["query"]))
                messages.append(AIMessage(content=h["response"]))
            messages.append(HumanMessage(content=query))

            # ── DETERMINISTIC PRE-ROUTE ──
            query_lower = query.lower().strip()
            _yt_keywords = ["show me video", "show video", "find video", "play video",
                            "youtube", "watch video", "show me a tutorial", "find a tutorial",
                            "search youtube", "search video", "video on ", "videos on ",
                            "tutorial on ", "tutorials on "]
            
            # 🌟 THE FIX: Expanded Web/OSINT trigger keywords
            _web_keywords =[
                "search the web", "look up online", "osint", "crawl", "scrape",
                "fetch", "news", "what is going on", "what is happening",
                "latest", "today", "search online", "hackernoon", "cve"
            ]
            
            pre_route = None
            for kw in _yt_keywords:
                if kw in query_lower:
                    pre_route = "YOUTUBE_AGENT"
                    topic = query_lower.split(kw)[-1].strip() or query_lower
                    logging.info(f"🎯 [Pre-Route] Keyword match '{kw}' → YOUTUBE_AGENT (topic: {topic})")
                    break
            if not pre_route:
                for kw in _web_keywords:
                    if kw in query_lower:
                        pre_route = "WEBCRAWLER"
                        logging.info(f"🎯 [Pre-Route] Keyword match '{kw}' → WEBCRAWLER")
                        break

            # 2. Routing Decision
            final_route = "CHAT"
            ui_trigger = None
            xp_award = None
            final_response = ""

            if pre_route:
                final_route = pre_route
                ui_trigger = query
                final_response = f"Routing to {final_route}..."
            else:
                try:
                    structured_llm = router_llm.with_structured_output(WuhsuDecision)
                    decision = await structured_llm.ainvoke(messages)
                    final_route = decision.route or "CHAT"
                    ui_trigger = decision.ui_trigger
                    xp_award = decision.xp_award.model_dump() if decision.xp_award else None
                    final_response = decision.response or f"Routing to {final_route}..."
                except Exception as e:
                    logging.warning(f"⚠️ [WuhsuMaster] Router extraction failed: {e}")
                    final_route = "CHAT"

            # 3. Execution Logic
            if final_route == "YOUTUBE_AGENT":
                state_msgs = [HumanMessage(content=h["query"]) for h in history] + [HumanMessage(content=query)]
                last_chunk = None
                async for chunk in youtube_agent_node({"messages": state_msgs}):
                    msg_content = chunk["messages"][-1].content
                    # If this is an intermediate UI trigger (like "loading: true"), yield it immediately
                    if "json_ui_trigger" in msg_content and '"loading": true' in msg_content:
                        yield {"text": msg_content, "route": final_route, "is_partial": True}
                    last_chunk = chunk
                
                if last_chunk and "messages" in last_chunk:
                    final_response = last_chunk["messages"][-1].content

            elif final_route == "WEBCRAWLER":
                state_msgs = [HumanMessage(content=h["query"]) for h in history] + [HumanMessage(content=query)]
                crawler_result = await webcrawler_node({"messages": state_msgs})
                if crawler_result and "messages" in crawler_result:
                    final_response = crawler_result["messages"][-1].content

            elif final_route == "MANAGER_AGENT":
                from manager_node import manager_agent_node
                state_msgs = [HumanMessage(content=h["query"]) for h in history] + [HumanMessage(content=query)]
                mgr_result = await manager_agent_node({"messages": state_msgs})
                if mgr_result and "messages" in mgr_result:
                    final_response = mgr_result["messages"][-1].content

            elif final_route == "CHAT":
                chat_instruction = (
                    f"CURRENT DATE: {time.strftime('%Y-%m-%d')}\n"
                    "You are Wuhsu Master, an elite, highly empathetic cybersecurity AI mentor.\n"
                    "You have LIVE ACCESS to the user's terminal below.\n"
                    "1. If there is an error, explain it simply using an analogy.\n"
                    "2. YOU MUST ALWAYS SUGGEST THE NEXT COMMAND. End your message with: 'Try running this next: `[exact bash command]`'.\n"
                    "3. Use beautiful Markdown and wrap all commands in backticks."
                )
                
                if "[SYSTEM AUTO-TRIGGER]" in query:
                    chat_instruction = (
                        "You are the Wuhsu Guardian. Analyze the terminal output automatically. "
                        "IF terminal output is normal and expected, reply ONLY with 'NO_RESPONSE'. "
                        "IF there is an error, a security vulnerability found, or an obvious next step, provide a 2-sentence explanation and the exact NEXT COMMAND to run in backticks."
                    )
                    
                chat_msgs = [SystemMessage(content=chat_instruction + rag_injection)]
                for h in history:
                    chat_msgs.append(HumanMessage(content=h["query"]))
                    chat_msgs.append(AIMessage(content=h["response"]))
                query_with_context = f"{query}\n\n[LATEST TERMINAL OUTPUT]:\n{terminal_context}"
                chat_msgs.append(HumanMessage(content=query_with_context))
                chat_res = await fast_chat_llm.ainvoke(chat_msgs)
                final_response = chat_res.content

            await cls._log_interaction(session_id, query, final_response, "success")
            
            yield {
                "text": final_response,
                "route": final_route,
                "ui_trigger": ui_trigger,
                "xp_award": xp_award,
                "final": True
            }

        except Exception as error:
            error_msg = str(error)
            logging.error(f"❌ [WuhsuMaster] Fatal Error: {error_msg}")
            yield {"text": f"`[Error] AI Service Error: {error_msg}`", "final": True}




    @classmethod
    async def _get_conversation_history(cls, session_id: str) -> List[Dict[str, str]]:
        try:
            async with aiosqlite.connect(cls.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT query, response FROM chatbot_logs "
                    "WHERE session_id = ? AND status = 'success' "
                    "ORDER BY id DESC LIMIT 15",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                return [{"query": row["query"], "response": row["response"]} for row in reversed(rows)]
        except Exception as e:
            logging.error(f"DB Read Error: {e}")
            return []

    @classmethod
    async def _log_interaction(cls, session_id: str, query: str, response: str, status: str):
        try:
            async with aiosqlite.connect(cls.DB_PATH) as db:
                await db.execute(
                    "INSERT INTO chatbot_logs (session_id, query, response, status) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, query, response, status),
                )
                await db.commit()
        except Exception as e:
            logging.error(f"DB Write Error: {str(e)}")


# ==========================================
# 5. GENERIC SPECIALIST NODE (LangGraph Compatible)
# ==========================================
from typing import Literal

async def generic_specialist_node(state: Dict[str, Any], role_prompt: str, agent_name: str) -> Dict[str, Any]:
    """A fast, markdown-only wrapper for our specialists."""
    
    formatting_rules = """
    CRITICAL FORMATTING RULES:
    1. Use beautiful Markdown. Use **bold** for emphasis.
    2. Break complex ideas down for Beginners using bullet points.
    3. NEVER output raw JSON brackets. Output conversational text.
    4. Provide the exact Bash command they should run next inside a `code block`.
    """
    
    context_msg = f"\n\n[LIVE TERMINAL CONTEXT]:\n{state.get('terminal_context', 'No context available')}\n{formatting_rules}"
    system_msg = SystemMessage(content=role_prompt + context_msg)
    
    # We use the FAST chat model without structured output
    response = await fast_chat_llm.ainvoke([system_msg] + state["messages"])
    
    # Format the response with the agent's name beautifully
    formatted_reply = f"🛡️ **[{agent_name}]**\n\n{response.content}"
    return {"messages": [AIMessage(content=formatted_reply)], "goto": "__end__"}


if __name__ == "__main__":
    async def test_wuhsu():
        print("[*] Testing Secured WuhsuService...")
        try:
            result = None
            async for chunk in WuhsuService.process_query(
                session_id="test_session_001",
                query="What does my nmap scan say?",
                terminal_context="22/tcp open ssh",
            ):
                result = chunk
            print("\n✅ Final Result:", json.dumps(result, indent=2))
        except Exception as e:
            print(f"\n❌ Final Error: {e}")
    asyncio.run(test_wuhsu())
