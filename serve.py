"""Run AIMIS as a server on one PC, so other phones, tablets and laptops can use it.

    python serve.py

Uses Waitress (a real web server for Python, works on Windows) instead of Flask's development server,
so many students can use AIMIS at the same time. Settings in .env (all optional):
    HOST=0.0.0.0        0.0.0.0 = other devices on the same Wi-Fi can connect; 127.0.0.1 = this PC only
    PORT=8000
    THREADS=16          how many requests are handled at the same time
    BEHIND_PROXY=1      only when a Cloudflare Tunnel (or another HTTPS proxy) sits in front of AIMIS
See DEPLOY.md for the full steps, including HTTPS (the camera and microphone need it on other devices).
"""
import os
import socket

from dotenv import load_dotenv

load_dotenv()

from app import app  # noqa: E402  (after load_dotenv so app.py sees the .env values)


def lan_ip():
    """This PC's address on the Wi-Fi / LAN (what other devices type), or None."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))      # nothing is sent; this only picks the network card that has internet
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    host = os.getenv("HOST") or "0.0.0.0"
    port = int(os.getenv("PORT") or 8000)
    threads = int(os.getenv("THREADS") or 16)

    if os.getenv("BEHIND_PROXY") == "1":
        # The tunnel talks to AIMIS over plain HTTP and tells it the real address and "https" in headers.
        # ProxyFix makes Flask trust exactly one proxy, so links and redirects use https:// .
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if os.getenv("FLASK_DEBUG") == "1":
        print("WARNING: FLASK_DEBUG=1 is on. Turn it off in .env before letting other people use AIMIS.")

    print("\nAIMIS server is running. Keep this window open.")
    print(f"  This PC:            http://localhost:{port}")
    ip = lan_ip()
    if host == "0.0.0.0" and ip:
        print(f"  Same Wi-Fi devices: http://{ip}:{port}  (camera/mic need HTTPS there: see DEPLOY.md)")
    print("  Stop: press Ctrl+C\n")

    try:
        from waitress import serve
    except ImportError:
        print("Waitress is not installed (pip install waitress). Using Flask's development server instead.")
        app.run(host=host, port=port, threaded=True)
        return
    serve(app, host=host, port=port, threads=threads, channel_timeout=120,
          max_request_body_size=app.config.get("MAX_CONTENT_LENGTH") or 25 * 1024 * 1024)


if __name__ == "__main__":
    main()
