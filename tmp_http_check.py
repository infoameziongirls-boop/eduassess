import urllib.request
with urllib.request.urlopen('http://127.0.0.1:5000/login', timeout=10) as resp:
    print(resp.status)
    print(resp.read(120).decode('utf-8', 'ignore'))
