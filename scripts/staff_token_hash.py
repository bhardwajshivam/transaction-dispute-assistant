"""Hash a high-entropy local demo staff token without echoing or saving it."""
from getpass import getpass
import hashlib

if __name__ == '__main__':
    token = getpass('Enter a randomly generated staff token (32–512 characters): ')
    if not 32 <= len(token) <= 512:
        raise SystemExit('Token must contain 32–512 characters.')
    print('Set this server-side environment variable before launching Streamlit:')
    print('STAFF_ACCESS_TOKEN_SHA256=' + hashlib.sha256(token.encode()).hexdigest())
