# scripts/api_external/pushover.py

import requests
import os
from dotenv import load_dotenv

load_dotenv()

PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")


def send_notification(title: str, msg: str, priority: int = 0) -> None:
    try:
        response = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": msg,
            "priority": priority,
        })

        result = response.json()

        if result.get("status") != 1:
            print(f"pushover error: {result.get('errors')}")

    except Exception as e:
        print(f"pushover failed: {e}")