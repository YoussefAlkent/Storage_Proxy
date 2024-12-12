import os
import logging
import json
import mysql.connector
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from passlib.hash import bcrypt
from dotenv import load_dotenv
from kafka import KafkaProducer
from kafka.errors import KafkaError

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")  # MySQL connection string
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")

# FastAPI app
app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka Producer Initialization
def init_kafka():
    try:
        return KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            acks='all',
            retries=3
        )
    except KafkaError as e:
        logger.error(f"Kafka initialization error: {e}")
        return None

def send_to_kafka(producer, topic, message):
    if not producer:
        return
    try:
        future = producer.send(topic, message)
        future.get(timeout=60)
    except KafkaError as e:
        logger.error(f"Kafka send error: {e}")

# Models
class User(BaseModel):
    id: int
    username: str
    password_hash: str

class Chat(BaseModel):
    id: int
    user_id: int
    prompt: str
    answer: str

# Pydantic Schemas
class UserCreate(BaseModel):
    username: str
    password: str

class ChatCreate(BaseModel):
    user_id: int
    prompt: str
    answer: str

# Dependency
def get_db():
    db = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )
    return db

# Function to ensure the necessary tables exist
def create_tables_if_not_exists(db: mysql.connector.MySQLConnection):
    cursor = db.cursor()
    try:
        # Create users table if it does not exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL
        );
        """)

        # Create chats table if it does not exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            prompt TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)

        db.commit()
        logger.info("Tables created or already exist.")
    except mysql.connector.Error as err:
        logger.error(f"Error creating tables: {err}")
    finally:
        cursor.close()

# Routes
@app.post("/storage/create_user")
def create_user(user: UserCreate, background_tasks: BackgroundTasks, db: mysql.connector.MySQLConnection = Depends(get_db)):
    hashed_password = bcrypt.hash(user.password)
    cursor = db.cursor()

    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (user.username, hashed_password))
        db.commit()
        background_tasks.add_task(send_to_kafka, app.state.kafka_producer, 'user_events', {
            'event': 'create_user',
            'username': user.username
        })
        return {"message": "User created successfully"}
    except mysql.connector.Error as err:
        logger.error(f"Error: {err}")
        raise HTTPException(status_code=500, detail="Error creating user")
    finally:
        cursor.close()

@app.post("/storage/login")
def login(user: UserCreate, db: mysql.connector.MySQLConnection = Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
        db_user = cursor.fetchone()
        if not db_user or not bcrypt.verify(user.password, db_user['password_hash']):
            raise HTTPException(status_code=400, detail="Invalid credentials")
        return {"message": "Login successful"}
    except mysql.connector.Error as err:
        logger.error(f"Error: {err}")
        raise HTTPException(status_code=500, detail="Error logging in")
    finally:
        cursor.close()

@app.post("/storage/add_chat")
def add_chat(chat: ChatCreate, background_tasks: BackgroundTasks, db: mysql.connector.MySQLConnection = Depends(get_db)):
    cursor = db.cursor()

    try:
        cursor.execute("INSERT INTO chats (user_id, prompt, answer) VALUES (%s, %s, %s)", (chat.user_id, chat.prompt, chat.answer))
        db.commit()
        background_tasks.add_task(send_to_kafka, app.state.kafka_producer, 'chat_events', {
            'event': 'add_chat',
            'user_id': chat.user_id,
            'prompt': chat.prompt
        })
        return {"message": "Chat added successfully"}
    except mysql.connector.Error as err:
        logger.error(f"Error: {err}")
        raise HTTPException(status_code=500, detail="Error adding chat")
    finally:
        cursor.close()

@app.get("/storage/get_chats/{user_id}")
def get_chats(user_id: int, db: mysql.connector.MySQLConnection = Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM chats WHERE user_id = %s", (user_id,))
        chats = cursor.fetchall()
        return {"chats": [{"prompt": chat["prompt"], "answer": chat["answer"]} for chat in chats]}
    except mysql.connector.Error as err:
        logger.error(f"Error: {err}")
        raise HTTPException(status_code=500, detail="Error retrieving chats")
    finally:
        cursor.close()

# Lifecycle Events
@app.on_event("startup")
def startup_event():
    app.state.kafka_producer = init_kafka()
    logger.info("Kafka producer initialized")
    # Create the necessary tables if they do not exist
    db = get_db()
    create_tables_if_not_exists(db)
    db.close()

@app.on_event("shutdown")
def shutdown_event():
    if hasattr(app.state, 'kafka_producer'):
        app.state.kafka_producer.close()
        logger.info("Kafka producer closed")
