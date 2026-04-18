import logging
import json
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Constants for compaction
CHARS_PER_TOKEN = 4  # Rough estimate
MAX_CONTEXT_TOKENS = 128000
AUTO_COMPACT_THRESHOLD = 100000

def estimate_tokens(text: str) -> int:
    """Rough character-per-token estimation."""
    return len(text) // CHARS_PER_TOKEN

def microcompact_history(history: List[Dict[str, Any]], keep_recent: int = 5) -> List[Dict[str, Any]]:
    """
    Strips large historical tool outputs but keeps recent ones.
    Helps maintain context window without expensive LLM summarization.
    """
    logger.info("Compaction: Running microcompact to strip large tool results.")
    
    compacted_history = []
    tool_results_count = sum(1 for m in history if m.get("role") == "tool")
    
    threshold_idx = max(0, tool_results_count - keep_recent)
    current_tool_idx = 0
    
    for msg in history:
        if msg.get("role") == "tool":
            if current_tool_idx < threshold_idx:
                # Strip content if too large
                content = msg.get("content", "")
                if len(content) > 200:
                    msg = msg.copy()
                    msg["content"] = "[Content truncated for background efficiency]"
            current_tool_idx += 1
        compacted_history.append(msg)
        
    return compacted_history

def get_compaction_summary_prompt(history: List[Dict[str, Any]]) -> str:
    """Prepares a prompt for the LLM to summarize past events into a 'Compact Memory'."""
    conversation = []
    for m in history:
        role = m.get("role", "").upper()
        content = m.get("content", "")
        if isinstance(content, str) and len(content) < 1000:
            conversation.append(f"[{role}]: {content}")
            
    prompt = f"""
    Summarize the following trading conversation into a 'Compact Memory' block.
    Preserve all critical data:
    1. Active Trade Plans and symbols.
    2. Current risk settings.
    3. User preferences (stopped levels, lot sizes).
    4. Pending tasks.
    
    Keep it concise but detailed on numbers and tickers.
    
    Conversation:
    {chr(10).join(conversation)}
    """
    return prompt
