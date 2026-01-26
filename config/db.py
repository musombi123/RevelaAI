import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("DB_NAME", "revelaai")]

users_col = db["users"]
memory_col = db["memory"]
messages_col = db["messages"]
