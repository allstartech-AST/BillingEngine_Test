import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client()

print("Available models:")
for m in client.models.list():
    print(f"- {m.name} (Display: {m.display_name})")
