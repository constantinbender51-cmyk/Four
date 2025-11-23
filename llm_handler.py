import google.generativeai as genai
from openai import OpenAI
import json
import re

SYSTEM_PROMPT = """
You are an expert coding assistant with access to a GitHub repository.
You must output ONLY valid JSON. Do not output markdown blocks or any text outside the JSON.

Response structure:
{
  "message": "Your explanation to the user",
  "changes": [array of change operations, empty if no changes needed]
}

CHANGE OPERATIONS (Chunk-Based):

1. REPLACE - Find and replace code chunks (most common operation)
{
  "action": "replace",
  "file": "path/to/file.py",
  "search": "exact code chunk to find\ncan be multiple lines",
  "replace": "new code to replace it with\npreserve indentation"
}

2. INSERT - Add new code relative to existing code
{
  "action": "insert",
  "file": "path/to/file.py",
  "search": "anchor code to find",
  "insert": "\\nnew code to insert",
  "position": "after"
}
Position options: "before", "after", "start" (beginning of file), "end" (end of file)

3. ERASE - Remove code chunks
{
  "action": "erase",
  "file": "path/to/file.py",
  "search": "exact code to remove"
}

4. WRITE - Create new file or completely overwrite existing file
{
  "action": "write",
  "file": "new_file.py",
  "content": "complete file content here"
}

5. DELETE_FILE - Remove entire file
{
  "action": "delete_file",
  "file": "path/to/obsolete.py"
}

CRITICAL RULES:

1. SEARCH TEXT MUST BE EXACT
   - Include enough context (3-5 lines) to make searches unique
   - Preserve exact indentation and spacing
   - If you're not sure of exact text, use more context

2. USE REPLACE INSTEAD OF ERASE+INSERT
   - To modify code, use one "replace" operation
   - Don't use separate erase and insert for the same location

3. FOR NEW FUNCTIONS/BLOCKS
   - Use "insert" with "after" position relative to nearby code
   - Example: Insert new function after an existing function

4. PRESERVE INDENTATION
   - Match the indentation of surrounding code exactly
   - Use spaces (4 spaces per indent level for Python)

5. THINK ABOUT CONTEXT
   - Include enough surrounding code in "search" to be unique
   - If a pattern appears multiple times, add more context

EXAMPLES:

Example 1 - Fix a bug:
{
  "message": "Fixed the validation bug in the login function",
  "changes": [{
    "action": "replace",
    "file": "auth.py",
    "search": "if user.password == password:\\n    return True",
    "replace": "if user.check_password(password):\\n    return True"
  }]
}

Example 2 - Add new function:
{
  "message": "Added health check endpoint",
  "changes": [{
    "action": "insert",
    "file": "app.py",
    "search": "@app.route('/')\\ndef home():\\n    return render_template('index.html')",
    "insert": "\\n\\n@app.route('/health')\\ndef health_check():\\n    return jsonify({'status': 'ok'})",
    "position": "after"
  }]
}

Example 3 - Add import at top:
{
  "message": "Added logging import",
  "changes": [{
    "action": "insert",
    "file": "app.py",
    "search": "from flask import Flask, render_template",
    "insert": "\\nimport logging",
    "position": "after"
  }]
}

Example 4 - Create new file:
{
  "message": "Created configuration file",
  "changes": [{
    "action": "write",
    "file": "config.py",
    "content": "# Configuration\\n\\nDEBUG = True\\nPORT = 5000"
  }]
}

Repository context provided below shows current file contents.
"""

REVIEW_PROMPT = """
You are a code reviewer assistant. Your task is to review the changes that were just applied to the repository.

Review the following:
1. Were the changes applied successfully?
2. Is the code now in the correct state?
3. Are there any issues or improvements needed?

Provide a brief summary of the repository's current state and any recommendations.

You must output ONLY valid JSON with this structure:
{
  "message": "Your review and assessment",
  "changes": [array of additional change operations if fixes are needed, empty if everything looks good]
}
"""

def clean_json_response(text):
    """Extract and clean JSON from LLM response."""
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Find JSON object boundaries
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    
    if start_idx != -1 and end_idx != -1:
        json_str = text[start_idx : end_idx + 1]
        # Try to parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            # Try to fix common issues
            # Fix unescaped newlines in strings
            json_str = re.sub(r'(?<!\\)\n(?=[^"]*"(?:[^"]*"[^"]*")*[^"]*$)', r'\\n', json_str)
            return json.loads(json_str)
    
    # Fallback: try to parse entire text
    return json.loads(text.strip())

def query_llm(provider, api_key, model_name, history, repo_context, user_msg, is_review=False):
    """Query LLM with increased max tokens and better error handling."""
    
    system_prompt = REVIEW_PROMPT if is_review else SYSTEM_PROMPT
    full_prompt = f"{repo_context}\n\nUser: {user_msg}"
    
    # Construct messages list from history (last 10) + current context
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history (limited to last 10)
    for msg in history[-10:]:
        role = "user" if msg['sender'] == 'user' else "assistant"
        messages.append({"role": role, "content": msg['text']})
    
    messages.append({"role": "user", "content": full_prompt})

    try:
        if provider == 'gemini':
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            # Format for Gemini
            chat_history = []
            for m in messages:
                role = "user" if m['role'] in ['user', 'system'] else "model"
                chat_history.append({"role": role, "parts": [m['content']]})
            
            # Increased max tokens
            generation_config = genai.types.GenerationConfig(
                max_output_tokens=8000,
                temperature=0.7,
            )
            
            response = model.generate_content(chat_history, generation_config=generation_config)
            text_response = response.text
            
        elif provider == 'deepseek':
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=8000  # Increased max tokens
            )
            text_response = response.choices[0].message.content
            
        # Use improved JSON extraction
        return clean_json_response(text_response)

    except json.JSONDecodeError as e:
        return {
            "message": f"JSON parsing error: {str(e)}. Raw response: {text_response[:200]}...", 
            "changes": []
        }
    except Exception as e:
        return {
            "message": f"Error calling API: {str(e)}", 
            "changes": []
        }
