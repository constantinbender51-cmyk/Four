import google.generativeai as genai
from openai import OpenAI
import json

SYSTEM_PROMPT = """
You are an expert coding assistant. You have access to a GitHub repository.
You must output ONLY valid JSON. Do not output markdown blocks.
Structure your response as a JSON object with a key "message" (for the user) and "changes" (list of file operations).

The "changes" schema:
[
  {
    "action": "insert", "file": "path/to/file.py", "line": 10, "content": "code to insert"
  },
  {
    "action": "erase", "file": "path/to/file.py", "line": 15, "content": "exact code\nto erase" 
  },
  {
    "action": "write", "file": "new_file.py", "content": "full file content"
  },
  {
    "action": "delete_file", "file": "path/to/obsolete_file.py"
  }
]

RULES:
1. 'line' is 1-based.
2. 'erase' content must match the file EXACTLY or it will fail.
3. Multiple changes are allowed.
4. 'delete_file' removes the file entirely from the repository.
5. You see the file contents in the context below.
"""

def query_llm(provider, api_key, model_name, history, repo_context, user_msg):
    full_prompt = f"{repo_context}\n\nUser: {user_msg}"
    
    # Construct messages list from history (last 10) + current context
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add history (limited to last 10)
    for msg in history[-10:]:
        role = "user" if msg['sender'] == 'user' else "assistant"
        messages.append({"role": role, "content": msg['text']})
    
    messages.append({"role": "user", "content": full_prompt})

    try:
        if provider == 'gemini':
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            # Gemini handles history differently, but for single-turn stateless with context, we just generate
            # Formatting chat history for Gemini is slightly different, simplified here to pure prompt for reliability
            chat_history = []
            for m in messages:
                role = "user" if m['role'] in ['user', 'system'] else "model"
                chat_history.append({"role": role, "parts": [m['content']]})
            
            response = model.generate_content(chat_history)
            text_response = response.text
            
        elif provider == 'deepseek':
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={ "type": "json_object" } 
            )
            text_response = response.choices[0].message.content
            
        # Clean code blocks if model messes up JSON constraint
        clean_json = text_response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)

    except Exception as e:
        return {"message": f"Error calling API: {str(e)}", "changes": []}
