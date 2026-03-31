import requests
from pydantic import BaseModel, Field
import json
import logging
import os

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("mcp_schema_tool")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MCP_API_URL = os.getenv("MCP_SCHEMA_URL", "http://localhost:8080/api/v1/schemas")
MCP_API_KEY = os.getenv("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")

class DBIntrospectionToolInput(BaseModel):
    """
    Input schema for the Database Introspection Tool.
    Requires no arguments as it fetches the full schema.
    """
    pass

def execute_schema_introspection(input_data: DBIntrospectionToolInput) -> str:
    """
    Tool for GenAI Agents to discover the PostgreSQL schema (tables and columns).
    Agents MUST run this tool before generating any SQL queries.
    
    Banking Relevance: Ensures the Agent is aware of the exact data types and table
    structures (e.g., enriched_trades vs daily_summary) to avoid generating hallucinated
    or inefficient queries.
    """
    logger.info("GenAI Agent triggered schema introspection tool.")
    
    try:
        headers = {
            "X-API-Key": MCP_API_KEY
        }
        response = requests.get(MCP_API_URL, headers=headers, timeout=10)
        
        if response.status_code == 403:
            return f"Error: Request rejected by MCP Server. Status 403. Details: {response.text}"
        if response.status_code == 429:
            return "Error: Rate limit exceeded."
            
        response.raise_for_status()
        
        schemas = response.json()
        
        # Format for LLM context (Markdown-friendly)
        result = "Database Schema Documentation:\n\n"
        for table in schemas:
            result += f"Table: {table['table_name']}\n"
            result += "Columns:\n"
            for col in table["columns"]:
                result += f"  - {col['name']} ({col['type']})\n"
            result += "\n"
            
        return result
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch schemas from MCP server: {e}")
        return f"Error: Could not retrieve database schema. Details: {str(e)}"

# Example usage for LangChain/Autogen:
# from langchain.tools import tool
# @tool("database_schema_tool", args_schema=DBIntrospectionToolInput)
# def get_database_schema(input_data: DBIntrospectionToolInput) -> str:
#     return execute_schema_introspection(input_data)
