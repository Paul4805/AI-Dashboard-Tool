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
from pydantic import BaseModel
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace "*" with specific URLs to limit access
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
)

templates = Jinja2Templates(directory="templates")

# Security config
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
        # Remove any existing sessions for this user
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        # Create new session
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_token, user_id, expires_at.isoformat())
        )
        conn.commit()
    return session_token

def get_user_from_session(session_token: str):
    if not session_token:
        return None
    
    with sqlite_connection() as conn:
        # Get valid session with user data
        session = conn.execute(
            "SELECT users.id, users.username FROM sessions "
            "JOIN users ON users.id = sessions.user_id "
            "WHERE session_id = ? AND expires_at > datetime('now')",
            (session_token,)
        ).fetchone()
        
        return dict(session) if session else None

# Authentication dependencies
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    return get_user_from_session(session_token) if session_token else None

def login_required(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return user

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user: dict = Depends(login_required)):
    # Verify session again to ensure it's valid
    session_token = request.cookies.get("session_token")
    if not session_token or not get_user_from_session(session_token):
        response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("session_token")
        return response
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": user["username"]
    })

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with sqlite_connection() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
    
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })
    
    session_token = create_session(user["id"])
    
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=SESSION_EXPIRE_MINUTES * 60,
        samesite="Lax",
        path="/",  # Important: set cookie path to root
        secure=False  # Set to True in production with HTTPS
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token:
        with sqlite_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_token,))
            conn.commit()
    
    response = RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

@app.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/signup")
async def signup(request: Request, username: str = Form(...), password: str = Form(...)):
    hashed_password = get_password_hash(password)
    
    try:
        with sqlite_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hashed_password)
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Username already exists"
        })
    
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)

#client = InferenceClient(api_key="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")
client = OpenAI(api_key="sk-aa05f2ae9f8c46cda0e9d5c16fdaed0c", base_url="https://api.deepseek.com")
# Chart templates
pie_json = '''"chart_type": "pie", "title": "عنوان نمودار", "labels": ["برچسب1", "برچسب2"], "values": [10, 20]'''
bar_line_json = '''"chart_type": "bar", "title": "عنوان نمودار", "x_axis": {"label": "برچسب محور x", "values": ["X1", "X2"]}, "y_axis": {"label": "برچسب محور y", "values": [100, 200]}'''

# Input model
class UserQuery(BaseModel):
    question: str
    format: str  # e.g., "bar graph", "pie chart", "line graph", "full ai report"

# Get database schema
def get_schema_description():
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

# Generate SQL
def generate_sql(user_prompt, schema_description):
    sqlquery = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""شما یک دستیار تبدیل سوالات فارسی به کوئری SQL هستید.
از ساختار جداول زیر استفاده کنید:
{schema_description}
فقط کوئری SQL را به عنوان پاسخ برگردان.
سوال: {user_prompt}
"""
        }]
    )
    return sqlquery.choices[0].message.content.strip().replace("```sql", "").replace("```", "").strip()

# Generate AI Report
def generate_analysis(user_prompt, results):
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""شما یک دستیار تحلیل داده هستید.
سوال کاربر: {user_prompt}
نتایج استخراج شده: {results}
لطفاً تحلیل کامل و دقیق از داده‌ها ارائه دهید."""
        }]
    )
    return response.choices[0].message.content.strip()

# Generate chart JSON
def generate_visualization(user_prompt, results, format):
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""
شما یک دستیار تولید نمودار هستید.
سوال: {user_prompt}
نوع نمودار: {format}
داده‌ها: {results}
لطفاً پاسخ را فقط در قالب JSON معتبر برگردانید.
{{ {pie_json if format == "pie chart" else bar_line_json} }}
"""
        }]
    )
    return response.choices[0].message.content.strip()

@app.post("/ask")
def ask_question(user_query: UserQuery):
    schema = get_schema_description()
    try:
        sql = generate_sql(user_query.question, schema)
        conn = sqlite3.connect("example.db")
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
