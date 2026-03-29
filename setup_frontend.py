import os
import urllib.request

ASSETS = {
  'static/css/xterm.css': 'https://unpkg.com/xterm@5.3.0/css/xterm.css',
  'static/js/xterm.js': 'https://unpkg.com/xterm@5.3.0/lib/xterm.js',
  'static/js/xterm-addon-fit.js': 'https://unpkg.com/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js',
  'static/js/xterm-addon-web-links.js': 'https://unpkg.com/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.js',
  'static/js/three.min.js': 'https://unpkg.com/three@0.128.0/build/three.min.js',
  'static/js/react.production.min.js': 'https://unpkg.com/react@18/umd/react.production.min.js',
  'static/js/react-dom.production.min.js': 'https://unpkg.com/react-dom@18/umd/react-dom.production.min.js',
  'static/js/babel.min.js': 'https://unpkg.com/@babel/standalone/babel.min.js'
}

os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'css'), exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'js'), exist_ok=True)

print('Downloading frontend assets locally to resolve CDN timeouts...')
for path, url in ASSETS.items():
    full_path = os.path.join(os.path.dirname(__file__), path)
    print(f'Fetching {os.path.basename(path)} ...')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=30) as response, open(full_path, 'wb') as out_file:
            out_file.write(response.read())
        print('  -> OK')
    except Exception as e:
        print(f'  -> Error: {e}')

print('\nBackend static file setup complete. Please run python main.py again!')
