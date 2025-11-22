import requests
import base64

def get_file_content(token, owner, repo, path, branch="main"):
    """Fetches file content from GitHub."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        content = response.json()
        file_sha = content['sha']
        decoded_content = base64.b64decode(content['content']).decode('utf-8')
        return decoded_content, file_sha
    return None, None

def get_repo_structure(token, owner, repo, branch="main"):
    """Fetches all file paths and their contents for context."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    files_context = ""
    if response.status_code == 200:
        tree = response.json().get('tree', [])
        for item in tree:
            if item['type'] == 'blob' and item['path'].endswith(('.py', '.md', '.txt', '.js', '.html')):
                content, _ = get_file_content(token, owner, repo, item['path'], branch)
                if content:
                    files_context += f"\n--- FILE: {item['path']} ---\n{content}\n"
    return files_context

def apply_changes_locally(original_content, changes):
    """
    Applies changes to the content string.
    CRITICAL: Sorts by line number DESCENDING so early edits don't shift later line numbers.
    """
    lines = original_content.split('\n')
    
    # Sort changes: Primary key = Line Number (Desc), Secondary = Order in original request (Desc)
    # We process from bottom to top.
    sorted_changes = sorted(changes, key=lambda x: (x.get('line', 0), changes.index(x)), reverse=True)

    for change in sorted_changes:
        action = change.get('action')
        line_idx = change.get('line', 1) - 1  # Convert 1-based to 0-based
        content = change.get('content', "")

        if action == 'insert':
            # Insert adds content AT that index, shifting existing down
            if 0 <= line_idx <= len(lines) + 1:
                new_lines = content.split('\n')
                lines[line_idx:line_idx] = new_lines

        elif action == 'erase':
            # content to erase must match exactly
            target_lines = content.split('\n')
            span = len(target_lines)
            
            # Check bounds
            if line_idx + span <= len(lines):
                current_slice = lines[line_idx : line_idx + span]
                # Exact match check
                if current_slice == target_lines:
                    del lines[line_idx : line_idx + span]
                else:
                    print(f"Skipping Erase: Content mismatch at line {line_idx+1}")

        elif action == 'write':
            # Overwrite entire file
            lines = content.split('\n')

        elif action == 'delete_file':
            return None # Signal to delete

    return "\n".join(lines)

def push_to_github(token, owner, repo, file_path, new_content, sha, branch="main"):
    """Push updated content to GitHub."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    headers = {"Authorization": f"Bearer {token}"}
    
    data = {
        "message": f"AI Update to {file_path}",
        "content": base64.b64encode(new_content.encode('utf-8')).decode('utf-8'),
        "branch": branch
    }
    if sha:
        data["sha"] = sha

    response = requests.put(url, headers=headers, json=data)
    return response.json()

def delete_file_from_github(token, owner, repo, path, sha, branch="main"):
    """Deletes a file from GitHub."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    
    data = {
        "message": f"AI Delete of {path}",
        "sha": sha,
        "branch": branch
    }
    
    # GitHub API DELETE expects JSON body for 'message' and 'sha'
    # requests.delete supports 'json' parameter in newer versions, or use 'data'
    response = requests.delete(url, headers=headers, json=data)
    return response.status_code in [200, 204]
