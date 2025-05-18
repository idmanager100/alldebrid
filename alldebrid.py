import os, re, time, configparser, requests, logging, shutil, threading, base64, hashlib, bencodepy
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
import http.server, socketserver, socket, base64

# === CONFIG LOADING ===
config = configparser.ConfigParser()
config.read('config.ini')

watch_folder = config.get('FOLDERS', 'watch_folder', fallback='watch')
complete_folder = config.get('FOLDERS', 'complete_folder', fallback='complete')
downloads_folder = config.get('FOLDERS', 'download_folder', fallback='downloads')
library_folder = config.get('FOLDERS', 'library_folder', fallback='library')

apikey = config.get('KEY', 'allkey')
fetch_key = config.get('KEY', 'key')
fetch_id = config.get('KEY', 'id')

tinfoil_port = config.getint('TINFOIL', 'port', fallback=9000)
tinfoil_user = config.get('TINFOIL', 'user', fallback='tinfoil')
tinfoil_pass = config.get('TINFOIL', 'pass', fallback='roms123')

server = "http://switch4pda.ru:8878"
log_file = config.get('GENERAL', 'log_file', fallback='alldebrid.log')

LOG = logging.getLogger("AllDebridUnified")
LOG.setLevel(logging.DEBUG)
fh = logging.FileHandler(log_file, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
LOG.addHandler(fh)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(message)s'))
LOG.addHandler(ch)

for folder in [watch_folder, complete_folder, downloads_folder, library_folder]:
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        LOG.warning(f"⚠️ Failed to create folder {folder}: {e}")

def extract_rom_tag(filename):
    match = re.search(r"\[([0-9A-F]{16})\]\[v(\d+)\]", filename, re.IGNORECASE)
    if match:
        return f"[{match.group(1)}][v{match.group(2)}]"
    return None

def extract_rom_tag_from_torrent(path):
    try:
        with open(path, 'rb') as f:
            meta = bencodepy.decode(f.read())
        info = meta[b'info']
        rom_tags = []
        if b'files' in info:
            for file in info[b'files']:
                for part in file[b'path']:
                    tag = extract_rom_tag(part.decode(errors='ignore'))
                    if tag:
                        rom_tags.append(tag)
        else:
            name = info.get(b'name', b'').decode(errors='ignore')
            tag = extract_rom_tag(name)
            if tag:
                rom_tags.append(tag)
        return rom_tags[0] if rom_tags else None
    except Exception as e:
        LOG.error(f"❌ Failed to extract ROM tag: {e}")
        return None

def is_duplicate_from_tag(tag):
    for file in os.listdir(library_folder):
        if tag.lower() in file.lower():
            LOG.info(f"✅ Duplicate ROM detected in library: {file}")
            return True
    return False

def torrent_to_magnet(path):
    try:
        with open(path, 'rb') as f:
            meta = bencodepy.decode(f.read())
        info = meta[b'info']
        digest = hashlib.sha1(bencodepy.encode(info)).digest()
        b32hash = base64.b32encode(digest).decode()
        name = info.get(b'name', b'').decode(errors='ignore')
        return f"magnet:?xt=urn:btih:{b32hash}&dn={name}", name
    except Exception as e:
        LOG.error(f"Torrent conversion failed: {e}")
        return None, None

def send_magnet(magnet):
    try:
        r = requests.get("https://api.alldebrid.com/v4/magnet/upload", params={
            "apikey": apikey, "magnets[]": magnet
        })
        res = r.json()
        if res["status"] == "success":
            magnets = res["data"]["magnets"]
            return magnets[0]["id"] if isinstance(magnets, list) else magnets["id"]
        LOG.error(f"Magnet rejected: {res}")
    except Exception as e:
        LOG.error(f"Send magnet error: {e}")
    return None

def poll_ready(magnet_id):
    for _ in range(60):
        try:
            r = requests.get("https://api.alldebrid.com/v4/magnet/status", params={
                "apikey": apikey, "id": magnet_id
            })
            res = r.json()
            if res["status"] == "success":
                magnet = res["data"]["magnets"]
                if magnet["status"] == "Ready":
                    LOG.info("✅ Download is ready.")
                    return magnet["links"]
                else:
                    LOG.info(f"⏳ Status: {magnet['status']}")
        except Exception as e:
            LOG.error(f"Poll error: {e}")
        time.sleep(5)
    return []

def unlock_and_download(entry):
    try:
        r = requests.get("https://api.alldebrid.com/v4/link/unlock", params={
            "apikey": apikey, "link": entry["link"]
        })
        res = r.json()
        if res["status"] != "success":
            LOG.error(f"Unlock failed: {res}")
            return
        url = res["data"]["link"]
        name = res["data"]["filename"]
        size = res["data"].get("filesize", 1)
        dest = os.path.join(downloads_folder, name)

        with requests.get(url, stream=True) as r:
            with open(dest, 'wb') as f:
                downloaded = 0
                start_time = time.time()
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.time() - start_time, 0.1)
                    speed = downloaded / 1024 / 1024 / elapsed
                    eta = (size - downloaded) / (downloaded / elapsed + 0.1)
                    percent = (downloaded / size) * 100
                    print(f"\r⬇️ {name} {percent:.1f}% at {speed:.2f} MB/s | ETA: {eta:.1f}s", end='', flush=True)

        print()
        LOG.info(f"✅ Finished: {name} | Speed: {speed:.2f} MB/s | Size: {size / (1024 * 1024):.2f} MB")

        if name.lower().endswith(('.nsp', '.nsz', '.xci', '.xcz')):
            final_path = os.path.join(library_folder, name)
            shutil.move(dest, final_path)
            LOG.info(f"📁 Moved to library: {final_path}")
        else:
            os.remove(dest)
            LOG.info(f"🧹 Deleted non-ROM file: {name}")
    except Exception as e:
        LOG.error(f"Download failed: {e}")

def process_torrents():
    LOG.info("📡 Torrent processor started...")
    while True:
        for f in os.listdir(watch_folder):
            if f.endswith('.torrent') and not f.endswith('.processed.torrent'):
                full = os.path.join(watch_folder, f)
                LOG.info(f"📄 Found torrent: {f}")
                tag = extract_rom_tag_from_torrent(full)
                if tag and is_duplicate_from_tag(tag):
                    LOG.info(f"⚠️ Duplicate detected: {tag} — skipping.")
                    os.remove(full)
                    continue
                magnet, name = torrent_to_magnet(full)
                if magnet:
                    mid = send_magnet(magnet)
                    if mid:
                        links = poll_ready(mid)
                        threads = [threading.Thread(target=unlock_and_download, args=(link,)) for link in links]
                        [t.start() for t in threads]
                        [t.join() for t in threads]
                        shutil.move(full, os.path.join(complete_folder, f))
        time.sleep(5)

def watch_remote_server():
    LOG.info("🌐 Remote torrent fetcher started...")
    while True:
        try:
            html = requests.get(server, auth=HTTPBasicAuth("user", fetch_key)).text
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all('a', href=True):
                name = a.text
                if fetch_id in name and fetch_key in name:
                    file = os.path.join(watch_folder, name.split("_&&_")[2].replace(" ", "_"))
                    if not os.path.exists(file):
                        link = f"{server}/{a['href']}"
                        with requests.get(link, auth=HTTPBasicAuth("user", fetch_key), stream=True) as r:
                            with open(file, 'wb') as f:
                                for chunk in r.iter_content(8192):
                                    f.write(chunk)
                        LOG.info(f"✅ Downloaded remote torrent: {os.path.basename(file)}")
        except Exception as e:
            LOG.error(f"⚠️ Remote fetch error: {e}")
        time.sleep(30)

class AuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_HEAD(self): return self.auth_check() and super().do_HEAD()
    def do_GET(self): return self.auth_check() and super().do_GET()
    def auth_check(self):
        auth = self.headers.get('Authorization')
        expected = f"{tinfoil_user}:{tinfoil_pass}"
        valid = "Basic " + base64.b64encode(expected.encode()).decode()
        if auth != valid:
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm=\"Tinfoil ROMs\"')
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return False
        return True

def get_local_ip():
    try: return socket.gethostbyname(socket.gethostname())
    except: return 'localhost'

def start_tinfoil_server():
    os.chdir(library_folder)
    with socketserver.TCPServer(("", tinfoil_port), AuthHandler) as httpd:
        LOG.info(f"🛰️ Tinfoil server running at http://{get_local_ip()}:{tinfoil_port}/ (auth enabled)")
        httpd.serve_forever()

# === MAIN THREAD SAFE EXIT ===
if __name__ == "__main__":
    try:
        t1 = threading.Thread(target=watch_remote_server, daemon=True)
        t2 = threading.Thread(target=process_torrents, daemon=True)
        t3 = threading.Thread(target=start_tinfoil_server, daemon=True)
        t1.start()
        t2.start()
        t3.start()
        while True: time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("🛑 CTRL+C received — shutting down.")
        os._exit(0)
