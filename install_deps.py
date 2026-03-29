import subprocess
import sys

mapping = {
    'bs4': 'beautifulsoup4',
    'aiofiles': 'aiofiles',
    'playwright': 'playwright',
    'OpenSSL': 'pyOpenSSL',
    'cryptography': 'cryptography',
    'yaml': 'pyyaml',
    'brotli': 'brotli',
    'colorama': 'colorama',
    'rich': 'rich',
    'xxhash': 'xxhash',
    'msgspec': 'msgspec',
    'json_repair': 'json-repair',
    'jsonschema': 'jsonschema',
    'w3lib': 'w3lib',
    'tzlocal': 'tzlocal',
    'fake_useragent': 'fake-useragent',
    'dotenv': 'python-dotenv',
    'filelock': 'filelock'
}

while True:
    try:
        import crawl4ai
        print('CRAWL4AI_IMPORTED_SUCCESSFULLY')
        break
    except ModuleNotFoundError as e:
        module_orig = e.name.split('.')[0]
        module = mapping.get(module_orig, module_orig)
        print(f"Missing import {module_orig}, installing pip package {module}...")
        res = subprocess.run([sys.executable, "-m", "pip", "install", module])
        if res.returncode != 0:
            print(f"Failed to install {module}")
            break
    except Exception as e:
        print(f"Other error: {e}")
        break
