import os
import requests

MVI_API = os.getenv("MVI_API")


def ask_mvi(
    text,
    system_prompt="",
    session_id=None,
):
    headers = {}

    if session_id:
        headers["X-Session-ID"] = session_id

    response = requests.post(
        MVI_API,
        headers=headers,
        json={
            "text": text,
            "system_prompt": system_prompt,
        },
        timeout=120,
    )

    response.raise_for_status()

    return response.json()

# -------------------------------
# Replicate Client (Images)
# -------------------------------

def get_replicate_headers():
    api_token = os.environ.get("REPLICATE_API_TOKEN")

    if not api_token:
        raise RuntimeError("REPLICATE_API_TOKEN is not set")

    return {
        "Authorization": f"Token {api_token}",
        "Content-Type": "application/json",
    }


def create_replicate_prediction(version: str, input_data: dict):
    headers = get_replicate_headers()

    response = requests.post(
        "https://api.replicate.com/v1/predictions",
        headers=headers,
        json={
            "version": version,
            "input": input_data,
        },
    )

    response.raise_for_status()

    return response.json()