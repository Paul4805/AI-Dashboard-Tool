from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Union
import sqlite3
from huggingface_hub import InferenceClient
from fastapi.middleware.cors import CORSMiddleware
import json
from openai import OpenAI
client = OpenAI(api_key="sk-aa05f2ae9f8c46cda0e9d5c16fdaed0c", base_url="https://api.deepseek.com")

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For testing, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


#client = InferenceClient(api_key="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")

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