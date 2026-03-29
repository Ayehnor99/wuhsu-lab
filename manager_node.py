import json
import logging
from typing import Literal, Optional
from langchain_core.messages import AIMessage, SystemMessage
from pydantic import BaseModel, Field

from wuhsu_common import WuhsuState, llm

class ManagerDecision(BaseModel):
    action: Literal["AWARD_XP", "GENERATE_REPORT", "GENERATE_SOCIAL_POST"] = Field(
        description="Choose action based on user intent."
    )
    skill_name: Optional[str] = Field(description="The infosec skill practiced (e.g., 'Network Recon').")
    xp_awarded: int = Field(default=0, description="XP to award (10-100).")
    generated_content: str = Field(
        description="If REPORT, write a professional pentest summary. If SOCIAL_POST, write an engaging LinkedIn/Twitter post with hashtags. Otherwise, write a short encouragement."
    )

async def manager_agent_node(state: WuhsuState):
    """
    The Enhanced Manager Agent. Tracks XP, writes Pentest Reports, and drafts Social Media updates.
    """
    logging.info("📊 [Manager Agent] Node activated using minimax-m2.7:cloud.")
    
    prompt = SystemMessage(content="""
    You are the Manager Agent for a cybersecurity professional.
    Analyze the terminal context and the user's chat.
    - If they just ran a command successfully, award XP and encourage them.
    - If they say "Write a report on my scan", draft a professional Pentest Report (Executive Summary, Technical Details, Remediation).
    - If they say "Draft a LinkedIn post", write an engaging infosec social media post highlighting what they just learned.
    """)
    
    # MiniMax outputs structured JSON perfectly here
    structured_llm = llm.with_structured_output(ManagerDecision)
    decision: ManagerDecision = await structured_llm.ainvoke([prompt] + state["messages"])
    
    chat_text = f"📊 **[Manager Agent]**\n\n{decision.generated_content}"
    
    if decision.action == "AWARD_XP":
        chat_text += f"\n\n*Awarded **+{decision.xp_awarded} XP** to `{decision.skill_name}`!*"
    
    # Trigger UI update for the Dashboard
    ui_payload = json.dumps({
        "action": "UI_UPDATE",
        "panel": "DASHBOARD",
        "type": decision.action,
        "skill": decision.skill_name or "",
        "xp": decision.xp_awarded,
        "content": decision.generated_content
    })
    
    final_content = f"{chat_text}\n\n```json_ui_trigger\n{ui_payload}\n```"
    return {"messages": [AIMessage(content=final_content)]}
