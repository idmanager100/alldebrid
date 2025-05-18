@echo off
echo 🔴 Stopping all python.exe processes...
taskkill /F /IM python.exe >nul 2>&1
echo 🧹 Clearing logs...
del /F /Q alldebrid_download.log >nul 2>&1
del /F /Q torrent_watcher.log >nul 2>&1
echo ✅ Stopped and cleared logs.
pause
