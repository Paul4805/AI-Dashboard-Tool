from fastapi import FastAPI, Request, Form, HTTPException, status 
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from datetime import datetime, timedelta
import secrets
import sqlite3
from database import sqlite_connection
from openai import OpenAI
import json 
import pymongo
from pydantic import BaseModel
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import FastAPI, UploadFile, File
import whisper
import tempfile
import shutil
import os
import torch
import psycopg2
import psycopg2.extras
from fastapi import Request
import mysql.connector as mysql

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace "*" with specific URLs to limit access
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
)
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from database import (
    test_postgresql_connection,
    test_mysql_connection,
    test_mongodb_connection,
    list_postgresql_databases,
    list_mysql_databases,
    list_mongodb_databases,
    list_postgresql_tables,
    list_mysql_tables,
    list_mongodb_collections,
    fetch_postgresql_table_data,
    fetch_mysql_table_data,
    fetch_mongodb_collection_data,
    delete_postgresql_database,
    delete_mysql_database,
    delete_mongodb_database
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_EXPIRE_MINUTES = 30

# Password hashing
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Session management
def create_session_token():
    return secrets.token_urlsafe(32)

def create_session(user_id: int):
    session_token = create_session_token()
    expires_at = datetime.now() + timedelta(minutes=SESSION_EXPIRE_MINUTES)
    
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_token, user_id, expires_at.isoformat())
        )
        conn.commit()
    return session_token

def get_user_from_session(session_token: str):
    if not session_token:
        return None
    
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT users.id, users.username FROM sessions "
            "JOIN users ON users.id = sessions.user_id "
            "WHERE session_id = ? AND expires_at > datetime('now')",
            (session_token,)
        )
        session = cursor.fetchone()
        if session:
            return {"id": session[0], "username": session[1]}
        else:
            return None

# Authentication dependencies
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    print(get_user_from_session(session_token) if session_token else None)
    return get_user_from_session(session_token) if session_token else None

def login_required(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    print(user)
    return user

# Routes
@app.get("/dashboard", response_class=HTMLResponse)
async def home(request: Request, user: dict = Depends(login_required)):
    # Verify session again to ensure it's valid
    session_token = request.cookies.get("session_token")
    if not session_token or not get_user_from_session(session_token):
        response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("session_token")
        return response
    
    # Fetch user email for display
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE id = ?", (user["id"],))
        user_email_row = cursor.fetchone()
    user_email = user_email_row[0] if user_email_row else ""
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": user["username"],
        "email": user_email
    })

@app.get("/data", response_class=HTMLResponse)
async def data_page(request: Request, user: dict = Depends(login_required)):
    # Verify session again to ensure it's valid
    session_token = request.cookies.get("session_token")
    if not session_token or not get_user_from_session(session_token):
        response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("session_token")
        return response
    
    return templates.TemplateResponse("data.html", {
        "request": request,
        "username": user["username"]
    })

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    session_token = request.cookies.get("session_token")
    user = get_user_from_session(session_token) if session_token else None
    
    if user:
        # User is properly authenticated - show dashboard
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    else:
        # Show public landing page or redirect to login
        return RedirectResponse("/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
    
    if not user or not verify_password(password, user[1]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })
    
    session_token = create_session(user[0])
    
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=SESSION_EXPIRE_MINUTES * 60,
        samesite="None",
        path="/",  # Important: set cookie path to root
        secure=True  # Set to True in production with HTTPS
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token:
        with sqlite_connection() as conn:
            cursor= conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_token,))
            conn.commit()
    
    response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

# Route to render history page
@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, user: dict = Depends(login_required)):
    return templates.TemplateResponse("history.html", {
        "request": request,
        "username": user["username"]
    })

from fastapi import Form

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, user: dict = Depends(login_required)):
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, first_name, last_name, email FROM users WHERE id = ?",
            (user["id"],)
        )
        user_data = cursor.fetchone()
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": {
            "username": user_data[0],
            "first_name": user_data[1],
            "last_name": user_data[2],
            "email": user_data[3]
        },
        "username": user["username"]
    })

@app.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    user: dict = Depends(login_required)
):
    error = None
    message = None
    with sqlite_connection() as conn:
        cursor = conn.cursor()
        # Check if email is unique if changed
        cursor.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?",
            (email, user["id"])
        )
        existing = cursor.fetchone()
        if existing:
            error = "Email is already in use by another account."
        else:
            try:
                cursor.execute(
                    """
                    UPDATE users
                    SET first_name = ?, last_name = ?, email = ?
                    WHERE id = ?
                    """,
                    (first_name, last_name, email, user["id"])
                )
                conn.commit()
                message = "Profile updated successfully."
            except Exception as e:
                conn.rollback()
                error = f"Failed to update profile: {str(e)}"
        # Fetch updated user data for rendering
        cursor.execute(
            "SELECT username, first_name, last_name, email FROM users WHERE id = ?",
            (user["id"],)
        )
        user_data = cursor.fetchone()
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": {
            "username": user_data[0],
            "first_name": user_data[1],
            "last_name": user_data[2],
            "email": user_data[3]
        },
        "username": user["username"],
        "error": error,
        "message": message
    })

# API endpoint to get user history with optional filters
@app.get("/api/history")
async def get_user_history(request: Request, user: dict = Depends(login_required)):
    user_id = user["id"]
    days = request.query_params.get("days")
    action_type = request.query_params.get("action_type")

    query = "SELECT id, action_type, description, details, created_at FROM user_history WHERE user_id = ?"
    params = [user_id]

    if days and days.isdigit() and int(days) > 0:
        query += " AND created_at >= datetime('now', ?)"
        params.append(f"-{days} days")

    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)

    query += " ORDER BY created_at DESC LIMIT 100"

    with sqlite_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

    history = []
    for row in rows:
        history.append({
            "id": row[0],
            "action_type": row[1],
            "description": row[2],
            "details": row[3],
            "created_at": row[4]
        })

    return history

@app.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

from fastapi import Form
from fastapi.responses import RedirectResponse
from fastapi import status

@app.post("/signup")
async def signup(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    if password != confirm_password:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Passwords do not match"
        })

    hashed_password = get_password_hash(password)
    
    try:
        with sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (first_name, last_name, email, username, password_hash) VALUES (?, ?, ?, ?, ?)",
                (first_name, last_name, email, username, hashed_password)
            )
            conn.commit()
    except sqlite3.IntegrityError as e:
        if 'unique constraint' in str(e).lower() or 'unique failed' in str(e).lower():
            error_msg = "Username or email already exists"
            return templates.TemplateResponse("signup.html", {
                "request": request,
                "error": error_msg
            })
        else:
            raise  # Re-raise if it's a different kind of integrity error

    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)

#client = InferenceClient(api_key="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")
client = OpenAI(api_key="sk-aa05f2ae9f8c46cda0e9d5c16fdaed0c", base_url="https://api.deepseek.com")
model = whisper.load_model("medium", device="cuda" if torch.cuda.is_available() else "cpu")
# Chart templates
pie_json = '''"chart_type": "pie", "title": "Chart Title", "labels": ["Label1", "Label2"], "values": [10, 20]'''
bar_line_json = '''"chart_type": "bar", "title": "Chart Title", "x_axis": {"label": "X-axis Label", "values": ["X1", "X2"]}, "y_axis": {"label": "Y-axis Label", "values": [100, 200]}'''

# Input model
class UserQuery(BaseModel):
    question: str
    format: str  # e.g., "bar graph", "pie chart", "line graph", "full ai report"


# Get database schema
def get_schema_description_farsi():
    conn = sqlite3.connect("example.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    schema_description = ""
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        columns = cursor.fetchall()
        schema_description += f"Table `{table}` has columns:\n"
        for col in columns:
            schema_description += f"  - `{col[1]}` ({col[2]})\n"
        schema_description += "\n"
    conn.close()
    return schema_description

def get_schema_description_english():
    conn = sqlite3.connect("example_english.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    schema_description = ""
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        columns = cursor.fetchall()
        schema_description += f"Table `{table}` has columns:\n"
        for col in columns:
            schema_description += f"  - `{col[1]}` ({col[2]})\n"
        schema_description += "\n"
    conn.close()
    return schema_description


import re

def clean_sql(raw_sql: str, as_single_line: bool = False) -> str:
    """
    Cleans an LLM-generated SQL string by removing markdown, explanations, and formatting.

    Args:
        raw_sql (str): Raw output from LLM containing SQL and possibly descriptions.
        as_single_line (bool): Whether to return the query in one line.

    Returns:
        str: Cleaned SQL query.
    """
    # Remove markdown
    cleaned = raw_sql.replace("```sql", "").replace("```", "").strip()

    # Split into lines and find where actual SQL starts (e.g., SELECT, WITH, INSERT, etc.)
    lines = cleaned.splitlines()
    sql_start_keywords = ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP")
    
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(sql_start_keywords):
            sql_lines = lines[i:]
            break
    else:
        sql_lines = lines  # fallback if no keyword found

    cleaned_sql = "\n".join(sql_lines).strip()

    if as_single_line:
        cleaned_sql = " ".join(cleaned_sql.split())

    return cleaned_sql


def generate_sql_english(user_prompt, schema_description):
    """
    Converts natural language questions to raw SQL queries using LLM via RunPod.
    
    Args:
        user_prompt (str): User's question in plain English.
        schema_description (str): Database table/column schema.

    Returns:
        str: Cleaned raw SQL query string (no explanation, no formatting).
    """
    # Construct a strict prompt
    prompt = f"""You are an AI that outputs only SQL queries.

Given the following database schema:
{schema_description}

Translate the following question into a syntactically correct SQL query.
IMPORTANT: Return ONLY the SQL query. Do NOT include comments, explanations, markdown, any formatting or the msg "Here's the SQL query to retrieve......" .

Question:
{user_prompt}
"""

    # Call the model (DeepSeek/Llama etc.)
    sqlquery = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    # Extract only SQL from response
    #if sqlsquery startswith("Here's the SQL query to retrieve") remove content till /n
    sqlquery= clean_sql(sqlquery.choices[0].message.content.strip())
    return sqlquery
    #return sqlquery.choices[0].message.content.strip().removeprefix("```sql").removesuffix("```").strip()


def generate_analysis(user_prompt, results):
    """
    Generates detailed data analysis from query results using Llama 3 on RunPod
    
    Args:
        user_prompt: Original user question/analysis request
        results: Data results to analyze (can be dict, list, or string)
        
    Returns:
        str: Detailed analysis of the data
    """
    # Construct the analysis prompt
    prompt = f"""You are a senior data analyst. Provide a comprehensive analysis of these results.
    
**User Question**: {user_prompt}

**Data Results**:
{str(results)}

Include in your response:
1. Key findings and patterns
2. Notable outliers or anomalies  
3. Business implications
4. Recommendations for next steps
5. Limitations of the data

Format your response with clear section headings.

please give the output in the language of the userprompt"""
    
    # Call the RunPod API
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""{prompt}"""
        }]
    )
    return response.choices[0].message.content.strip()


def generate_visualization(user_prompt, results, chart_format):
    """
    Generates visualization specifications using predefined JSON templates
    
    Args:
        user_prompt: The visualization request
        results: Data to visualize
        chart_format: Chart type ('pie', 'bar', 'line', etc.)
        
    Returns:
        str: Valid JSON configuration for the chart
    """
    # Select the appropriate template
    template = pie_json if chart_format.lower() == "pie chart" else bar_line_json
    
    prompt = f"""
You are a chart generation assistant.
Question: {user_prompt}
Chart type: {chart_format}
Data: {results}

Use this JSON template:
{template}

Instructions:
1. Fill in the template with the provided data
2. Return ONLY valid JSON
3. No explanations or additional text
4. Include appropriate colors if the template has color fields
5. Make labels descriptive

please use chart labels in the language of the userprompt"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""
{prompt}
"""
        }]
    )
    return response.choices[0].message.content.strip()



def generate(user_query: UserQuery):
    schema = get_schema_description_english()
    print(f"Schema for English: {schema}")  # Debugging output
    print(f"User Query: {user_query.question}, Format: {user_query.format}")  # Debugging output
    try:
        sql = generate_sql_english(user_query.question, schema)
        #if sql.startswith(""):
        conn = sqlite3.connect("example_english.db")
        cursor = conn.cursor()
        cursor.execute(sql)
        results = cursor.fetchall()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL Error: {e}")
    try:
        if user_query.format == "full ai report":
            analysis = generate_analysis(user_query.question, results)
            return {"type": "report", "analysis": analysis}
        else:
            chart_str = generate_visualization(user_query.question, results, user_query.format)
            # Attempt to parse valid JSON from LLM output
            chart_json = json.loads(chart_str.strip().strip("```json").strip("```").strip())
            return {"type": "chart", "data": chart_json}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing Error: {e}")
def get_user_id(user: dict = Depends(get_current_user)):
    return user["id"]

@app.post("/ask")
async def ask_question(request: Request):
    data = await request.json()
    question = data.get("question", "")
    format_type = data.get("format", "")
    connection = data.get("connection", {})
    
    # Extract connection details
    db_type = connection.get("dbType", "")
    host = connection.get("host", "localhost")
    port = connection.get("port", "5432")
    database = connection.get("database", "")
    username = connection.get("username", "")
    password = connection.get("password", "")
    
    print(f"Using database connection: {db_type} - {host}:{port}/{database}")
    
    try:
        # Store user query history with the exact format you want
        try:
            user = get_current_user(request)
            if user:
                history_details = {
                    "format": format_type,
                    "question": question,
                    "connection": {
                        "host": host,
                        "port": port,
                        "dbType": db_type,
                        "database": database,
                        "username": username
                    }
                }
                
                with sqlite_connection() as history_conn:
                    history_cursor = history_conn.cursor()
                    history_cursor.execute(
                        "INSERT INTO user_history (user_id, action_type, description, details) VALUES (?, ?, ?, ?)",
                        (user["id"], "query", question, json.dumps(history_details))
                    )
                    history_conn.commit()
        except Exception as history_exc:
            print(f"Failed to store user history: {history_exc}")
        
        # Get database schema
        schema_description = ""
        
        if db_type == "postgresql":
            import psycopg2
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=username,
                password=password
            )
            cursor = conn.cursor()
            
            # Get schema information
            cursor.execute("""
                SELECT table_name, column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
            """)
            
            tables = {}
            for row in cursor.fetchall():
                table_name, column_name, data_type = row
                if table_name not in tables:
                    tables[table_name] = []
                tables[table_name].append(f"{column_name} ({data_type})")
            
            # Format schema description
            for table_name, columns in tables.items():
                schema_description += f"Table `{table_name}` has columns:\n"
                for column in columns:
                    schema_description += f"  - `{column}`\n"
                schema_description += "\n"
            
        elif db_type == "mysql":
            import mysql.connector
            conn = mysql.connector.connect(
                host=host,
                port=port,
                database=database,
                user=username,
                password=password
            )
            cursor = conn.cursor()
            
            # Get schema information
            cursor.execute("""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """, (database,))
            
            tables = {}
            for row in cursor.fetchall():
                table_name, column_name, data_type = row
                if table_name not in tables:
                    tables[table_name] = []
                tables[table_name].append(f"{column_name} ({data_type})")
            
            # Format schema description
            for table_name, columns in tables.items():
                schema_description += f"Table `{table_name}` has columns:\n"
                for column in columns:
                    schema_description += f"  - `{column}`\n"
                schema_description += "\n"
                
        elif db_type == "mongodb":
            from pymongo import MongoClient
            client = MongoClient(
                host=host,
                port=int(port),
                username=username,
                password=password,
                authSource=connection.get("authSource", "admin")
            )
            db = client[database]
            
            # Get collection names
            collection_names = db.list_collection_names()
            
            # For each collection, get a sample document to infer schema
            for collection_name in collection_names:
                schema_description += f"Collection `{collection_name}` has fields:\n"
                sample = db[collection_name].find_one()
                if sample:
                    for field, value in sample.items():
                        data_type = type(value).__name__
                        schema_description += f"  - `{field}` ({data_type})\n"
                schema_description += "\n"
        else:
            return {"error": f"Unsupported database type: {db_type}"}
        
        print(f"Schema description: {schema_description}")
        
        # Generate SQL query from the question
        sql_query = generate_sql_english(question, schema_description)
        print(f"Generated SQL query: {sql_query}")
        
        # Execute the query
        results = []
        if db_type == "postgresql" or db_type == "mysql":
            cursor.execute(sql_query)
            columns = [desc[0] for desc in cursor.description]
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
        elif db_type == "mongodb":
            # For MongoDB, we'd need to convert SQL to MongoDB query
            # This is a simplified approach
            collection_name = sql_query.split("FROM")[1].split()[0].strip()
            collection = db[collection_name]
            for doc in collection.find().limit(100):
                results.append(doc)
        
        # Generate visualization or report
        if format_type == "full ai report":
            analysis = generate_analysis(question, results)
            return {
                "type": "report",
                "analysis": analysis
            }
        else:
            chart_json = generate_visualization(question, results, format_type)
            # Parse the JSON string to a dictionary
            try:
                chart_data = json.loads(chart_json)
            except:
                # If parsing fails, use the string as is
                chart_data = {
                    "chart_type": format_type,
                    "title": question,
                    "error": "Could not parse chart data",
                    "raw_data": chart_json
                }
            
            return {
                "type": "chart",
                "data": chart_data
            }
            
    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        print(f"Error: {str(e)}\n{traceback_str}")
        return {"error": str(e), "traceback": traceback_str}

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
            shutil.copyfileobj(file.file, temp_audio)
            temp_audio_path = temp_audio.name

        # Transcribe using Whisper
        result = model.transcribe(temp_audio_path)
        transcription = result["text"]

        # Clean up
        os.remove(temp_audio_path)

        return {"transcription": transcription.strip()}

    except Exception as e:
        return {"error": str(e)}

@app.get("/databases")
async def get_databases():
    # This endpoint will list databases based on query parameters
    db_type = None
    host = None
    port = None
    username = None
    password = None
    auth_source = "admin"

    # Extract query parameters
    from fastapi import Request
    async def inner(request: Request):
        nonlocal db_type, host, port, username, password, auth_source
        params = request.query_params
        db_type = params.get("dbType")
        host = params.get("host")
        port = params.get("port")
        username = params.get("username")
        password = params.get("password")
        auth_source = params.get("authSource", "admin")

        if not db_type or not host or not port:
            return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, and port are required"})

        try:
            if db_type == "postgresql":
                databases = list_postgresql_databases(host, port, username, password)
            elif db_type == "mysql":
                databases = list_mysql_databases(host, port, username, password)
            elif db_type == "mongodb":
                databases = list_mongodb_databases(host, port, username, password, auth_source)
            else:
                return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
            return {"success": True, "databases": databases}
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

    return await inner(Request)

@app.post("/api/test-connection")
async def test_connection(payload: dict = Body(...)):
    db_type = payload.get("dbType")
    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    database = payload.get("database")
    auth_source = payload.get("authSource", "admin")

    if not db_type or not host or not port:
        return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, and port are required"})

    try:
        if db_type == "postgresql":
            result = test_postgresql_connection(host, port, username, password, database)
        elif db_type == "mysql":
            result = test_mysql_connection(host, port, username, password, database)
        elif db_type == "mongodb":
            result = test_mongodb_connection(host, port, username, password, database, auth_source)
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
        return {"success": True, "message": f"{db_type} connection successful"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/databases")
async def get_databases_post(payload: dict = Body(...)):
    db_type = payload.get("dbType")
    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    auth_source = payload.get("authSource", "admin")

    if not db_type or not host or not port:
        return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, and port are required"})

    try:
        if db_type == "postgresql":
            databases = list_postgresql_databases(host, port, username, password)
        elif db_type == "mysql":
            databases = list_mysql_databases(host, port, username, password)
        elif db_type == "mongodb":
            databases = list_mongodb_databases(host, port, username, password, auth_source)
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
        return {"success": True, "databases": databases}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/tables")
async def get_tables_post(payload: dict = Body(...)):
    db_type = payload.get("dbType")
    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    database = payload.get("database")
    auth_source = payload.get("authSource", "admin")

    if not db_type or not host or not port or not database:
        return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, port, and database are required"})

    try:
        if db_type == "postgresql":
            tables = list_postgresql_tables(host, port, username, password, database)
        elif db_type == "mysql":
            tables = list_mysql_tables(host, port, username, password, database)
        elif db_type == "mongodb":
            tables = list_mongodb_collections(host, port, username, password, database, auth_source)
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
        return {"success": True, "tables": tables}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/table-data")
async def get_table_data_post(payload: dict = Body(...)):
    db_type = payload.get("dbType")
    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    database = payload.get("database")
    table = payload.get("table")
    auth_source = payload.get("authSource", "admin")
    page = payload.get("page", 1)
    page_size = payload.get("pageSize", 100)

    if not db_type or not host or not port or not database or not table:
        return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, port, database, and table are required"})

    try:
        if db_type == "postgresql":
            result = fetch_postgresql_table_data(host, port, username, password, database, table, page, page_size)
        elif db_type == "mysql":
            result = fetch_mysql_table_data(host, port, username, password, database, table, page, page_size)
        elif db_type == "mongodb":
            result = fetch_mongodb_collection_data(host, port, username, password, database, table, auth_source, page, page_size)
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
        return {"success": True, "data": result["data"], "totalRows": result["total_rows"], "page": page, "pageSize": page_size, "totalPages": (result["total_rows"] + page_size - 1) // page_size}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/delete-database")
async def delete_database_post(payload: dict = Body(...)):
    db_type = payload.get("dbType")
    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    database = payload.get("database")
    auth_source = payload.get("authSource", "admin")

    if not db_type or not host or not port or not database:
        return JSONResponse(status_code=400, content={"success": False, "message": "dbType, host, port, and database are required"})

    try:
        if db_type == "postgresql":
            result = delete_postgresql_database(host, port, username, password, database)
        elif db_type == "mysql":
            result = delete_mysql_database(host, port, username, password, database)
        elif db_type == "mongodb":
            result = delete_mongodb_database(host, port, username, password, database, auth_source)
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Unsupported database type"})
        return {"success": True, "message": f"{db_type} database {database} deleted successfully"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/create-connection")
async def create_connection_post(payload: dict = Body(...)):
    # This endpoint can reuse the test connection logic
    return await test_connection(payload)

