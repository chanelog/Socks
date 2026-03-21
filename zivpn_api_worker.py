#!/usr/bin/env python3
# ============================================================
#   OGH-ZIV API Worker — Dijalankan di VPS Remote (SG/Indo)
#   Bot Telegram (Master) mengirim perintah ke file ini
#   via HTTP POST ke port 8765
#
#   Install di VPS SG:
#   pip3 install --break-system-packages flask
#   python3 zivpn_api_worker.py
#
#   Atau jalankan sebagai service systemd (lihat bagian bawah)
# ============================================================

import json
import subprocess
import os
import re
import random
import string
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Konfigurasi Worker ────────────────────────────────────────
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8765
API_KEY     = "GANTI_API_KEY_RAHASIA_INI"   # ← Samakan dengan bot!

# ── Path file (sama seperti di VPS ini) ──────────────────────
USERS_DB    = "/etc/zivpn/users.db"
DOMAIN_CONF = "/etc/zivpn/domain.conf"
MLDB        = "/etc/zivpn/maxlogin.db"

# ── Helper ────────────────────────────────────────────────────
def get_ip() -> str:
    try:
        import urllib.request
        return urllib.request.urlopen(
            "https://api.ipify.org", timeout=5
        ).read().decode().strip()
    except:
        import socket
        return socket.gethostbyname(socket.gethostname())

def get_domain() -> str:
    if Path(DOMAIN_CONF).exists():
        return Path(DOMAIN_CONF).read_text().strip()
    return get_ip()

def get_port() -> str:
    cfg = "/etc/zivpn/config.json"
    if Path(cfg).exists():
        try:
            data = json.loads(Path(cfg).read_text())
            return data.get("listen", ":5667").lstrip(":")
        except: pass
    return "5667"

def create_account(username, password, days, kuota, maxlogin, note="-"):
    exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    Path(USERS_DB).parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_DB, "a") as f:
        f.write(f"{username}|{password}|{exp}|{kuota}|{note}\n")
    # maxlogin
    mldb  = Path(MLDB)
    lines = mldb.read_text().splitlines() if mldb.exists() else []
    lines = [l for l in lines if not l.startswith(f"{username}|")]
    lines.append(f"{username}|{maxlogin}")
    mldb.write_text("\n".join(lines) + "\n")
    _reload_pw()
    return {
        "username": username, "password": password, "exp": exp,
        "ip": get_ip(), "domain": get_domain(), "port": get_port(),
        "kuota": "Unlimited" if kuota == 0 else f"{kuota} GB",
        "maxlogin": maxlogin, "note": note,
    }

def delete_account(username):
    if not Path(USERS_DB).exists(): return False
    lines     = Path(USERS_DB).read_text().splitlines()
    new_lines = [l for l in lines if not l.startswith(f"{username}|")]
    if len(new_lines) == len(lines): return False
    Path(USERS_DB).write_text("\n".join(new_lines) + "\n" if new_lines else "")
    if Path(MLDB).exists():
        ml = [l for l in Path(MLDB).read_text().splitlines() if not l.startswith(f"{username}|")]
        Path(MLDB).write_text("\n".join(ml) + "\n")
    _reload_pw()
    return True

def list_accounts():
    if not Path(USERS_DB).exists(): return []
    today  = datetime.now().strftime("%Y-%m-%d")
    result = []
    for line in Path(USERS_DB).read_text().splitlines():
        if not line.strip(): continue
        parts = line.split("|")
        if len(parts) >= 3:
            result.append({
                "username": parts[0],
                "exp":      parts[2],
                "status":   "aktif" if parts[2] >= today else "expired"
            })
    return result

def get_info():
    today   = datetime.now().strftime("%Y-%m-%d")
    total   = 0
    aktif   = 0
    if Path(USERS_DB).exists():
        for line in Path(USERS_DB).read_text().splitlines():
            if not line.strip(): continue
            parts = line.split("|")
            if len(parts) >= 3:
                total += 1
                if parts[2] >= today: aktif += 1
    return {
        "ok":         True,
        "ip":         get_ip(),
        "domain":     get_domain(),
        "port":       get_port(),
        "total_akun": total,
        "aktif_akun": aktif,
        "expired":    total - aktif,
    }

def _reload_pw():
    cfg_file = "/etc/zivpn/config.json"
    if not Path(USERS_DB).exists() or not Path(cfg_file).exists(): return
    try:
        pws = []
        for line in Path(USERS_DB).read_text().splitlines():
            parts = line.split("|")
            if len(parts) >= 2: pws.append(f'"{parts[1]}"')
        data = json.loads(Path(cfg_file).read_text())
        data["auth"]["config"] = json.loads(f"[{','.join(pws)}]")
        Path(cfg_file).write_text(json.dumps(data, indent=2))
        subprocess.run(["systemctl", "restart", "zivpn"], capture_output=True, timeout=10)
    except Exception as e:
        print(f"[WARN] reload_pw error: {e}")

# ── HTTP Request Handler ──────────────────────────────────────
class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}")

    def do_POST(self):
        if self.path != "/api":
            self._send(404, {"ok": False, "error": "Not found"})
            return

        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._send(400, {"ok": False, "error": "Invalid JSON"})
            return

        # Validasi API Key
        if data.get("key") != API_KEY:
            self._send(403, {"ok": False, "error": "API key salah"})
            return

        action = data.get("action", "")
        print(f"[API] action={action}")

        try:
            if action == "create_account":
                akun = create_account(
                    data["username"], data["password"],
                    int(data.get("days", 30)),
                    int(data.get("kuota", 0)),
                    int(data.get("maxlogin", 2)),
                    data.get("note", "-")
                )
                self._send(200, {"ok": True, "akun": akun})

            elif action == "delete_account":
                ok = delete_account(data["username"])
                self._send(200, {"ok": ok, "error": "" if ok else "User tidak ditemukan"})

            elif action == "list_accounts":
                self._send(200, {"ok": True, "accounts": list_accounts()})

            elif action == "get_info":
                self._send(200, get_info())

            elif action == "restart_service":
                subprocess.run(["systemctl", "restart", "zivpn"], timeout=15, capture_output=True)
                self._send(200, {"ok": True, "message": "Service ZIVPN di-restart"})

            else:
                self._send(400, {"ok": False, "error": f"Action tidak dikenal: {action}"})

        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════╗
║   OGH-ZIV API Worker — VPS Remote               ║
╠══════════════════════════════════════════════════╣
║  Listen : {LISTEN_HOST}:{LISTEN_PORT}
║  API Key: {API_KEY[:6]}... (jaga kerahasiaannya!)
╚══════════════════════════════════════════════════╝
""")
    srv = HTTPServer((LISTEN_HOST, LISTEN_PORT), APIHandler)
    print(f"[INFO] API Worker berjalan di port {LISTEN_PORT}...")
    srv.serve_forever()

# ── Cara install sebagai systemd service ─────────────────────
# sudo cp zivpn_api_worker.py /usr/local/bin/zivpn-api-worker.py
# sudo chmod +x /usr/local/bin/zivpn-api-worker.py
#
# Buat file: /etc/systemd/system/zivpn-api-worker.service
# [Unit]
# Description=OGH-ZIV API Worker
# After=network.target
#
# [Service]
# ExecStart=/usr/bin/python3 /usr/local/bin/zivpn-api-worker.py
# Restart=always
# RestartSec=5
#
# [Install]
# WantedBy=multi-user.target
#
# sudo systemctl enable zivpn-api-worker --now
