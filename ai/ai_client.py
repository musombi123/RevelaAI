from groq import Groq
from ai.system_prompt import SYSTEM_PROMPT

client = Groq()

def query_llm(user_query: str):
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_query}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content
