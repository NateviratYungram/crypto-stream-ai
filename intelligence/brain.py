import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

BRAIN_STATE_FILE = "brain_state.json"

def get_brain_state() -> Dict[str, Any]:
    """Retrieve the AI's current working memory and emotional state."""
    if not os.path.exists(BRAIN_STATE_FILE):
        return {
            "frontal_lobe": "No current focus. Analysing market regime.",
            "emotion": "NEUTRAL",
            "last_updated": None
        }
    
    try:
        with open(BRAIN_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read brain state: {e}")
        return {"error": str(e)}

def update_brain_state(memory: Optional[str] = None, emotion: Optional[str] = None) -> Dict[str, Any]:
    """Update the AI's cognitive focus or emotional baseline."""
    current = get_brain_state()
    if "error" in current: current = {"frontal_lobe": "", "emotion": "NEUTRAL"}
    
    if memory:
        current["frontal_lobe"] = memory
    if emotion:
        current["emotion"] = emotion.upper()
        
    current["last_updated"] = datetime.now().isoformat()
    
    try:
        with open(BRAIN_STATE_FILE, "w") as f:
            json.dump(current, f, indent=2)
        logger.info(f"Brain state updated: {current['emotion']} | {current['frontal_lobe'][:50]}...")
        return {"status": "SUCCESS", "state": current}
    except Exception as e:
        logger.error(f"Failed to save brain state: {e}")
        return {"status": "ERROR", "error": str(e)}
