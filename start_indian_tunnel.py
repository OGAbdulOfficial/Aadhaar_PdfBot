"""
Aadhaar Bot — Indian Residential Relay Tunnel
=============================================
This script runs on your Indian PC and creates a secure reverse tunnel to your VPS.
Whenever the bot on your VPS requests UIDAI (Captcha/OTP/Download), it routes
through your Indian IP address, bypassing any foreign datacenter blocks!

Usage:
    python start_indian_tunnel.py
"""

import sys
import io
import time
import socket
import threading
import http.server
import socketserver
import urllib.request
import urllib.error
import paramiko

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

LOCAL_PROXY_PORT = 8899
VPS_HOST = "157.173.100.212"
VPS_PORT = 22
VPS_USER = "nagi"
VPS_PASS = "nagi@2010"

class SimpleProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_CONNECT(self):
        # Handle HTTPS tunneling
        host, port = self.path.split(":")
        port = int(port)
        try:
            target_sock = socket.create_connection((host, port), timeout=10)
            self.send_response(200, "Connection Established")
            self.end_headers()
        except Exception as e:
            self.send_error(502, f"Connect error: {e}")
            return

        # Bi-directional stream
        def forward(source, dest):
            try:
                while True:
                    data = source.recv(8192)
                    if not data:
                        break
                    dest.sendall(data)
            except Exception:
                pass
            finally:
                source.close()
                dest.close()

        t1 = threading.Thread(target=forward, args=(self.connection, target_sock), daemon=True)
        t2 = threading.Thread(target=forward, args=(target_sock, self.connection), daemon=True)
        t1.start()
        t2.start()
        t1.join()

    def do_GET(self):
        self._proxy_http()

    def do_POST(self):
        self._proxy_http()

    def _proxy_http(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_len) if content_len > 0 else None
        headers = dict(self.headers)
        headers.pop('Proxy-Connection', None)

        req = urllib.request.Request(self.path, data=post_data, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        # Silent or simple log
        pass

def start_local_proxy():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", LOCAL_PROXY_PORT), SimpleProxyHandler)
    server.serve_forever()

def reverse_forward_tunnel(server_port, remote_host, remote_port, transport):
    transport.request_port_forward("", server_port)
    while True:
        chan = transport.accept(1000)
        if chan is None:
            continue
        thr = threading.Thread(target=handle_reverse_channel, args=(chan, remote_host, remote_port), daemon=True)
        thr.start()

def handle_reverse_channel(chan, host, port):
    sock = socket.socket()
    try:
        sock.connect((host, port))
    except Exception as e:
        chan.close()
        return

    def pipe(src, dst):
        try:
            while True:
                d = src.recv(8192)
                if not d:
                    break
                dst.sendall(d)
        except Exception:
            pass
        finally:
            src.close()
            dst.close()

    t1 = threading.Thread(target=pipe, args=(chan, sock), daemon=True)
    t2 = threading.Thread(target=pipe, args=(sock, chan), daemon=True)
    t1.start()
    t2.start()

def main():
    print("=" * 60)
    print("🇮🇳 Aadhaar Bot — Indian Residential Relay Tunnel")
    print("=" * 60)
    print(f"[*] Starting local HTTP proxy on 127.0.0.1:{LOCAL_PROXY_PORT}...")
    t = threading.Thread(target=start_local_proxy, daemon=True)
    t.start()
    time.sleep(1)

    print(f"[*] Connecting reverse tunnel to VPS {VPS_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    while True:
        try:
            client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
            print(f"[✅] Connected! Forwarding VPS port {LOCAL_PROXY_PORT} -> Local Indian IP.")
            print(f"[*] On VPS .env, set: PROXY_URL=http://127.0.0.1:{LOCAL_PROXY_PORT}")
            print("[*] Tunnel is ACTIVE. Keep this window open.")
            
            transport = client.get_transport()
            reverse_forward_tunnel(LOCAL_PROXY_PORT, "127.0.0.1", LOCAL_PROXY_PORT, transport)
        except KeyboardInterrupt:
            print("\n[!] Stopping tunnel.")
            break
        except Exception as e:
            print(f"[!] Tunnel disconnected ({e}). Reconnecting in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    main()

