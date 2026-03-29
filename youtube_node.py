from __future__ import annotations

import re
import json
import logging
import asyncio
import os
from typing import Any, List, Literal, Optional
from typing_extensions import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ─── Logger ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("WuhsuYouTubeScout")

from wuhsu_common import WuhsuState, llm

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — STRUCTURED OUTPUT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class YouTubeSearchIntent(BaseModel):
    """
    What the LLM must fill after reading the conversation.
    """
    primary_query: str = Field(
        alias="query",
        description=(
            "The best YouTube search query for this user's question. "
            "Be specific: include the technology + action + level. "
            "Example: 'Linux chmod permissions tutorial beginners Kali'"
        ),
        json_schema_extra={
            "system_prompt": (
                "You are the Wuhsu YouTube Scout. Your job is to find the most relevant "
                "cybersecurity tutorial videos for the user based on their query."
            )
        }
    )
    fallback_query_1: str = Field(
        default="",
        description=(
            "A simpler/broader backup query if primary returns nothing. "
            "Example: 'chmod linux permissions explained'"
        )
    )
    fallback_query_2: str = Field(
        default="",
        description=(
            "The broadest possible last-resort query. "
            "Example: 'Linux file permissions tutorial'"
        )
    )
    audience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = Field(
        description=(
            "Skill level of the user based on how they write. "
            "BEGINNER = simple questions, 'what is...'. "
            "ADVANCED = uses technical terms, mentions CVEs, tools."
        ),
        default="BEGINNER"
    )
    concept_being_taught: str = Field(
        alias="concept",
        description=(
            "In 3–5 words: what concept are we teaching? "
            "Example: 'Linux file permissions', 'TCP handshake', 'nmap port scanning'"
        )
    )
    class Config:
        populate_by_name = True


class VideoRelevanceScore(BaseModel):
    """
    After finding videos, the LLM scores each one for relevance.
    """
    video_title: str = Field(description="The title of the video being scored")
    score: int = Field(
        description="Relevance score from 0 (totally irrelevant) to 10 (perfect match)",
        ge=0, le=10
    )
    reason: str = Field(
        description="One sentence explaining why this score was given"
    )
    should_use: bool = Field(
        description="True only if score >= 6 AND the video is educational (not entertainment)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

QUERY_EXTRACTION_PROMPT = """
You are the YouTube Search Query Specialist for the WUHSU LAB Cybersecurity Learning Platform.

Your job: Read the conversation between a cybersecurity student and Wuhsu Master,
and generate the BEST possible YouTube search queries to find a tutorial.

GUIDELINES:
- Focus on the MOST RECENT user message and any visible terminal commands.
- If the user ran: "chmod 777 secret.txt" → search for "chmod linux permissions"  
- If the user asks about a CVE → search for "CVE-XXXX-XXXX explained tutorial"
- If the user is stuck on a tool → search for "[tool name] tutorial [use case]"
- If the user asks about Web3/Blockchain → search for "Web3 security" or "[topic] tutorial"
- Always generate 3 queries: specific → medium → broad (as fallbacks)
- Detect skill level from HOW they write:
    Beginner:     "what does this command do?" → add "explained for beginners"
    Intermediate: "I understand X but not Y" → add "deep dive"
    Advanced:     Uses technical jargon → add "advanced technique"

DO NOT generate queries for:
- Entertainment videos (gaming, music, etc.)
- Non-educational content
- Anything unrelated to technology, cybersecurity, Linux, networking, programming, or Web3.
"""

RELEVANCE_SCORING_PROMPT = """
You are the Video Quality Validator for the WUHSU LAB Cybersecurity Learning Platform.

You will receive a video title. Score it from 0–10 based on:

SCORE 9–10: Perfect tutorial, directly addresses the topic, from a known tech channel
SCORE 7–8:  Good tutorial, related topic, educational
SCORE 5–6:  Somewhat related, might be useful
SCORE 0–4:  Entertainment, wrong topic, clickbait, or not educational

SHOULD_USE = True only if score >= 6 AND title sounds educational.

Known good channels: NetworkChuck, David Bombal, John Hammond, 
IppSec, TCM Security, Professor Messer, CBT Nuggets, Computerphile
"""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — YOUTUBE SEARCH WITH RETRY
# ══════════════════════════════════════════════════════════════════════════════

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _youtube_search_sync(query: str, max_results: int = 3) -> list:
    """
    Synchronous YouTube search wrapped in retry logic.
    """
    try:
        from youtube_agent import YouTubeAgent
    except ImportError:
        logger.error("youtube_agent module not found.")
        return []

    yt = YouTubeAgent()
    results = yt.search(query, max_results=max_results)
    return results or []


async def _youtube_search_async(query: str, max_results: int = 3) -> list:
    """
    Async wrapper: runs the blocking YouTube search in a thread pool.
    """
    logger.info(f"[YouTube] Searching: {query}")
    return await asyncio.to_thread(_youtube_search_sync, query, max_results)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — VIDEO RELEVANCE SCORER
# ══════════════════════════════════════════════════════════════════════════════

async def _score_video(title: str, concept: str) -> VideoRelevanceScore:
    """
    Ask the LLM to score a video's relevance before showing it to the user.
    """
    structured = llm.with_structured_output(VideoRelevanceScore)
    try:
        score = await structured.ainvoke([
            SystemMessage(content=RELEVANCE_SCORING_PROMPT),
            HumanMessage(content=f"Concept being taught: {concept}\nVideo title: {title}")
        ])
        if not score:
            raise ValueError("LLM returned no score")
        return score
    except Exception as e:
        logger.warning(f"[YouTube] Scoring failed for '{title}': {e}")
        return VideoRelevanceScore(
            video_title=title, score=6, reason="scoring unavailable", should_use=True
        )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — THE LANGGRAPH NODE
# ══════════════════════════════════════════════════════════════════════════════

async def youtube_agent_node(state: WuhsuState) -> dict:
    """
    The YouTube Agent LangGraph Node.
    """
    messages = state.get("messages", [])
    if not messages:
        messages = [HumanMessage(content="Show me a general cybersecurity tutorial")]

    last_user_msg = "cybersecurity tutorial"
    for m in reversed(messages):
        if hasattr(m, "content") and m.type == "human":
            last_user_msg = m.content
            break

    logger.info("[YouTubeAgent] Sending initial loading signal...")
    # This immediately tells the UI to show a loading state in the Tactical Sandbox
    yield {"messages": [AIMessage(content="```json_ui_trigger\n{\"action\":\"UI_UPDATE\",\"panel\":\"YOUTUBE\",\"loading\":true}\n```")]}

    logger.info("[YouTubeAgent] Extracting search intent from conversation...")

    try:
        # MiniMax with structured output is the preferred way
        structured_llm = llm.with_structured_output(YouTubeSearchIntent)
        intent = await structured_llm.ainvoke(
            [SystemMessage(content=QUERY_EXTRACTION_PROMPT)] + messages
        )
        if not intent:
            raise ValueError("LLM returned no intent")
    except Exception as e:
        logger.warning(f"[YouTubeAgent] Intent extraction failed, trying manual JSON extraction: {e}")
        try:
            # Fallback to direct prompt + robust manual parsing
            resp = await llm.ainvoke(
                [SystemMessage(content=QUERY_EXTRACTION_PROMPT + "\nIMPORTANT: OUTPUT VALID JSON ONLY. Do not use markdown wrappers like ```json.")] + messages
            )
            content = resp.content.strip()
            
            # Bulletproof JSON extractor: Find the first { and the last }
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                clean_json = content[start_idx:end_idx+1]
                data = json.loads(clean_json)
                
                intent = YouTubeSearchIntent(
                    primary_query=data.get("query") or data.get("primary_query") or last_user_msg,
                    fallback_query_1=data.get("fallback_query_1", ""),
                    fallback_query_2=data.get("fallback_query_2", ""),
                    audience_level=data.get("audience_level", "BEGINNER"),
                    concept_being_taught=data.get("concept") or data.get("concept_being_taught") or "Cybersecurity"
                )
            else:
                raise ValueError("No JSON brackets found in LLM output.")
                
        except Exception as e2:
            logger.error(f"[YouTubeAgent] All extraction layers failed: {e2}. Using emergency fallback.")
            intent = YouTubeSearchIntent(
                primary_query=last_user_msg,
                fallback_query_1="cybersecurity basics tutorial",
                fallback_query_2="linux tutorial",
                audience_level="BEGINNER",
                concept_being_taught="General Tech"
            )

    # ── STEP 2 + 3: SEARCH WITH FALLBACK CHAIN ───────────────────────────────
    query_chain = [
        intent.primary_query,
        intent.fallback_query_1,
        intent.fallback_query_2,
    ]

    raw_results = []
    used_query  = ""

    for query in query_chain:
        if not query.strip():
            continue
        try:
            results = await _youtube_search_async(query, max_results=3)
            if results:
                raw_results = results
                used_query  = query
                logger.info(f"[YouTubeAgent] Found {len(results)} results for: '{query}'")
                break
            else:
                logger.info(f"[YouTubeAgent] No results for '{query}', trying fallback...")
        except Exception as e:
            logger.warning(f"[YouTubeAgent] Search failed for '{query}': {e}")
            continue

    # ── HARD FAILURE: Nothing found after all 3 queries ──────────────────────
    if not raw_results:
        logger.warning("[YouTubeAgent] All 3 queries returned no results.")
        yield {
            "messages": [AIMessage(content=(
                "📺 **[YouTube Agent]**\n\n"
                f"I searched for **'{intent.primary_query}'** (and two fallback queries) "
                f"but couldn't find a relevant tutorial right now.\n\n"
                f"Try searching YouTube manually for: `{intent.concept_being_taught} tutorial`"
            ))]
        }
        return


    # ── STEP 4: SCORE ALL RESULTS FOR RELEVANCE ───────────────────────────────
    logger.info(f"[YouTubeAgent] Scoring {len(raw_results)} results...")
    scoring_tasks = [
        _score_video(v.get("title", "Unknown"), intent.concept_being_taught)
        for v in raw_results
    ]
    scores = await asyncio.gather(*scoring_tasks, return_exceptions=True)

    # ── STEP 5: SELECT BEST VIDEO ─────────────────────────────────────────────
    best_video = None
    best_score = -1

    for video, score_result in zip(raw_results, scores):
        if isinstance(score_result, Exception):
            continue
        if score_result.should_use and score_result.score > best_score:
            best_score = score_result.score
            best_video = video
            logger.info(
                f"[YouTubeAgent] New best: '{video.get('title')}' "
                f"(score: {score_result.score}/10 — {score_result.reason})"
            )

    if best_video is None:
        logger.warning("[YouTubeAgent] No video passed relevance filter. Using first result.")
        best_video = raw_results[0]

    video_id = best_video.get("video_id", "")
    title    = best_video.get("title", "Cybersecurity Tutorial")
    channel  = best_video.get("channel_title", "Unknown Channel")
    duration = best_video.get("duration", "")

    if not video_id:
        logger.error("[YouTubeAgent] Best video has no video_id. Aborting.")
        yield {
            "messages": [AIMessage(content=(
                "📺 **[YouTube Agent]**\n\n"
                "I found a video but couldn't get a valid URL. Please try again."
            ))]
        }
        return


    # Build embed URL with autoplay
    embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"

    # ── STEP 7: BUILD THE CHAT RESPONSE ──────────────────────────────────────
    level_prefix = {
        "BEGINNER":     "Since you're learning this for the first time,",
        "INTERMEDIATE": "To deepen your understanding,",
        "ADVANCED":     "For a technical deep-dive,"
    }.get(intent.audience_level, "")

    duration_str = f" ({duration})" if duration else ""
    score_str    = f" _(relevance: {best_score}/10)_" if best_score > 0 else ""

    chat_text = (
        f"📺 **[YouTube Agent]**\n\n"
        f"{level_prefix} I found a great resource on **{intent.concept_being_taught}**:\n\n"
        f"**{title}**{duration_str} by *{channel}*{score_str}\n\n"
        f"I searched for: `{used_query}`\n"
        f"Loading it in the Sandbox panel now — it will autoplay immediately! 🎬"
    )

    # ── STEP 8: BUILD THE UI TRIGGER PAYLOAD ─────────────────────────────────
    ui_payload = {
        "action":   "UI_UPDATE",
        "panel":    "YOUTUBE",
        "url":      embed_url,
        "title":    title,
        "channel":  channel,
        "query":    used_query,
        "score":    best_score,
        "concept":  intent.concept_being_taught,
        "level":    intent.audience_level,
    }

    final_content = (
        f"{chat_text}\n\n"
        f"```json_ui_trigger\n"
        f"{json.dumps(ui_payload, indent=2)}\n"
        f"```"
    )

    logger.info(f"[YouTubeAgent] Done. Returning video: {title} by {channel}")
    yield {"messages": [AIMessage(content=final_content)]}

