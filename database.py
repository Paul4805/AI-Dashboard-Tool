import sqlite3
from contextlib import contextmanager
import os
from psycopg2 import pool as pg_pool
import psycopg2
import mysql.connector
from pymongo import MongoClient

DB_PATH = "secure_app.db"

@contextmanager
def sqlite_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    if not os.path.exists(DB_PATH):
        with sqlite_connection() as conn:
            cursor = conn.cursor()
            # Create users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                email TEXT UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Create sessions table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """)

            # Create user_prompts table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """)

            # Create user_history table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """)

            conn.commit()

def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

# PostgreSQL connection test
def test_postgresql_connection(host, port, username, password, database=None):
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database if database else "postgres",
            connect_timeout=5
        )
        conn.close()
        return True
    except Exception as e:
        raise e

# MySQL connection test
def test_mysql_connection(host, port, username, password, database=None):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database if database else None,
            connection_timeout=5
        )
        conn.close()
        return True
    except Exception as e:
        raise e

# MongoDB connection test
def test_mongodb_connection(host, port, username, password, database=None, auth_source="admin"):
    try:
        if database:
            uri = f"mongodb://{username}:{password}@{host}:{port}/{database}?authSource={auth_source}"
        else:
            uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource={auth_source}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.server_info()  # Forces a call to the server
        client.close()
        return True
    except Exception as e:
        raise e

# List PostgreSQL databases
def list_postgresql_databases(host, port, username, password):
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database="postgres",
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT datname FROM pg_database
            WHERE datistemplate = false
            ORDER BY datname
        """)
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        raise e

# List MySQL databases
def list_mysql_databases(host, port, username, password):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            connection_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        raise e

# List MongoDB databases
def list_mongodb_databases(host, port, username, password, auth_source="admin"):
    try:
        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource={auth_source}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        dbs = client.list_database_names()
        client.close()
        return dbs
    except Exception as e:
        raise e

# List PostgreSQL tables
def list_postgresql_tables(host, port, username, password, database):
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database,
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        raise e

# List MySQL tables
def list_mysql_tables(host, port, username, password, database):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database,
            connection_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        raise e

# List MongoDB collections
def list_mongodb_collections(host, port, username, password, database, auth_source="admin"):
    try:
        uri = f"mongodb://{username}:{password}@{host}:{port}/{database}?authSource={auth_source}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[database]
        collections = db.list_collection_names()
        client.close()
        return collections
    except Exception as e:
        raise e

# Fetch PostgreSQL table data with pagination
def fetch_postgresql_table_data(host, port, username, password, database, table, page=1, page_size=100):
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database,
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        total_rows = cursor.fetchone()[0]
        offset = (page - 1) * page_size
        cursor.execute(f"SELECT * FROM {table} LIMIT {page_size} OFFSET {offset}")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()
        data = [dict(zip(columns, row)) for row in rows]
        return {"data": data, "total_rows": total_rows}
    except Exception as e:
        raise e

# Fetch MySQL table data with pagination
def fetch_mysql_table_data(host, port, username, password, database, table, page=1, page_size=100):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database=database,
            connection_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        total_rows = cursor.fetchone()[0]
        offset = (page - 1) * page_size
        cursor.execute(f"SELECT * FROM `{table}` LIMIT {offset}, {page_size}")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()
        data = [dict(zip(columns, row)) for row in rows]
        return {"data": data, "total_rows": total_rows}
    except Exception as e:
        raise e

# Fetch MongoDB collection data with pagination
def fetch_mongodb_collection_data(host, port, username, password, database, collection, auth_source="admin", page=1, page_size=100):
    try:
        uri = f"mongodb://{username}:{password}@{host}:{port}/{database}?authSource={auth_source}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[database]
        coll = db[collection]
        total_rows = coll.count_documents({})
        skip = (page - 1) * page_size
        cursor = coll.find().skip(skip).limit(page_size)
        data = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])  # Convert ObjectId to string
            data.append(doc)
        client.close()
        return {"data": data, "total_rows": total_rows}
    except Exception as e:
        raise e

# Delete PostgreSQL database
def delete_postgresql_database(host, port, username, password, database):
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            database="postgres",
            connect_timeout=5
        )
        conn.autocommit = True
        cursor = conn.cursor()
        # Terminate connections to the database
        cursor.execute(f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
        """, (database,))
        # Drop the database
        cursor.execute(f"DROP DATABASE IF EXISTS {database}")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        raise e

# Delete MySQL database
def delete_mysql_database(host, port, username, password, database):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port),
            user=username,
            password=password,
            connection_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        raise e

# Delete MongoDB database
def delete_mongodb_database(host, port, username, password, database, auth_source="admin"):
    try:
        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource={auth_source}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[database]
        db.drop_database(database)
        client.close()
        return True
    except Exception as e:
        raise e

if __name__ == "__main__":
    print("Initializing SQLite database...")
    init_db()
    print("Database initialized.")
