# core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "RevelaAI"
ENV = os.getenv("ENV", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 10))
