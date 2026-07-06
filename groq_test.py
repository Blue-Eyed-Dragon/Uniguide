import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
response = client.chat.completions.create(
    model="qwen/qwen3-32b",
    messages=[
        {"role": "user", "content": "Describe how to make an egg sandwich and then list the ingredients. Make the sandwich as a python function uses helper functions to eecute the steps in the ingredients"}
    ]
)

print(response.choices[0].message.content)