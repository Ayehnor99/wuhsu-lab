import asyncio
import time
import logging
from unittest.mock import MagicMock, patch, AsyncMock
from wuhsu_agent import WuhsuService, switch_to_local, switch_to_cloud

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test_llm_switching_and_model():
    print("\n--- Starting LLM Model and Fallback Verification ---")
    
    # 1. Verify Model Name
    from wuhsu_agent import _primary_llm
    print(f"Primary model: {_primary_llm.model}")
    assert _primary_llm.model == "minimax-m2.7:cloud"

    # 2. Verify initial state
    from wuhsu_agent import _llm_mode
    print(f"Initial mode: {_llm_mode}")
    assert _llm_mode == "CLOUD"

    # 3. Mock a connection error and verify immediate switch
    print("Testing immediate fallback on connection error...")
    
    # Mock the LLM to throw a connection error
    with patch('wuhsu_agent.llm.with_structured_output') as mock_structured:
        mock_target = MagicMock()
        # Mock its ainvoke to throw an error then succeed on retry (Local)
        # Actually, switch_to_local changes the global llm, but inside process_query,
        # we still use the 'llm' from the local scope if it's passed as an argument.
        # But _invoke_with_fallback uses llm_to_use (which is the global llm).
        
        mock_target.ainvoke = AsyncMock(side_effect=Exception("Connection timed out"))
        mock_structured.return_value = mock_target
        
        # We need to mock _fallback_llm too
        with patch('wuhsu_agent._fallback_llm.with_structured_output') as mock_fallback_structured:
            mock_fallback_target = MagicMock()
            from wuhsu_agent import WuhsuDecision
            mock_fallback_target.ainvoke = AsyncMock(return_value=WuhsuDecision(
                response="Fallback success",
                route="CHAT"
            ))
            mock_fallback_structured.return_value = mock_fallback_target
            
            # Reset state
            from wuhsu_agent import _llm_mode
            if _llm_mode != "CLOUD": switch_to_cloud()
            
            try:
                result = await WuhsuService.process_query("test_session", "Hello")
                print(f"Result with fallback: {result['text']}")
                assert result['text'] == "Fallback success"
            except Exception as e:
                print(f"Fallback test failed with: {e}")
                raise e
            
            from wuhsu_agent import _llm_mode as mode_after
            print(f"Mode after fallback: {mode_after}")
            assert mode_after == "LOCAL"

    print("\n✅ LLM Model and Fallback Logic Verified Successfully!")

if __name__ == "__main__":
    asyncio.run(test_llm_switching_and_model())
