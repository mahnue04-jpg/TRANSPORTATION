import requests
import json

url = "http://localhost:8010/api/chat"
user_id = "debug-response-engine"

prompts = [
    "Help me start a trucking business",
    "Create a proposal for a website redesign project for a local clinic",
    "Draft an invoice for monthly consulting services"
]

for prompt in prompts:
    print(f"\n--- PROMPT: {prompt} ---")
    data = {
        "user_id": user_id,
        "message": prompt
    }
    try:
        response = requests.post(url, json=data)
        if response.status_code == 200:
            res_json = response.json()
            # Assuming standard structure, adjust if your API is different
            print(f"Status: {response.status_code}")
            # Print reply or tools if present
            if "reply" in res_json:
                print(f"Reply (first 200 chars): {res_json['reply'][:200]}...")
            if "tools" in res_json:
                 print(f"Tools: {res_json['tools']}")
            if not "reply" in res_json and not "tools" in res_json:
                 print(f"Full JSON: {json.dumps(res_json, indent=2)[:500]}...")
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Exception: {e}")
