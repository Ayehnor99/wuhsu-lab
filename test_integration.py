import asyncio
from wuhsu_agent import WuhsuService

async def test_chat():
    print("[*] Testing Wuhsu Master Agent (Qwen 3.5)...")
    try:
        result = await WuhsuService.process_query('test', 'Search for latest OpenSSH CVEs in 2026')
        print('\n\n---FINAL RESPONSE---\n', result)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    asyncio.run(test_chat())
