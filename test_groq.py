from dotenv import load_dotenv
load_dotenv()

import os
from groq import Groq

print("KEY FOUND:", bool(os.getenv("GROQ_API_KEY")))

client = Groq()

completion = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[
        {"role": "user", "content": "Hello Groq!"}
    ]
)

print(completion.choices[0].message.content)
