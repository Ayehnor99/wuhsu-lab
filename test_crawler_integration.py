import asyncio
import json
from wuhsu_agent import WuhsuService

async def test_crawler():
    print("[*] Testing WebCrawler Integration through WuhsuService...")
    try:
        result = await WuhsuService.process_query(
            session_id="test_crawler_session",
            query="Search for latest cybersecurity news about Qwen 3.5",
            terminal_context="User is exploring AI capabilities."
        )
        print("\n✅ Final Result from Wuhsu Agent:")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"\n❌ Final Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_crawler())
