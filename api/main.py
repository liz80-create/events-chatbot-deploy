# /api/main.py

# ==============================================================================
# Vercel Serverless Function for Events Chatbot
# ==============================================================================

import ssl
import certifi
import os
import json
import logging
import asyncio
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

# --- Required Libraries ---
import aiohttp
import psycopg2
import google.generativeai as genai
from psycopg2.extras import RealDictCursor, execute_batch
from dataclasses import dataclass
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Config:
    AIRTABLE_PAT: Optional[str] = os.getenv('AIRTABLE_PAT')
    AIRTABLE_BASE_ID: Optional[str] = os.getenv('AIRTABLE_BASE_ID')
    AIRTABLE_TABLE_NAME: Optional[str] = os.getenv('AIRTABLE_TABLE_NAME', 'Events')
    NEON_DB_URL: Optional[str] = os.getenv('NEON_DB_URL')
    GEMINI_API_KEY: Optional[str] = os.getenv('GEMINI_API_KEY')

# --- Service Classes ---
class AirtableClient:
    def __init__(self, pat_token: str, base_id: str, table_name: str):
        if not all([pat_token, base_id, table_name]): raise ValueError("Airtable client requires PAT, Base ID, and Table Name.")
        self.base_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        self.headers = {"Authorization": f"Bearer {pat_token}"}
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
    async def fetch_all_records(self) -> List[Dict[str, Any]]:
        all_records, offset = [], None
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                params = {"pageSize": 100}
                if offset: params["offset"] = offset
                try:
                    async with session.get(self.base_url, headers=self.headers, params=params) as response:
                        response.raise_for_status(); data = await response.json()
                        records = data.get("records", []); all_records.extend(records)
                        offset = data.get("offset")
                        if not offset: break
                except aiohttp.ClientError as e: logger.error(f"Airtable API request failed: {e}"); raise Exception(f"Airtable error: {e}")
        return all_records

class NeonDBManager:
    def __init__(self, connection_string: str):
        if not connection_string: raise ValueError("DB connection string required.")
        self.connection_string = connection_string
    def _get_connection(self):
        try: return psycopg2.connect(self.connection_string)
        except psycopg2.OperationalError as e: logger.error(f"DB connection failed: {e}"); raise
    def setup_database(self):
        q = "CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, airtable_id VARCHAR(255) UNIQUE NOT NULL, name TEXT, source VARCHAR(255), workstream VARCHAR(255), programme VARCHAR(255), type VARCHAR(100), start_time TIMESTAMPTZ, end_time TIMESTAMPTZ, linked_space VARCHAR(255), dependencies TEXT, owner VARCHAR(255), notes TEXT, tags TEXT, pmo_tracking VARCHAR(255), created_on DATE, updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP); CREATE INDEX IF NOT EXISTS idx_events_name ON events(name); CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time); CREATE INDEX IF NOT EXISTS idx_events_linked_space ON events(linked_space);"
        with self._get_connection() as c, c.cursor() as cur: cur.execute(q); c.commit()
    def sync_records(self, records: List[Dict[str, Any]]):
        q = "INSERT INTO events (airtable_id, name, source, workstream, programme, type, start_time, end_time, linked_space, dependencies, owner, notes, tags, pmo_tracking, created_on) VALUES (%(airtable_id)s, %(name)s, %(source)s, %(workstream)s, %(programme)s, %(type)s, %(start_time)s, %(end_time)s, %(linked_space)s, %(dependencies)s, %(owner)s, %(notes)s, %(tags)s, %(pmo_tracking)s, %(created_on)s) ON CONFLICT (airtable_id) DO UPDATE SET name = EXCLUDED.name, source = EXCLUDED.source, workstream = EXCLUDED.workstream, programme = EXCLUDED.programme, type = EXCLUDED.type, start_time = EXCLUDED.start_time, end_time = EXcluded.end_time, linked_space = EXCLUDED.linked_space, dependencies = EXCLUDED.dependencies, owner = EXCLUDED.owner, notes = EXCLUDED.notes, tags = EXCLUDED.tags, pmo_tracking = EXCLUDED.pmo_tracking, created_on = EXCLUDED.created_on, updated_at = CURRENT_TIMESTAMP;"
        processed = [self._process_record(r) for r in records if r.get('id')]
        if not processed: return
        with self._get_connection() as c, c.cursor() as cur: execute_batch(cur, q, processed); c.commit()
    def _process_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        fields = record.get('fields', {}); 
        def _parse_datetime(dt_str: Optional[str]) -> Optional[str]:
            if not dt_str: return None
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y %H:%M", "%Y-%m-%d"):
                try: return datetime.strptime(dt_str, fmt).isoformat()
                except (ValueError, TypeError): continue
            return None
        return {'airtable_id': record.get('id'),'name':fields.get('Name'),'source':fields.get('Source'),'workstream':fields.get('Workstream'),'programme':fields.get('Programme'),'type':fields.get('Type'),'start_time':_parse_datetime(fields.get('StartTime')),'end_time':_parse_datetime(fields.get('EndTime')),'linked_space':fields.get('LinkedSpace'),'dependencies':fields.get('Dependencies'),'owner':fields.get('Owner'),'notes':fields.get('Notes'),'tags':fields.get('Tags'),'pmo_tracking':fields.get('PMO Tracking'),'created_on':_parse_datetime(fields.get('Created On'))}
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor: cursor.execute(query, params); return [dict(row) for row in cursor.fetchall()]
    def get_table_schema(self) -> str:
        with self._get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'events' ORDER BY ordinal_position;")
            return "\n".join(f"- {col[0]} ({col[1]})" for col in cursor.fetchall())

class GeminiManager:
    """Uses Gemini to generate full SQL queries based on conversational flow."""
    def __init__(self, api_key: str):
        if not api_key: raise ValueError("Gemini API key required.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    async def generate_sql_query(self, user_query: str, flow: str, table_schema: str) -> str:
        """Generates a full SQL query using a flow-specific prompt."""

        if flow == "get_event_details":
            prompt = f"""

You are a PostgreSQL expert. The user has provided the following text to identify a single, specific event from a list they were shown: "{user_query}"
**Database Schema:**
{table_schema}
This text might be a messy combination of the event's name, location, and date.
**Your Task:**
1.  Intelligently identify the core **event name**.
2.  Intelligently identify the **date**, if one is mentioned in the text.
3.  Write a precise SQL query to `SELECT *` from the `events` table that matches these extracted criteria.
4.  If a date is found, add a condition like `AND start_time::date = 'YYYY-MM-DD'`.
5.  Use `ILIKE` for the name match to be case-insensitive.
6.  You **MUST** use `LIMIT 1` to ensure only one result is returned.
7.  Return ONLY the raw SQL query.

**Example 1:**
User Question: "AM volunteers shift 2 release on July 19, 2025"
SQL Output: SELECT * FROM events WHERE (name ILIKE '%AM volunteers shift 2 release%' OR programme ILIKE '%AM volunteers shift 2 release%' OR notes ILIKE '%AM volunteers shift 2 release%') AND start_time::date = '2025-07-19' ORDER BY start_time ASC;

"""
        else:
            prompt = f"""
You are an expert PostgreSQL query generator for a Festival Events database. Convert the user's question into a precise SQL query.

**Database Schema:**
{table_schema}

**ADVANCED SEARCH RULES:**
1.  **Keyword Logic (CRITICAL RULE):** For multi-word queries like "food fest" or "film screening", identify the core keywords (e.g., 'food', 'fest'). Each keyword should have its own search block (`(name ILIKE '%keyword%' OR programme ILIKE '%keyword%')`). You **MUST** connect these distinct keyword blocks with `AND` to ensure all terms are present in the results.
    * **Example for "food fest":** `WHERE (name ILIKE '%food%' OR programme ILIKE '%food%') AND (name ILIKE '%fest%' OR programme ILIKE '%festival%')`
    * **This ensures you find "food festivals", not just anything with "food" or anything with "fest".**
2.  **Date Handling (CRITICAL RULE):** If the user provides a date or asks about "today" or "tomorrow", you **MUST** search against the `start_time` column. The correct PostgreSQL syntax is `start_time::date = 'YYYY-MM-DD'`. Do **NOT** use `ILIKE` for dates.
    * **Example for a date query:** `SELECT * FROM events WHERE start_time::date = '2025-07-20' ORDER BY start_time ASC;`
3  **Date Handling**: If the user provides a date, you **MUST** search against the `start_time` column. The correct syntax is `start_time::date = 'YYYY-MM-DD'`. Do **NOT** use `ILIKE` for dates.
4.  **Split Locations**: For "SSH 3", generate `WHERE (linked_space ILIKE '%SSH%' AND linked_space ILIKE '%3%')`.


5.  **Broaden Search**: For "film screenings," create a broad `OR` search for `film` and `screenings` across `name`, `programme`, `notes`, etc.

6.  **Parentheses are Mandatory**: You MUST wrap `OR` conditions in parentheses when combining with `AND`. `WHERE (A OR B) AND C`.

7.  **Multi-Field Search**: If a specific entity like "Festival Programming" is mentioned, search for it across `workstream`, `programme`, `name`, `owner`.

**Query Construction Rules:**
-   Today's date is {datetime.now().strftime('%Y-%m-%d')}.
-   Use `ILIKE` for **text-based, non-date** searching.
-   Always include `ORDER BY start_time ASC`.
-   Select all columns: `SELECT * FROM events`.

**Security Rules:**
-   ONLY generate `SELECT` queries. For any other request, return: `SELECT 'Invalid request.';`

**Response Format:**
-   Return ONLY the raw SQL query.

**User Question:** "{user_query}"
"""
        try:
            response = await self.model.generate_content_async(prompt)
            sql_query = re.sub(r'```sql\n?|```', '', response.text).strip()
            
            if not sql_query.lstrip().upper().startswith("SELECT"):
                logger.warning(f"AI generated a non-SELECT query, blocking it: {sql_query}")
                return "SELECT 'Invalid request. Only SELECT queries are allowed.';"

            return sql_query
        except Exception as e:
            logger.error(f"SQL generation failed: {e}")
            return "SELECT 'AI query generation failed. Please try rephrasing.';"

# --- FastAPI Application Setup ---
app = FastAPI()
config = Config()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
db_manager = NeonDBManager(config.NEON_DB_URL)
gemini_manager = GeminiManager(config.GEMINI_API_KEY)
TABLE_SCHEMA = ""

class QueryRequest(BaseModel):
    flow: str; query: Optional[str] = None

class QueryRequest(BaseModel):
    flow: str; query: Optional[str] = None

# This lifespan function will run the setup code when the serverless function starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    global TABLE_SCHEMA
    db_manager.setup_database()
    TABLE_SCHEMA = db_manager.get_table_schema()
    logger.info("API is ready. Schema loaded.")
    yield
    # No cleanup needed for this app

app.router.lifespan_context = lifespan

@app.post("/")
async def handle_query(request: QueryRequest):
    if not request.query: raise HTTPException(status_code=400, detail="Query text cannot be empty.")
    try:
        sql_query = await gemini_manager.generate_sql_query(request.query, request.flow, TABLE_SCHEMA)
        logger.info(f"AI Generated SQL: {sql_query}")
        results = db_manager.execute_query(sql_query)
        response_type = "detail" if request.flow == "get_event_details" else "list"
        return {"data": results, "type": response_type}
    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

@app.post("/api/sync")
async def sync_data():
    try:
        airtable_client = AirtableClient(config.AIRTABLE_PAT, config.AIRTABLE_BASE_ID, config.AIRTABLE_TABLE_NAME)
        records = await airtable_client.fetch_all_records()
        db_manager.sync_records(records)
        return {"message": f"Synced {len(records)} records."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))