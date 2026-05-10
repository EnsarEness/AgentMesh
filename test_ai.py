import os
from openai import OpenAI
print("OpenAI Key:", bool(os.environ.get("OPENAI_API_KEY")))
try:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "say hi in JSON format like {\"greeting\":\"hi\"}"}],
        response_format={ "type": "json_object" }
    )
    print(resp.choices[0].message.content)
except Exception as e:
    print("Error:", e)
