import os
import json
import logging
import asyncio
from typing import Literal
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from pydantic import BaseModel, Field

# Import the Firecrawl SDK safely
try:
    from firecrawl import FirecrawlApp
    _HAS_FIRECRAWL = True
except ImportError:
    _HAS_FIRECRAWL = False
    logging.warning("⚠️ Firecrawl SDK not found. Install it with 'pip install firecrawl-py'.")

# Import our shared Ollama Cloud LLM (Qwen 3.5) and State
# Fixed: Importing from wuhsu_common to prevent circular imports with wuhsu_agent
from wuhsu_common import WuhsuState, llm

load_dotenv()

# Initialize Firecrawl
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
firecrawl_app = None
if FIRECRAWL_API_KEY:
    try:
        firecrawl_app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
    except Exception as e:
        logging.error(f"Failed to initialize Firecrawl SDK: {e}")
else:
    logging.warning("⚠️ FIRECRAWL_API_KEY not found. Scraping will fail.")

# ==========================================
# 1. FIRECRAWL OSINT UTILITIES
# ==========================================
def firecrawl_scrape_url(url: str) -> str:
    """Uses Firecrawl to bypass anti-bot and extract pure Markdown for the LLM."""
    try:
        if not firecrawl_app:
            return "Firecrawl app not initialized. Check API Key."
            
        logging.info(f"🔥 [WebCrawler] Firecrawling URL: {url}")
        
        # Scrape the target URL and request markdown format
        # scrape_url is synchronous in the SDK, so we'll wrap it in to_thread if called from async
        scrape_result = firecrawl_app.scrape_url(
            url, 
            params={'formats': ['markdown']}
        )
        
        if scrape_result and 'markdown' in scrape_result:
            # Return the first 3000 characters to protect the LLM context window
            markdown_content = scrape_result['markdown'][:3000]
            return f"--- SCRAPED DATA FROM {url} ---\n{markdown_content}"
        else:
            return "Failed to extract markdown from the page."
            
    except Exception as e:
        logging.error(f"🔥 Firecrawl Error: {e}")
        return f"Crawl failed: {str(e)}"

def firecrawl_search_web(query: str) -> str:
    """Uses Firecrawl to search the web for OSINT intelligence."""
    from wuhsu_common import quick_ddg_search
    try:
        if not firecrawl_app:
            logging.warning("🔥 Firecrawl app not initialized. Falling back to DuckDuckGo.")
            return quick_ddg_search(query)
            
        logging.info(f"🔥 [WebCrawler] Firecrawl searching for: {query}")
        
        search_result = firecrawl_app.search(query)
        if not search_result:
            logging.warning("🔥 Firecrawl returned no results. Falling back to DuckDuckGo.")
            return quick_ddg_search(query)
            
        # Parse Pydantic SearchData object or dictionary
        if hasattr(search_result, "model_dump"):
            data = search_result.model_dump()
        elif hasattr(search_result, "dict"):
            data = search_result.dict()
        elif isinstance(search_result, dict):
            data = search_result
        else:
            data = {}
            
        web_results = data.get("web") or data.get("data") or []
        
        if not web_results or not isinstance(web_results, list):
            logging.warning("🔥 Firecrawl returned no web results. Falling back to DuckDuckGo.")
            return quick_ddg_search(query)
            
        formatted_results = f"--- FIRECRAWL SEARCH RESULTS FOR: {query} ---\n\n"
        for idx, result in enumerate(web_results[:5]):
            title = result.get('title', 'Unknown Title')
            url = result.get('url', 'Unknown URL')
            description = result.get('description', 'No description available.')
            formatted_results += f"### {idx+1}. {title}\n**URL:** {url}\n**Summary:** {description}\n\n"
            
        return formatted_results
        
    except Exception as e:
        logging.error(f"🔥 Firecrawl Search Error: {e}")
        return quick_ddg_search(query)


# ==========================================
# 2. INTENT PARSING (PYDANTIC)
# ==========================================
class CrawlerDecision(BaseModel):
    action: Literal["SEARCH", "CRAWL"] = Field(
        description="Choose 'SEARCH' to use DuckDuckGo for general info. Choose 'CRAWL' to read a specific URL."
    )
    query_or_url: str = Field(
        description="The search query (if SEARCH) or the exact http/https URL (if CRAWL)."
    )

# ==========================================
# 3. THE WEBCRAWLER LANGGRAPH NODE
# ==========================================
async def webcrawler_node(state: WuhsuState):
    """
    The OSINT WebCrawler Agent. Uses Firecrawl to pull pristine threat-intel.
    """
    logging.info("🕸️ [WebCrawler] Node activated.")
    
    intent_prompt = SystemMessage(content="""
    You are the OSINT WebCrawler Agent.
    Look at the terminal context and user message. 
    If the user provided a specific URL to analyze, output 'CRAWL' and the URL.
    If the user wants general intelligence (e.g., 'Latest CVEs for OpenSSH'), output 'SEARCH' and the query.
    """)
    
    # decision: CrawlerDecision = await structured_llm.ainvoke([intent_prompt] + state["messages"])
    # Note: Qwen 3.5 cloud handles structured output well
    try:
        structured_llm = llm.with_structured_output(CrawlerDecision)
        decision = await structured_llm.ainvoke([intent_prompt] + state["messages"])
    except Exception as e:
        logging.warning(f"Structured output failed in WebCrawler, using fallback: {e}")
        # Simplest fallback
        decision = CrawlerDecision(action="SEARCH", query_or_url=str(state["messages"][-1].content))

    raw_data = ""
    if decision.action == "CRAWL" and decision.query_or_url.startswith("http"):
        # 🔥 FIRECRAWL IN ACTION
        # Run synchronous scrape in separate thread
        raw_data = await asyncio.to_thread(firecrawl_scrape_url, decision.query_or_url)
    else:
        # 🔥 FIRECRAWL SEARCH
        raw_data = await asyncio.to_thread(firecrawl_search_web, decision.query_or_url)
        
    summary_prompt = SystemMessage(content=f"""
    You are the OSINT WebCrawler Agent. You just pulled the following raw data from the internet:
    {raw_data}
    
    Summarize this cybersecurity intelligence. Extract CVE IDs, CVSS scores, or Indicators of Compromise (IOCs).
    Format nicely in markdown.
    """)
    
    final_response = await llm.ainvoke([summary_prompt] + state["messages"])
    
    formatted_reply = f"🕸️ **[Threat Intel Agent]**\n\n*Source: {decision.query_or_url}*\n\n{final_response.content}"
    
    return {"messages": [AIMessage(content=formatted_reply)]}
