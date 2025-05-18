from flask import Flask, request, send_from_directory, abort, Response
import os
import datetime
import configparser
from functools import wraps

app = Flask(__name__)

# Load config.ini
config = configparser.ConfigParser()
config.read('config.ini')
LIBRARY_PATH = config.get('FOLDERS', 'library', fallback='C:/new.v1/library')
USERNAME = config.get('ROMSERVER', 'tinuser')
PASSWORD = config.get('ROMSERVER', 'tinpass')
LOG_FILE = "download.log"

# Authentication utilities
def check_auth(username, password):
    return username == USERNAME and password == PASSWORD

def authenticate():
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# Logging
def log_download(ip, filename):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {ip} downloaded {filename}"
    print(log_line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

@app.route('/roms/<path:filename>')
@requires_auth
def serve_rom(filename):
    file_path = os.path.join(LIBRARY_PATH, filename)
    if not os.path.isfile(file_path):
        abort(404)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    log_download(client_ip, filename)
    return send_from_directory(LIBRARY_PATH, filename, as_attachment=True)

@app.route('/')
@requires_auth
def index():
    try:
        files = os.listdir(LIBRARY_PATH)
        links = [f'<a href="/roms/{f}">{f}</a>' for f in files if os.path.isfile(os.path.join(LIBRARY_PATH, f))]
        return "<h1>Available ROMs:</h1>" + "<br>".join(links)
    except Exception as e:
        return f"<h1>Error accessing library:</h1><pre>{e}</pre>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
