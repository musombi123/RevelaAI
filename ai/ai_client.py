import os
from groq import Groq
import requests

# -------------------------------
# Groq Client (Text / Reasoning)
# -------------------------------
def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    return Groq(api_key=api_key)


# -------------------------------
# Replicate Client (Images / Logos)
# -------------------------------
def get_replicate_headers():
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        raise RuntimeError("REPLICATE_API_TOKEN is not set")

    return {
        "Authorization": f"Token {api_token}",
        "Content-Type": "application/json"
    }


def create_replicate_prediction(version: str, input_data: dict) -> dict:
    headers = get_replicate_headers()

    response = requests.post(
        "https://api.replicate.com/v1/predictions",
        headers=headers,
        json={
            "version": version,
            "input": input_data
        }
    )

    response.raise_for_status()
    return response.json()
