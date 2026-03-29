"""Verify the hardened server response."""
import urllib.request

r = urllib.request.urlopen("http://127.0.0.1:8000")
html = r.read().decode("utf-8")

# Check token injection
token_injected = "{{ session_token }}" not in html and "SESSION_TOKEN" in html
print(f"TOKEN_INJECTED: {token_injected}")

# Find the token line
for line in html.split("\n"):
    if "SESSION_TOKEN" in line and "const" in line:
        print(f"TOKEN_LINE: {line.strip()[:120]}")
        break

# Check CSP
csp_found = "Content-Security-Policy" in html
print(f"CSP_FOUND: {csp_found}")

# Count SRI tags
sri_count = html.count('integrity="sha384-')
print(f"SRI_TAGS: {sri_count}")
