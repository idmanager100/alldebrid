start "" py alldebrid_download.py
wait 2
start "" py app.py
wait 2
start "" py torrent_fetcher.py
wait 2

wait 2
start "" py move_complete.py
wait 2
start "" py alldebrid_download.py

pause