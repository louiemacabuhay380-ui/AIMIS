# Running AIMIS on one PC as the server

One PC runs AIMIS, the database (`aimis.db`), the encrypted recordings and Ollama. Students open AIMIS
in Chrome or Edge on their own phones, tablets and laptops. Nothing is installed on their devices.

```
 students' phones / laptops ──https──> Cloudflare Tunnel ──> server PC: serve.py (Waitress) ──> aimis.db, uploads/
                                                                          │
                                                                          ├──> Google Gemini (internet)
                                                                          └──> Ollama (on the same PC)
```

## What the server PC needs

- Windows with AIMIS already working with `python app.py` (see README)
- 16 GB RAM is recommended (Ollama's gemma3:4b uses about 4 to 5 GB); 8 GB works if the chatbot is slow or turned off
- Stable internet (Gemini scores the answers and the tunnel carries the traffic)
- Plugged in, with sleep turned off: Settings > System > Power > Screen and sleep > **Never** (when plugged in)

## 1. Install and set up

```
venv\Scripts\activate
pip install -r requirements.txt        (adds waitress, the web server)
```

In `.env`:
- `FLASK_DEBUG` must be off (delete the line or put `#` in front)
- `SECRET_KEY` must be long and random: `python -c "import secrets; print(secrets.token_hex(32))"`
- Keep this PC's own `AUDIO_ENCRYPTION_KEY`. Recordings can't be played without it, so keep a copy somewhere safe.
- Change the admin password after the first login.

## 2. Start the server

Double-click **`start_server.bat`** (or run `python serve.py`). Keep the window open. It shows:

```
AIMIS server is running. Keep this window open.
  This PC:            http://localhost:8000
  Same Wi-Fi devices: http://192.168.1.23:8000
```

Check that it opens on the server PC itself first.

## 3. Let other devices in: pick one

### A. Cloudflare Tunnel (recommended): works anywhere, and the camera and mic work

Browsers only let a website use the camera and microphone over **https://** (or on `localhost`).
A Cloudflare Tunnel gives AIMIS a free https:// link without changing the router.

1. Install it once: `winget install --id Cloudflare.cloudflared`
2. In `.env`, add `BEHIND_PROXY=1`, then restart the server.
3. In a second window: `cloudflared tunnel --url http://localhost:8000`
4. It prints a link like `https://some-random-words.trycloudflare.com`. Share that link with the students.

The quick link changes every time cloudflared restarts. For a link that never changes, you need your own domain
on Cloudflare and a named tunnel (`cloudflared tunnel create aimis`).

If everyone uses only the https link, also add `SESSION_COOKIE_SECURE=1` so the login cookie is never sent
without encryption. Don't add it if anyone still uses the http:// address: their login would stop working.

### B. Same Wi-Fi only: testing only

1. When Windows asks, allow Python on **Private networks**. Or open the port in PowerShell (as administrator):
   `New-NetFirewallRule -DisplayName "AIMIS" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private`
2. On the other device, open `http://<the address shown>:8000`

The camera and mic **won't work** this way on other devices, because it isn't https. Use it only to test pages.
Many school Wi-Fi networks also block devices from reaching each other.

## 4. While it runs

- Keep both windows open (AIMIS, and cloudflared if you use A) and keep Ollama running.
- Gemini's free plan limits how many requests can be made per minute and per day. Each answer needs a few calls,
  so with many students at once some answers fall back to Ollama (slower). For data gathering, schedule students in
  small groups, or use a paid Gemini key.
- SQLite handles a class-sized group fine. Don't edit `aimis.db` in DB Browser while AIMIS is running.

## 5. Backups (do this daily during data gathering)

This makes a safe copy even while AIMIS is running:

```
python -c "import sqlite3, datetime; d = datetime.date.today(); sqlite3.connect('aimis.db').backup(sqlite3.connect(f'backup_aimis_{d}.db'))"
```

Keep backups and the `.env` file off GitHub, on a USB drive that only the group uses. They contain student data.

## 6. Updating AIMIS

Stop the server (Ctrl+C), `git pull`, `pip install -r requirements.txt`, `python check_setup.py --fix`, then start it again.
