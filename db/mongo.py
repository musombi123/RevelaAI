import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "revelaai")

if not MONGO_URI:
    raise RuntimeError("❌ MONGO_URI is missing. Set it in Render Environment Variables.")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_col = db["users"]
memory_col = db["memory"]
messages_col = db["messages"]
