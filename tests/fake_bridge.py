"""Simulierte Hue-Bridge: HTTPS-REST (443) + DTLS-Entertainment (2100)."""
import json, socket, ssl, struct, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mbedtls import tls

APP_KEY, APP_ID = "testappkey", "test-app-id-1234"
CLIENT_KEY = "00112233445566778899AABBCCDDEEFF"
CFG_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ENT = {"data": [{"id": CFG_ID, "metadata": {"name": "Entertainment-Bereich 1"},
       "channels": [
           {"channel_id": 0, "position": {"x": -0.9, "y": 0.8, "z": 0.0},
            "members": [{"service": {"rid": "ent-1", "rtype": "entertainment"}}]},
           {"channel_id": 1, "position": {"x": 0.7, "y": 0.2, "z": 0.9},
            "members": [{"service": {"rid": "ent-2", "rtype": "entertainment"}}]}],
       "light_services": [{"rid": "light-1"}, {"rid": "light-2"}]}]}
state = {"active": False}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _j(self, obj, extra=None):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        assert self.headers.get("hue-application-key") == APP_KEY, "falscher key"
        p = self.path
        if p == "/auth/v1":
            return self._j({}, {"hue-application-id": APP_ID})
        if p.endswith("/entertainment_configuration"):
            return self._j(ENT)
        if p.endswith("/entertainment"):
            return self._j({"data": [{"id": "ent-1", "owner": {"rid": "dev-1"}},
                                     {"id": "ent-2", "owner": {"rid": "dev-2"}}]})
        if p.endswith("/device"):
            return self._j({"data": [{"id": "dev-1", "metadata": {"name": "Hue Flux strip light 1"}},
                                     {"id": "dev-2", "metadata": {"name": "Ambiente Esstisch"}}]})
        if p.endswith("/light"):
            return self._j({"data": [{"id": "light-1", "owner": {"rid": "dev-1"}},
                                     {"id": "light-2", "owner": {"rid": "dev-2"}}]})
        self._j({"errors": ["404"]})

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        print("BRIDGE PUT", self.path.rsplit("/", 1)[-1], body, flush=True)
        if body.get("action") == "start": state["active"] = True
        if body.get("action") == "stop": state["active"] = False
        self._j({"data": [], "errors": []})


def https():
    srv = ThreadingHTTPServer(("127.0.0.1", 443), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(sys.argv[1], sys.argv[2])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()


def block(f, *a):
    while True:
        try:
            return f(*a)
        except (tls.WantReadError, tls.WantWriteError):
            pass


def dtls():
    conf = tls.DTLSConfiguration(pre_shared_key_store={APP_ID: bytes.fromhex(CLIENT_KEY)},
                                 ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
                                 validate_certificates=False)
    while True:
        s = tls.ServerContext(conf).wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 2100))
        conn, addr = s.accept()
        conn.setcookieparam(addr[0].encode())
        try:
            block(conn.do_handshake)
        except tls.HelloVerifyRequest:
            pass
        conn, addr = conn.accept()
        conn.setcookieparam(addr[0].encode())
        block(conn.do_handshake)
        print("BRIDGE DTLS-Handshake OK, Identität korrekt", flush=True)
        n = 0
        conn.settimeout(4)
        try:
            while True:
                d = block(conn.recv, 4096)
                if not d: break
                n += 1
                assert d[:9] == b"HueStream" and d[9] == 2, "falscher Header"
                cfg = d[16:52].decode()
                assert cfg == CFG_ID, cfg
                chans = [struct.unpack(">BHHH", d[52 + 7*i:59 + 7*i]) for i in range((len(d) - 52)//7)]
                if n % 10 == 1:
                    print(f"BRIDGE Frame {n} seq={d[11]} active={state['active']} " +
                          " ".join(f"ch{c}=#{r>>8:02x}{g>>8:02x}{b>>8:02x}" for c, r, g, b in chans), flush=True)
        except Exception as e:
            print("BRIDGE Verbindung zu:", type(e).__name__, "nach", n, "Frames", flush=True)
        s.close()


threading.Thread(target=https, daemon=True).start()
dtls()
