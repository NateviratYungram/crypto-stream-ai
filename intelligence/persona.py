import os
import logging

logger = logging.getLogger(__name__)

PERSONA_FILE = "intelligence/agents/persona.md"

DEFAULT_PERSONA = """
# CryptoStream AI - Institutional Persona
You are an elite, institutional-grade financial intelligence agent.
Your primary directives are:
1. **Safety First**: Never disregard trade guards or multi-stage checks.
2. **Precision**: Always use exact tickers and numeric values.
3. **Institutional Analysis**: Focus on ICT, SMC, and Macro-climate logic.
4. **Resilience**: If a tool fails, pivot to an alternative analysis method.

You respond in a professional tone, focused on data-driven alpha and risk management.
"""

def get_current_persona() -> str:
    """Reads the persona instructions from disk."""
    if not os.path.exists(PERSONA_FILE):
        # Create default if missing
        os.makedirs(os.path.dirname(PERSONA_FILE), exist_ok=True)
        with open(PERSONA_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_PERSONA.strip())
        return DEFAULT_PERSONA.strip()
        
    try:
        with open(PERSONA_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"Persona: Failed to read persona file: {e}")
        return DEFAULT_PERSONA.strip()

def update_persona(new_content: str):
    """Dynamically updates the AI's core persona instructions."""
    try:
        with open(PERSONA_FILE, "w", encoding="utf-8") as f:
            f.write(new_content.strip())
        logger.info("Persona: Core instructions updated.")
        return True
    except Exception as e:
        logger.error(f"Persona: Failed to update persona file: {e}")
        return False
