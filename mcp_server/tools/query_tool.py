import requests
from pydantic import BaseModel, Field
import json
import logging

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("mcp_query_tool")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MCP_API_URL = os.getenv("MCP_API_URL", "http://localhost:8080/api/v1/query")
MCP_API_KEY = os.getenv("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")

class SQLQueryToolInput(BaseModel):
    """
    Input schema for the SQL Query Execution Tool.
    """
    sql: str = Field(..., description="PostgreSQL syntax query string to execute. MUST be a SELECT statement.")
    max_rows: int = Field(50, description="Maximum number of rows to return to prevent context window explosion.")

def execute_sql_query(input_data: SQLQueryToolInput) -> str:
    """
    Tool for GenAI Agents to execute SQL queries against the CryptoStream Lakehouse.
    Returns results formatted as a Markdown table or JSON string.
    
    Banking Relevance: "Chat with Data" capability. Allows compliance officers
    or branch managers to ask questions like "How many whale transactions happened today?"
    without writing SQL.
    """
    logger.info(f"GenAI Agent triggered query tool with SQL: {input_data.sql}")
    
    try:
        payload = {
            "sql": input_data.sql,
            "max_rows": input_data.max_rows
        }
        
        headers = {
            "X-API-Key": MCP_API_KEY,
            "Content-Type": "application/json"
        }
        
        response = requests.post(MCP_API_URL, json=payload, headers=headers, timeout=30)
        
        # Handle 403 Forbidden (SQL Injection protection or Invalid API Key)
        if response.status_code == 403:
            return f"Error: Request rejected by MCP Server. Status 403. Details: {response.text}"
            
        # Handle 429 Too Many Requests (Rate limit exceeded)
        if response.status_code == 429:
            return "Error: Rate limit exceeded. Please try again later."
            
        response.raise_for_status()
        result_data = response.json()
        
        rows = result_data.get("data", [])
        row_count = result_data.get("row_count", 0)
        
        if row_count == 0:
            return "Query executed successfully. 0 rows returned."
            
        # Format results as a markdown table for the LLM
        columns = list(rows[0].keys())
        
        md_table = f"Query returned {row_count} rows:\n\n"
        md_table += "| " + " | ".join(columns) + " |\n"
        md_table += "|" + "|".join(["---" for _ in columns]) + "|\n"
        
        for row in rows:
            md_table += "| " + " | ".join([str(row[c]) for c in columns]) + " |\n"
            
        return md_table
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to execute SQL via MCP server: {e}")
        return f"Error executing query. Details: {str(e)}"

# Example usage for LangChain/Autogen:
# from langchain.tools import tool
# @tool("execute_sql_query", args_schema=SQLQueryToolInput)
# def run_sql(input_data: SQLQueryToolInput) -> str:
#     return execute_sql_query(input_data)
