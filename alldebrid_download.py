import os, re, time, configparser, requests, logging, shutil, threading
import bencodepy, hashlib, base64

config = configparser.ConfigParser()
config.read('config.ini')

watch_folder = config.get('FOLDERS', 'watch_folder', fallback='watch')
complete_folder = config.get('FOLDERS', 'complete_folder', fallback='complete')
downloads_folder = config.get('FOLDERS', 'downloads_folder', fallback='downloads')
library_folder = config.get('FOLDERS', 'library_folder', fallback='library')
log_file = config.get('GENERAL', 'log_file', fallback='alldebrid.log')
apikey = config.get('KEY', 'allkey')

os.makedirs(downloads_folder, exist_ok=True)
os.makedirs(complete_folder, exist_ok=True)
os.makedirs(library_folder, exist_ok=True)

with open(log_file, 'w', encoding='utf-8') as f:
    f.write('')

LOG = logging.getLogger("Alldebrid")
LOG.setLevel(logging.INFO)
fh = logging.FileHandler(log_file, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
LOG.addHandler(fh)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(message)s'))
LOG.addHandler(ch)

def extract_rom_tag_from_torrent(path):
    try:
        with open(path, 'rb') as f:
            meta = bencodepy.decode(f.read())
        info = meta[b'info']
        rom_tags = []

        if b'files' in info:
            for file in info[b'files']:
                for part in file[b'path']:
                    name = part.decode(errors='ignore')
                    tag = extract_rom_tag(name)
                    if tag:
                        rom_tags.append(tag)
        else:
            name = info.get(b'name', b'').decode(errors='ignore')
            tag = extract_rom_tag(name)
            if tag:
                rom_tags.append(tag)

        return rom_tags[0] if rom_tags else None
    except Exception as e:
        LOG.error(f"❌ Failed to extract ROM tag from .torrent: {e}")
        return None

def extract_rom_tag(filename):
    match = re.search(r"\[([0-9A-F]{16})\]\[v(\d+)\]", filename, re.IGNORECASE)
    if match:
        title_id, version = match.groups()
        return f"[{title_id}][v{version}]"
    return None

def is_duplicate_from_tag(tag):
    for file in os.listdir(library_folder):
        if tag.lower() in file.lower():
            LOG.info(f"✅ Duplicate ROM already in library: {file}")
            return True
    return False

def torrent_to_magnet(path):
    try:
        with open(path, 'rb') as f:
            meta = bencodepy.decode(f.read())
        info = meta[b'info']
        info_bencoded = bencodepy.encode(info)
        digest = hashlib.sha1(info_bencoded).digest()
        b32hash = base64.b32encode(digest).decode()
        name = info.get(b'name', b'').decode(errors='ignore')
        return f"magnet:?xt=urn:btih:{b32hash}&dn={name}", name
    except Exception as e:
        LOG.error(f"Torrent conversion failed: {e}")
        return None, None

def send_magnet(magnet):
    try:
        r = requests.get("https://api.alldebrid.com/v4/magnet/upload", params={
            "apikey": apikey,
            "magnets[]": magnet
        })
        res = r.json()
        if res["status"] == "success":
            magnets = res["data"]["magnets"]
            if isinstance(magnets, list) and len(magnets) > 0:
                return magnets[0]["id"]
            elif isinstance(magnets, dict):
                return magnets["id"]
        LOG.error(f"Magnet rejected: {res}")
    except Exception as e:
        LOG.error(f"Send magnet error: {e}")
    return None

def poll_ready(magnet_id):
    for _ in range(60):
        try:
            r = requests.get("https://api.alldebrid.com/v4/magnet/status", params={
                "apikey": apikey,
                "id": magnet_id
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
        shared = entry.get("link")
        r = requests.get("https://api.alldebrid.com/v4/link/unlock", params={"apikey": apikey, "link": shared})
        res = r.json()
        if res["status"] != "success":
            LOG.error(f"Unlock failed: {res}")
            return
        url = res["data"]["link"]
        name = res["data"]["filename"]
        size = res["data"].get("filesize", 1)
        dest = os.path.join(downloads_folder, name)

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                downloaded = 0
                start_time = time.time()
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.time() - start_time, 0.1)
                    percent = (downloaded / size) * 100
                    speed = downloaded / 1024 / elapsed
                    LOG.info(f"⬇️ {name} {percent:.1f}% at {speed:.1f} KB/s")

        if name.lower().endswith(('.nsp', '.nsz', '.xci', '.xcz')):
            LOG.info(f"✅ Finished: {name}")
            shutil.move(dest, os.path.join(library_folder, name))
        else:
            os.remove(dest)
            LOG.info(f"🧹 Deleted non-ROM file: {name}")
    except Exception as e:
        LOG.error(f"Download failed: {e}")

def process_torrents():
    LOG.info("📡 Watching for torrents...")
    while True:
        for f in os.listdir(watch_folder):
            if f.endswith('.torrent') and not f.endswith('.processed.torrent'):
                full = os.path.join(watch_folder, f)
                LOG.info(f"📄 Found torrent: {f}")
                rom_tag = extract_rom_tag_from_torrent(full)
                if not rom_tag:
                    LOG.warning(f"❓ No valid ROM tag found in {f} — allowing download.")
                elif is_duplicate_from_tag(rom_tag):
                    LOG.info(f"⚠️ Duplicate detected by ROM tag {rom_tag} — skipping.")
                    os.remove(full)
                    continue

                magnet, name = torrent_to_magnet(full)
                if not magnet or not name:
                    continue

                LOG.info(f"🔗 Magnet: {magnet}")
                mid = send_magnet(magnet)
                if not mid:
                    continue
                links = poll_ready(mid)
                threads = []
                for link in links:
                    t = threading.Thread(target=unlock_and_download, args=(link,))
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join()
                shutil.move(full, os.path.join(complete_folder, f))
        time.sleep(5)

if __name__ == "__main__":
    process_torrents()
