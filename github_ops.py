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
    
    # Files to explicitly include even if they don't have standard extensions
    config_files = {'Procfile', 'Dockerfile', 'Makefile', '.gitignore', 'requirements.txt'}
    allowed_extensions = ('.py', '.md', '.txt', '.js', '.html', '.css', '.json')

    files_context = ""
    if response.status_code == 200:
        tree = response.json().get('tree', [])
        for item in tree:
            path = item['path']
            # Check if it's a blob (file) and matches our filter
            is_config = path.split('/')[-1] in config_files
            is_code = path.endswith(allowed_extensions)
            
            if item['type'] == 'blob' and (is_code or is_config):
                content, _ = get_file_content(token, owner, repo, path, branch)
                if content:
                    files_context += f"\n--- FILE: {path} ---\n"
                    # Add line numbers to context for easier LLM targeting
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        files_context += f"{i} | {line}\n"
                        
    return files_context

def apply_changes_locally(original_content, changes):
    """
    Applies changes to the content string.
    CRITICAL: Sorts by line number DESCENDING so early edits don't shift later line numbers.
    """
    lines = original_content.split('\n')
    
    # Priority for same-line operations: 
    # We want 'erase' to happen BEFORE 'insert' at the same line to effect a clean replacement.
    # Since we sort Reverse=True (descending), we give 'erase' a higher priority value.
    action_priority = {
        'delete_file': 3,
        'erase': 2,
        'insert': 1,
        'write': 0
    }

    # Sort changes: 
    # 1. Line Number (Desc) - Process bottom of file first
    # 2. Action Priority (Desc) - Process Erase before Insert on same line
    sorted_changes = sorted(changes, key=lambda x: (x.get('line', 0), action_priority.get(x.get('action'), 0)), reverse=True)

    for change in sorted_changes:
        action = change.get('action')
        line_idx = change.get('line', 1) - 1  # Convert 1-based to 0-based
        content = change.get('content', "")

        if action == 'insert':
            # Insert adds content AT that index
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
                    print(f"Expected: {target_lines}")
                    print(f"Found: {current_slice}")

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
    
    response = requests.delete(url, headers=headers, json=data)
    return response.status_code in [200, 204]
