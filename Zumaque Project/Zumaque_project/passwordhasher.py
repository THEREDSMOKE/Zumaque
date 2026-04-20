import os
from dotenv import load_dotenv
import pyodbc
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv(override=True)
SECRET_KEY = os.getenv('SECRET_KEY')

def test_password_hashing():
    password = input("Enter a password to hash: ")
    hashed_password = generate_password_hash(password)
    print(f"Hashed password: {hashed_password}")

  # Función para establecer conexión con SQL Server
def get_db_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')}"
    )
    return pyodbc.connect(conn_str)

def hash_password(password):
    return generate_password_hash(password)

def insert_user(username, password):
    try:
        hashed_password = hash_password(password)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuario (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error inserting user: {e}")

if __name__ == "__main__":
    username = input("Enter a username: ").strip()
    password = input("Enter a password to hash and save: ").strip()
    if not username or not password:
        print("Username and password are required.")
    else:
        insert_user(username, password)
        print("User inserted successfully.")
    

   