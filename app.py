from flask import Flask, render_template, request, jsonify
import github_ops
import llm_handler
from gtts import gTTS
import io
import base64

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    
    # Credentials & Config
    gh_token = data.get('ghToken')
    gh_user = data.get('ghUser')
    gh_repo = data.get('ghRepo')
    
    api_key = data.get('apiKey')
    provider = data.get('provider') # 'gemini' or 'deepseek'
    model = data.get('model')
    
    history = data.get('history', [])
    user_msg = data.get('message')

    # 1. Fetch Repo Context
    try:
        repo_context = github_ops.get_repo_structure(gh_token, gh_user, gh_repo)
    except Exception as e:
        return jsonify({"error": f"GitHub Error: {str(e)}"}), 500

    # 2. Query LLM
    llm_response = llm_handler.query_llm(provider, api_key, model, history, repo_context, user_msg)
    
    # 3. Process Changes
    changes = llm_response.get('changes', [])
    execution_log = []

    if changes:
        # Group by file to minimize API calls
        changes_by_file = {}
        for change in changes:
            fname = change['file']
            if fname not in changes_by_file:
                changes_by_file[fname] = []
            changes_by_file[fname].append(change)

        for fname, file_changes in changes_by_file.items():
            try:
                # Fetch specific file content
                content, sha = github_ops.get_file_content(gh_token, gh_user, gh_repo, fname)
                
                # Handle case where file doesn't exist (for new file creation)
                if content is None: content = "" 
                
                # Apply Logic
                new_content = github_ops.apply_changes_locally(content, file_changes)
                
                if new_content is None:
                    # Logic to delete file via API
                    if sha: # Can only delete if it exists remotely
                        github_ops.delete_file_from_github(gh_token, gh_user, gh_repo, fname, sha)
                        execution_log.append(f"Deleted {fname}")
                    else:
                        execution_log.append(f"Skipped delete {fname} (File not found)")
                else:
                    # Push to GitHub
                    github_ops.push_to_github(gh_token, gh_user, gh_repo, fname, new_content, sha)
                    execution_log.append(f"Updated {fname}")
            except Exception as e:
                execution_log.append(f"Failed to update {fname}: {str(e)}")

    return jsonify({
        "response": llm_response.get('message', "Processed"),
        "execution_log": execution_log,
        "audio": generate_audio(llm_response.get('message', "Processed"))
    })

def generate_audio(text):
    """Generate audio from text using gTTS and return as base64."""
    try:
        # Create gTTS object
        tts = gTTS(text=text, lang='zh', slow=True)
        
        # Save to BytesIO object
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        
        # Encode to base64
        audio_base64 = base64.b64encode(audio_fp.read()).decode('utf-8')
        return audio_base64
    except Exception as e:
        print(f"Audio generation error: {str(e)}")
        return None

@app.route('/api/heartbeat', methods=['GET'])
def heartbeat():
    """Simple heartbeat endpoint to keep connection alive."""
    return jsonify({"status": "alive"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
