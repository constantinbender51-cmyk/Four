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
    "action": "delete_file", "file": "path/to/obsolete.py"
  }
]

CRITICAL RULES FOR LINE NUMBERS:
1. 'line' is 1-based.
2. ALWAYS use the ORIGINAL line numbers as seen in the provided file context.
3. DO NOT calculate line shifts yourself. The system applies changes from bottom-to-top automatically.
4. To REPLACE a line (e.g., line 5): Issue an 'erase' for line 5 AND an 'insert' for line 5. The system will handle the order.

Context:
You see the file contents below.
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
            
        # --- Robust JSON Extraction ---
        # LLMs sometimes output conversational text before or after the JSON.
        # We find the first '{' and the last '}' to extract the main JSON object.
        start_idx = text_response.find('{')
        end_idx = text_response.rfind('}')

        if start_idx != -1 and end_idx != -1:
            clean_json = text_response[start_idx : end_idx + 1]
            return json.loads(clean_json)
        else:
            # Fallback if no braces found (rare if model follows prompt)
            # Try standard strip in case it's just whitespace
            return json.loads(text_response.strip())

    except Exception as e:
        return {"message": f"Error calling API or parsing JSON: {str(e)}", "changes": []}
