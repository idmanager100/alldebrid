
import os
import time
import requests
from configparser import ConfigParser
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

config = ConfigParser()
config.read('config.ini')

server = "http://switch4pda.ru:8878"
key = config.get('KEY', 'key')
iD = config.get('KEY', 'id')
WATCH_FOLDER = os.path.abspath('./watch')
LOG_FILE = "torrent_watcher.log"

if not os.path.exists(WATCH_FOLDER):
    os.makedirs(WATCH_FOLDER)

def log(msg):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")

def get_html(server, password):
    while True:
        try:
            resp = requests.get(server, auth=HTTPBasicAuth("user", password))
            return resp.text
        except Exception:
            time.sleep(5)

def download_file(link, filename, password):
    while True:
        try:
            resp = requests.get(link, auth=HTTPBasicAuth("user", password), stream=True)
            if resp.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"✅ Downloaded: {filename}")
                log(f"Downloaded: {os.path.basename(filename)}")
                return True
        except Exception:
            print("⚠️ Connection error, retrying...")
            time.sleep(5)

def check_updates():
    html = get_html(server, key)
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all('a', href=True):
        name = a.text
        link = server + "/" + a['href']
        if iD in name and key in name:
            filename = os.path.join(WATCH_FOLDER, name.split("_&&_")[2].replace(" ", "_"))
            if not os.path.exists(filename):
                log(f"Found new torrent: {os.path.basename(filename)}")
                download_file(link, filename, key)

if __name__ == "__main__":
    print("🚀 Torrent fetcher started, watching for updates...")
    while True:
        try:
            check_updates()
        except Exception as e:
            print(f"⚠️ Error: {e}")
            log(f"Error: {e}")
        time.sleep(30)
