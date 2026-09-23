"""Local dashboard and trading worker. Paper by default; live requires explicit launch flags."""

from __future__ import annotations

import json
import mimetypes
import argparse
import getpass
import os
import re
import secrets
import sys
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PACKAGES = Path(__file__).parent / '.packages'
if PACKAGES.is_dir():
    sys.path.insert(0, str(PACKAGES))
from engine import TradingBot


ROOT = Path(__file__).parent
bot = None
CONTROL_TOKEN = secrets.token_urlsafe(32)
PORT = 8765


def key_from_clipboard():
    """Consume a copied account key without asking Windows getpass to handle paste."""
    if os.name != 'nt':
        raise RuntimeError('Clipboard key input is supported only on Windows')
    input('Copy the account private key in your wallet app, then return here and press Enter. Do not paste it here: ')
    import tkinter
    try:
        root = tkinter.Tk()
        root.withdraw()
        try:
            value = root.clipboard_get().strip()
            root.clipboard_clear()
            root.update()
        finally:
            root.destroy()
    except tkinter.TclError as exc:
        raise RuntimeError('Clipboard text is unavailable') from exc
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}', value):
        raise RuntimeError('Clipboard did not contain a 64-digit hexadecimal account private key')
    return value


class Handler(BaseHTTPRequestHandler):
    def send_data(self, payload: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data: dict, status: int = 200):
        self.send_data(json.dumps(data, allow_nan=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            self.send_json({'error': 'Invalid host'}, 403)
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            self.send_json(bot.snapshot())
            return
        if path == "/":
            path = "/dashboard.html"
        if path not in ("/dashboard.html", "/styles.css", "/dashboard.js"):
            self.send_json({"error": "Not found"}, 404)
            return
        file = ROOT / path.lstrip("/")
        data = file.read_bytes().replace(b'__CONTROL_TOKEN__', CONTROL_TOKEN.encode()) if file.suffix == '.html' else file.read_bytes()
        self.send_data(data, (mimetypes.guess_type(file.name)[0] or 'text/plain') + '; charset=utf-8')

    def do_POST(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}') or self.headers.get('X-Orbit-Token') != CONTROL_TOKEN:
            self.send_json({'error': 'Invalid control token or host'}, 403)
            return
        path = urlsplit(self.path).path
        if path not in ("/api/pause", "/api/resume"):
            self.send_json({"error": "Not found"}, 404)
            return
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            self.send_json({"error": "Invalid origin"}, 403)
            return
        try:
            bot.set_paused(path == "/api/pause")
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 409)
            return
        self.send_json({"ok": True, "paused": path == "/api/pause"})

    def log_message(self, format, *args):
        if not self.path.startswith("/api/state"):
            super().log_message(format, *args)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(worker):
    # Bind first: a second launch must never start an order worker before failing on the port.
    server = LocalServer(('127.0.0.1', PORT), Handler)
    try:
        worker.start()
        print(f'Orbit {worker.mode.upper()} dashboard: http://127.0.0.1:{PORT}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop_event.set()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['paper', 'live'], default='paper')
    parser.add_argument('--accept-loss-risk', action='store_true')
    parser.add_argument('--expected-wallet', help='Public 0x address that the local signing key must match')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--key-from-clipboard', action='store_true', help='Windows: read and clear a copied private key after Enter')
    parser.add_argument('--data-dir', type=Path, default=ROOT)
    parser.add_argument('--enable-experimental-trend', action='store_true',
                        help='Allow new trend positions; the reference backtest is unprofitable')
    parser.add_argument('--equity-floor', type=float, default=17.0,
                        help='USD account stop trigger; the existing 5%% guard can stop earlier (default: 17)')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    if args.key_from_clipboard and (args.mode != 'live' or not args.expected_wallet):
        parser.error('Clipboard key input requires live mode and --expected-wallet')
    PORT = args.port
    if args.mode == 'live' and not args.accept_loss_risk:
        parser.error('Live trading can lose funds. Use --accept-loss-risk only after reviewing the tests and README.')
    args.data_dir.mkdir(parents=True, exist_ok=True)
    # No key is accepted over HTTP or written into the repository. Never paste a seed phrase here.
    try:
        key = (key_from_clipboard() if args.key_from_clipboard else
               (os.environ.pop('BOT_PRIVATE_KEY', None) or getpass.getpass('Dedicated bot wallet private key (hidden): '))) if args.mode == 'live' else None
    except (RuntimeError, EOFError) as exc:
        parser.exit(2, f'Unable to read a valid key: {exc}. No order worker started.\n')
    try:
        bot = TradingBot(args.mode, key, args.data_dir, args.enable_experimental_trend, args.equity_floor)
    except Exception:
        parser.exit(2, 'Unable to initialize the wallet or ledger. Check local configuration; no order worker started.\n')
    key = None
    if args.mode == 'live' and args.expected_wallet and bot.executor.address.lower() != args.expected_wallet.lower():
        parser.exit(2, 'Signing key does not match the expected public wallet. No order worker started.\n')
    try:
        serve(bot)
    except OSError:
        parser.exit(2, 'Dashboard port is unavailable. Stop the existing bot first; no new worker started.\n')
