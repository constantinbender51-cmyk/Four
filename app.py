from flask import Flask, render_template, request, jsonify, send_file
import github_ops
import llm_handler
from gtts import gTTS
import os
import tempfile
import uuid

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    """Convert text to speech and return audio file."""
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        # Create temporary file
        temp_dir = tempfile.gettempdir()
        audio_file = os.path.join(temp_dir, f"tts_{uuid.uuid4()}.mp3")
        
        # Generate speech
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(audio_file)
        
        return send_file(audio_file, mimetype='audio/mpeg')
    
    except Exception as e:
        return jsonify({"error": f"TTS Error: {str(e)}"}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    
    # Credentials & Config
    gh_token = data.get('ghToken')
    gh_user = data.get('ghUser')
    gh_repo = data.get('ghRepo')
    
    api_key = data.get('apiKey')
    provider = data.get('provider')  # 'gemini' or 'deepseek'
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
    changes_applied = False

    if changes:
        changes_applied = True
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
                if content is None:
                    content = ""
                
                # Apply Logic
                new_content = github_ops.apply_changes_locally(content, file_changes)
                
                if new_content is None:
                    # Logic to delete file via API
                    if sha:  # Can only delete if it exists remotely
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

    response_data = {
        "response": llm_response.get('message', "Processed"),
        "execution_log": execution_log,
        "changes_applied": changes_applied
    }

    # 4. If changes were applied, trigger review
    if changes_applied:
        try:
            # Fetch updated repo context
            updated_repo_context = github_ops.get_repo_structure(gh_token, gh_user, gh_repo)
            
            # Create review prompt
            review_msg = f"Previous changes applied:\n{chr(10).join(execution_log)}\n\nPlease review the current state of the repository and confirm everything looks correct."
            
            # Query LLM for review
            review_response = llm_handler.query_llm(
                provider, api_key, model, history, 
                updated_repo_context, review_msg, is_review=True
            )
            
            response_data["review"] = review_response.get('message', '')
            
            # If review suggests additional changes, apply them
            review_changes = review_response.get('changes', [])
            if review_changes:
                review_log = []
                changes_by_file = {}
                for change in review_changes:
                    fname = change['file']
                    if fname not in changes_by_file:
                        changes_by_file[fname] = []
                    changes_by_file[fname].append(change)

                for fname, file_changes in changes_by_file.items():
                    try:
                        content, sha = github_ops.get_file_content(gh_token, gh_user, gh_repo, fname)
                        if content is None:
                            content = ""
                        
                        new_content = github_ops.apply_changes_locally(content, file_changes)
                        
                        if new_content is None:
                            if sha:
                                github_ops.delete_file_from_github(gh_token, gh_user, gh_repo, fname, sha)
                                review_log.append(f"Deleted {fname}")
                        else:
                            github_ops.push_to_github(gh_token, gh_user, gh_repo, fname, new_content, sha)
                            review_log.append(f"Fixed {fname}")
                    except Exception as e:
                        review_log.append(f"Failed to fix {fname}: {str(e)}")
                
                response_data["review_log"] = review_log
                
        except Exception as e:
            response_data["review_error"] = f"Review failed: {str(e)}"

    return jsonify(response_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
