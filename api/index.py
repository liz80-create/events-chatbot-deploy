# /api/index.py
#
# The final, correct version using FastAPI. This structure correctly handles
# async operations, Vercel's routing, and data serialization.

import os
import logging
import asyncio
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date
import json

# --- Required Libraries (ensure these are in requirements.txt) ---
import aiohttp
import psycopg2
import google.generativeai as genai
from psycopg2.extras import RealDictCursor, execute_batch
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --- Final, Correct Configuration for Vercel ---

# This custom class teaches FastAPI how to convert date/datetime objects to strings.
class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=lambda obj: obj.isoformat() if isinstance(obj, (datetime, date)) else None,
        ).encode("utf-8")

# This is the main application object Vercel will find and run.
# It uses our custom JSON response class to prevent data conversion errors.
app = FastAPI(default_response_class=CustomJSONResponse)

# This middleware correctly handles CORS for all requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Your Application Code ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Config:
    AIRTABLE_PAT: Optional[str] = os.getenv('AIRTABLE_PAT')
    AIRTABLE_BASE_ID: Optional[str] = os.getenv('AIRTABLE_BASE_ID')
    AIRTABLE_TABLE_NAME: Optional[str] = os.getenv('AIRTABLE_TABLE_NAME', 'Events')
    NEON_DB_URL: Optional[str] = os.getenv('NEON_DB_URL')
    GEMINI_API_KEY: Optional[str] = os.getenv('GEMINI_API_KEY')

# --- Your Full, Original Service Classes ---

class AirtableClient:
    def __init__(self, pat_token: str, base_id: str, table_name: str):
        if not all([pat_token, base_id, table_name]):
            raise ValueError("Airtable client requires PAT, Base ID, and Table Name.")
        self.base_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        self.headers = {"Authorization": f"Bearer {pat_token}"}
        # ssl_context is implicitly handled by aiohttp with default certifi certs
    
    async def fetch_all_records(self) -> List[Dict[str, Any]]:
        all_records, offset = [], None
        async with aiohttp.ClientSession() as session:
            while True:
                params = {"pageSize": 100}
                if offset: params["offset"] = offset
                try:
                    async with session.get(self.base_url, headers=self.headers, params=params) as response:
                        response.raise_for_status()
                        data = await response.json()
                        records = data.get("records", [])
                        all_records.extend(records)
                        offset = data.get("offset")
                        if not offset: break
                except aiohttp.ClientError as e:
                    logger.error(f"Airtable API request failed: {e}")
                    raise Exception(f"Airtable error: {e}")
        return all_records

class NeonDBManager:
    def __init__(self, connection_string: str):
        if not connection_string:
            raise ValueError("DB connection string required.")
        self.connection_string = connection_string
    
    def _get_connection(self):
        try:
            return psycopg2.connect(self.connection_string)
        except psycopg2.OperationalError as e:
            logger.error(f"DB connection failed: {e}")
            raise
    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_table_schema(self) -> str:
        with self._get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'events' ORDER BY ordinal_position;")
            return "\n".join(f"- {col[0]} ({col[1]})" for col in cursor.fetchall())

class GeminiManager:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API key required.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    async def generate_sql_query(self, user_query: str, flow: str, table_schema: str) -> str:
        if flow == "get_event_details":
            prompt = f"""You are a PostgreSQL expert. The user has provided the following text to identify a single, specific event from a list they were shown: "{user_query}"\n**Database Schema:**\n{table_schema}\nThis text might be a messy combination of the event's name, location, and date.\n**Your Task:**\n1. Intelligently identify the core **event name**.\n2. Intelligently identify the **date**, if one is mentioned in the text.\n3. Write a precise SQL query to `SELECT *` from the `events` table that matches these extracted criteria.\n4. If a date is found, add a condition like `AND start_time::date = 'YYYY-MM-DD'`.\n5. Use `ILIKE` for the name match to be case-insensitive.\n6. You **MUST** use `LIMIT 1` to ensure only one result is returned.\n7. Return ONLY the raw SQL query.\n**Example 1:**\nUser Question: "AM volunteers shift 2 release on July 19, 2025"\nSQL Output: SELECT * FROM events WHERE (name ILIKE '%AM volunteers shift 2 release%' OR programme ILIKE '%AM volunteers shift 2 release%' OR notes ILIKE '%AM volunteers shift 2 release%') AND start_time::date = '2025-07-19' ORDER BY start_time ASC LIMIT 1;"""
        else:
            prompt = f"""You are an expert PostgreSQL query generator for a Festival Events database. Convert the user's question into a precise SQL query.\n**Database Schema:**\n{table_schema}\n**ADVANCED SEARCH RULES:**\n1. **Keyword Logic (CRITICAL RULE):** For multi-word queries like "food fest" or "film screening", identify the core keywords (e.g., 'food', 'fest'). Each keyword should have its own search block (`(name ILIKE '%keyword%' OR programme ILIKE '%keyword%')`). You **MUST** connect these distinct keyword blocks with `AND` to ensure all terms are present in the results.\n2. **Date Handling (CRITICAL RULE):** If the user provides a date or asks about "today" or "tomorrow", you **MUST** search against the `start_time` column. The correct PostgreSQL syntax is `start_time::date = 'YYYY-MM-DD'`. Do **NOT** use `ILIKE` for dates.\n**Query Construction Rules:**\n- Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n- Use `ILIKE` for **text-based, non-date** searching.\n- Always include `ORDER BY start_time ASC`.\n- Select all columns: `SELECT * FROM events`.\n**Security Rules:**\n- ONLY generate `SELECT` queries. For any other request, return: `SELECT 'Invalid request.';`\n**Response Format:**\n- Return ONLY the raw SQL query.\n**User Question:** "{user_query}" """
        
        try:
            # FIX: Use the synchronous generate_content method instead of async
            response = self.model.generate_content(prompt)
            sql_query = re.sub(r'```sql\n?|```', '', response.text).strip()
            
            if not sql_query.lstrip().upper().startswith("SELECT"):
                logger.warning(f"AI generated a non-SELECT query, blocking it: {sql_query}")
                return "SELECT 'Invalid request. Only SELECT queries are allowed.';"
            
            return sql_query
            
        except Exception as e:
            logger.error(f"SQL generation failed: {e}", exc_info=True)
            return "SELECT 'AI query generation failed. Please try rephrasing.';"

# --- Initialize Services ---
# This block runs once when the serverless function starts (cold start)
config = Config()
db_manager = NeonDBManager(config.NEON_DB_URL)
gemini_manager = GeminiManager(config.GEMINI_API_KEY)
TABLE_SCHEMA = ""

@app.on_event("startup")
def startup_event():
    global TABLE_SCHEMA
    try:
        # No need to run setup_database on every startup if it's already created.
        TABLE_SCHEMA = db_manager.get_table_schema()
        logger.info("API is ready. Database schema loaded.")
    except Exception as e:
        logger.error(f"Error during startup schema loading: {e}", exc_info=True)
        # The app can still run, but the AI might be less accurate without the schema.
        TABLE_SCHEMA = "Schema not available."

class QueryRequest(BaseModel):
    flow: str
    query: Optional[str] = None

# --- API Routes ---
# The path "/query" is relative to the file path "/api/index.py"
# So the public URL is /api/query
@app.post("/query")
async def handle_query(request: QueryRequest):
    if not TABLE_SCHEMA:
        raise HTTPException(status_code=503, detail="Service not ready: Schema not loaded.")
    
    flow, user_query = request.flow, request.query
    if not user_query:
        raise HTTPException(status_code=400, detail="Query text cannot be empty.")
    
    try:
        # FIX: Run the SQL generation in a thread pool to avoid event loop issues
        loop = asyncio.get_running_loop()
        sql_query = await loop.run_in_executor(
            None, 
            gemini_manager.generate_sql_query, 
            user_query, 
            flow, 
            TABLE_SCHEMA
        )
        
        logger.info(f"AI Generated SQL: {sql_query}")
        
        # Running the synchronous DB call in an async thread pool
        results = await loop.run_in_executor(None, db_manager.execute_query, sql_query)
        response_type = "detail" if flow == "get_event_details" else "list"
        
        return {"data": results, "type": response_type}
        
    except Exception as e:
        logger.error(f"Error processing query for flow '{flow}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")