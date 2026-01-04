from dotenv import load_dotenv
load_dotenv()

import os
from groq import Groq

print("KEY FOUND:", bool(os.getenv("GROQ_API_KEY")))

client = Groq()

SYSTEM_PROMPT = (
    "You are RevelaAI, a philosophical and theological AI assistant. "
    "If greeted, respond politely and identify yourself as RevelaAI."
)

completion = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "hello"}
    ],
    temperature=0.2
)

print(completion.choices[0].message.content)
