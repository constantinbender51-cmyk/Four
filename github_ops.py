import requests
import base64
import difflib

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
    allowed_extensions = ('.py', '.md', '.txt', '.js', '.html', '.css', '.json', '.yml', '.yaml')

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
                    files_context += f"\n{'='*60}\n"
                    files_context += f"FILE: {path}\n"
                    files_context += f"{'='*60}\n"
                    files_context += content + "\n"
                        
    return files_context

def normalize_whitespace(text):
    """Normalize whitespace for more flexible matching."""
    # Normalize line endings
    text = text.replace('\r\n', '\n')
    # Normalize tabs to 4 spaces
    text = text.replace('\t', '    ')
    return text

def find_in_content(content, search_text):
    """
    Find search_text in content with normalized whitespace.
    Returns (index, match_found) or (None, False)
    """
    normalized_content = normalize_whitespace(content)
    normalized_search = normalize_whitespace(search_text)
    
    index = normalized_content.find(normalized_search)
    if index != -1:
        return index, True
    
    return None, False

def find_similar_text(content, search_text, n=3):
    """Find similar text in content for helpful error messages."""
    lines = content.split('\n')
    search_lines = search_text.split('\n')
    
    if not search_lines:
        return []
    
    # Look for lines that contain the first line of search text
    first_search_line = search_lines[0].strip()
    suggestions = []
    
    for i, line in enumerate(lines):
        if first_search_line in line:
            # Get context around this line
            start = max(0, i)
            end = min(len(lines), i + len(search_lines))
            context = '\n'.join(lines[start:end])
            suggestions.append(context)
            if len(suggestions) >= n:
                break
    
    return suggestions

def apply_changes_locally(original_content, changes):
    """
    Applies chunk-based changes to content.
    
    Operations:
    - replace: Find and replace code chunks
    - insert: Insert code at a specific position relative to anchor
    - erase: Remove code chunk (same as replace with "")
    - write: Overwrite entire file
    - delete_file: Signal file deletion
    """
    content = original_content
    
    for change in changes:
        action = change.get('action')
        
        if action == 'write':
            # Complete file overwrite
            content = change.get('content', '')
            
        elif action == 'delete_file':
            # Signal deletion
            return None
            
        elif action == 'replace':
            search_text = change.get('search', '')
            replace_text = change.get('replace', '')
            
            if not search_text:
                print(f"Warning: Replace operation missing 'search' field")
                continue
            
            index, found = find_in_content(content, search_text)
            
            if found:
                # Calculate actual length to replace (accounting for normalization)
                normalized_content = normalize_whitespace(content)
                normalized_search = normalize_whitespace(search_text)
                
                # Find in normalized, replace in original
                norm_index = normalized_content.find(normalized_search)
                
                # Map back to original indices (this is approximate but works well)
                before_normalized = normalized_content[:norm_index]
                before_original = content[:len(before_normalized)]
                
                # Find actual start in original
                actual_start = len(before_original)
                actual_end = actual_start + len(search_text)
                
                # Replace
                content = content[:actual_start] + replace_text + content[actual_end:]
            else:
                # Provide helpful error message
                suggestions = find_similar_text(content, search_text)
                print(f"Warning: Could not find search text for replace operation")
                print(f"Searched for:\n{search_text[:100]}...")
                if suggestions:
                    print(f"Similar code found:\n{suggestions[0][:100]}...")
                    
        elif action == 'erase':
            # Erase is just replace with empty string
            search_text = change.get('search', '')
            
            if not search_text:
                print(f"Warning: Erase operation missing 'search' field")
                continue
                
            index, found = find_in_content(content, search_text)
            
            if found:
                normalized_content = normalize_whitespace(content)
                normalized_search = normalize_whitespace(search_text)
                norm_index = normalized_content.find(normalized_search)
                
                before_normalized = normalized_content[:norm_index]
                before_original = content[:len(before_normalized)]
                
                actual_start = len(before_original)
                actual_end = actual_start + len(search_text)
                
                content = content[:actual_start] + content[actual_end:]
            else:
                print(f"Warning: Could not find search text for erase operation")
                
        elif action == 'insert':
            search_text = change.get('search', '')
            insert_text = change.get('insert', '')
            position = change.get('position', 'after')  # 'before', 'after', 'start', 'end'
            
            if position == 'start':
                content = insert_text + content
                
            elif position == 'end':
                content = content + insert_text
                
            else:
                if not search_text:
                    print(f"Warning: Insert operation missing 'search' anchor")
                    continue
                    
                index, found = find_in_content(content, search_text)
                
                if found:
                    normalized_content = normalize_whitespace(content)
                    normalized_search = normalize_whitespace(search_text)
                    norm_index = normalized_content.find(normalized_search)
                    
                    before_normalized = normalized_content[:norm_index]
                    before_original = content[:len(before_normalized)]
                    
                    actual_start = len(before_original)
                    
                    if position == 'before':
                        content = content[:actual_start] + insert_text + content[actual_start:]
                    else:  # after
                        actual_end = actual_start + len(search_text)
                        content = content[:actual_end] + insert_text + content[actual_end:]
                else:
                    print(f"Warning: Could not find anchor text for insert operation")

    return content

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
