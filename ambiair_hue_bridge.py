#!/usr/bin/env python3
"""
ambiair-hue-bridge – Philips Ambilight (AmbiAir) -> Philips Hue Entertainment

Not affiliated with, endorsed by or sponsored by TP Vision, Philips or Signify.
Ambilight and Hue are trademarks of their respective owners.

Gibt sich gegenüber einem Philips Google TV als AmbiAir-Lautsprecher aus,
empfängt die vom Ambilight-Chip berechneten Farben (UDP, ca. 28 Bilder/s)
und streamt sie über die Hue Entertainment API an einen Entertainment-Bereich.

Protokoll (aus org.droidtv.ambiair rekonstruiert):
  Suche:   mDNS  _tpv_al._tcp, Dienstname muss "tpv_" enthalten
  Setup:   HTTP  :80  /1/ambiair/multicast/{config|key|checkkey|clearkey|
                      configured|stream}/post_value=<json>
  Farben:  UDP   224.8.0.8:2920 (Multicast) und <unsere IP>:2930 (Unicast)
           120 Byte: "AmbilightAir" 01 00 | 16 Byte Schlüssel |
           10 x [00 00 id | R16 G16 B16]  (Big Endian)
"""
import argparse
import json
import logging
import math
import os
import select
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

log = logging.getLogger("ambiair-hue-bridge")

# --------------------------------------------------------------------------
# AmbiAir: Positionen rund um den Fernseher (Reihenfolge = Slot im Paket)
# --------------------------------------------------------------------------
SLOTS = ["BottomLeft", "LeftDown", "LeftUp", "TopLeft", "TopMiddle",
         "TopRight", "RightUp", "RightDown", "BottomRight", "BottomMiddle"]
# Blick auf den Fernseher: x -1 links .. 1 rechts, y -1 unten .. 1 oben
SLOT_POS = {
    "BottomLeft": (-1.0, -1.0), "LeftDown": (-1.0, -0.4), "LeftUp": (-1.0, 0.4),
    "TopLeft": (-0.6, 1.0), "TopMiddle": (0.0, 1.0), "TopRight": (0.6, 1.0),
    "RightUp": (1.0, 0.4), "RightDown": (1.0, -0.4), "BottomRight": (1.0, -1.0),
    "BottomMiddle": (0.0, -1.0),
}
MCAST_GROUP, MCAST_PORT, UCAST_PORT = "224.8.0.8", 2920, 2930
PACKET_LEN = 120


def parse_frame(data: bytes):
    """Liefert (schlüssel, [(r,g,b) x10] als 16-Bit) oder None."""
    if len(data) < PACKET_LEN or data[:12] != b"AmbilightAir":
        return None
    key = data[14:30].decode("ascii", "replace")
    colors = []
    for i in range(10):
        b = 33 + 9 * i
        colors.append(struct.unpack(">HHH", data[b:b + 6]))
    return key, colors


def build_frame(key: str, colors) -> bytes:
    """Gegenstück zu parse_frame (für Tests / Simulation)."""
    pkt = bytearray(PACKET_LEN)
    pkt[0:12] = b"AmbilightAir"
    pkt[12] = 1
    pkt[14:30] = key.encode()[:16].ljust(16, b"0")
    for i, (r, g, b) in enumerate(colors[:10]):
        pkt[32 + 9 * i] = i + 1
        pkt[33 + 9 * i:39 + 9 * i] = struct.pack(">HHH", r, g, b)
    return bytes(pkt)


# --------------------------------------------------------------------------
# Zustand (Schlüssel, Position …) dauerhaft speichern
# --------------------------------------------------------------------------
class State:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"key": "", "configured": 0, "angle": "Left 1 (L1)",
                     "brightness": 5, "stream": False}
        try:
            with open(path) as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def get(self, k):
        with self.lock:
            return self.data.get(k)

    def update(self, **kw):
        with self.lock:
            self.data.update(kw)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)


# --------------------------------------------------------------------------
# AmbiAir-HTTP-Server (Port 80) – beantwortet die Einrichtung durch den TV
# --------------------------------------------------------------------------
def make_handler(state: State, mac: str, on_identify):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AmbiAir/1.0"

        def log_message(self, fmt, *args):
            log.debug("HTTP %s " + fmt, self.client_address[0], *args)

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _config(self):
            return {"capability": True, "multicast": True,
                    "speaker type": "playFi", "MAC address": mac,
                    "configured": int(state.get("configured") or 0),
                    "status": {"angle": state.get("angle"),
                               "brightness": int(state.get("brightness") or 5)}}

        def _payload(self):
            raw = urllib.parse.unquote(self.path)
            if "post_value=" not in raw:
                return raw, {}
            route, _, js = raw.partition("/post_value=")
            # Länge auch aus einem eventuellen Body lesen (für den Fall der Fälle)
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            try:
                return route, json.loads(js)
            except ValueError:
                return route, {}

        def do_GET(self):
            path = urllib.parse.unquote(self.path).rstrip("/")
            if path.endswith("/config"):
                log.info("TV %s fragt Konfiguration ab", self.client_address[0])
                return self._send(self._config())
            self._send({"error": "unknown"}, 404)

        def do_POST(self):
            route, p = self._payload()
            ep = route.rstrip("/").rsplit("/", 1)[-1]
            ip = self.client_address[0]
            if ep == "key":
                state.update(key=p.get("key", ""))
                log.info("TV %s hat Schlüssel übergeben: %s", ip, p.get("key"))
            elif ep == "checkkey":
                log.info("TV %s prüft Schlüssel", ip)
            elif ep == "clearkey":
                state.update(key="", configured=0, stream=False)
                log.info("TV %s hat die Kopplung aufgehoben", ip)
            elif ep == "configured":
                state.update(configured=int(p.get("configured", 1)))
                log.info("TV %s: eingerichtet = %s", ip, p.get("configured"))
            elif ep == "config":
                st = p.get("status") or {}
                state.update(angle=st.get("angle", state.get("angle")),
                             brightness=st.get("brightness", state.get("brightness")))
                log.info("TV %s: Position %s, Helligkeit %s", ip,
                         st.get("angle"), st.get("brightness"))
            elif ep == "stream":
                state.update(stream=bool(p.get("status")))
                log.info("TV %s: Streaming %s", ip, "AN" if p.get("status") else "AUS")
            elif ep == "state":   # .../light/state  -> Lampe blinken lassen
                log.info("TV %s möchte den Lautsprecher blinken lassen", ip)
                threading.Thread(target=on_identify, daemon=True).start()
            else:
                log.info("TV %s: unbekannter Aufruf %s %s", ip, route, p)
            self._send({"success": True})

        do_PUT = do_POST

    return Handler


def advertise(name: str, host_ip: str):
    from zeroconf import ServiceInfo, Zeroconf
    zc = Zeroconf(interfaces=[host_ip])
    svc = f"tpv_{name}"
    info = ServiceInfo("_tpv_al._tcp.local.", f"{svc}._tpv_al._tcp.local.",
                       addresses=[socket.inet_aton(host_ip)], port=80,
                       properties={"name": name},
                       server=f"ambiair-hue-{socket.gethostname()}.local.")
    # Philips nutzt "_tpv_al" – Unterstrich im Typnamen ist nicht RFC-konform
    zc.register_service(info, strict=False)
    log.info("Im Netz angekündigt als '%s' (%s:80)", svc, host_ip)
    return zc, info


# --------------------------------------------------------------------------
# Philips Hue: REST (v2) + Entertainment-Streaming (DTLS)
# --------------------------------------------------------------------------
_NOVERIFY = ssl.create_default_context()
_NOVERIFY.check_hostname = False
_NOVERIFY.verify_mode = ssl.CERT_NONE


def http_json(method, url, body=None, headers=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, context=_NOVERIFY, timeout=timeout) as r:
        return json.loads(r.read() or b"null"), r.headers


def discover_bridges(wait=4.0):
    """Hue-Bridges per mDNS (_hue._tcp) finden."""
    from zeroconf import ServiceBrowser, Zeroconf
    found = {}

    class L:
        def add_service(self, zc, t, n):
            i = zc.get_service_info(t, n)
            if i and i.parsed_addresses():
                found[n] = i.parsed_addresses()[0]

        def update_service(self, *a):
            pass

        def remove_service(self, *a):
            pass

    zc = Zeroconf()
    ServiceBrowser(zc, "_hue._tcp.local.", L())
    time.sleep(wait)
    zc.close()
    return sorted(set(found.values()))


class HueBridge:
    def __init__(self, ip, app_key, client_key):
        self.ip, self.app_key, self.client_key = ip, app_key, client_key
        self.base = f"https://{ip}"

    def _h(self):
        return {"hue-application-key": self.app_key}

    def get(self, path):
        return http_json("GET", self.base + path, headers=self._h())[0]

    def put(self, path, body):
        return http_json("PUT", self.base + path, body, headers=self._h())[0]

    def app_id(self):
        _, hdr = http_json("GET", self.base + "/auth/v1", headers=self._h())
        return hdr.get("hue-application-id")

    def ent_configs(self):
        return self.get("/clip/v2/resource/entertainment_configuration")["data"]

    def find_config(self, name):
        cfgs = self.ent_configs()
        for c in cfgs:
            if not name or c["metadata"]["name"] == name or c["id"] == name:
                return c
        raise SystemExit(f"Entertainment-Bereich '{name}' nicht gefunden. "
                         f"Vorhanden: {[c['metadata']['name'] for c in cfgs]}")

    def channel_names(self, cfg):
        """channel_id -> Lampenname (über entertainment-Dienst -> Gerät)."""
        ents = {e["id"]: e["owner"]["rid"] for e in
                self.get("/clip/v2/resource/entertainment")["data"]}
        devs = {d["id"]: d["metadata"]["name"] for d in
                self.get("/clip/v2/resource/device")["data"]}
        names = {}
        for ch in cfg["channels"]:
            n = []
            for m in ch.get("members", []):
                dev = ents.get(m["service"]["rid"])
                n.append(devs.get(dev, "?"))
            names[ch["channel_id"]] = " + ".join(n) or f"Kanal {ch['channel_id']}"
        return names

    def light_ids(self, cfg):
        """Licht-IDs im Bereich (für 'identify')."""
        ents = {e["id"]: e["owner"]["rid"] for e in
                self.get("/clip/v2/resource/entertainment")["data"]}
        lights = self.get("/clip/v2/resource/light")["data"]
        owners = {ents.get(lr["rid"]) for lr in cfg.get("light_services", [])}
        if not owners - {None}:
            owners = {ents.get(m["service"]["rid"]) for ch in cfg["channels"]
                      for m in ch.get("members", [])}
        return [l["id"] for l in lights if l["owner"]["rid"] in owners]


def pair(ip=None):
    if not ip:
        print("Suche Hue-Bridge im Netz …")
        ips = discover_bridges()
        if not ips:
            raise SystemExit("Keine Bridge gefunden – bitte --bridge <IP> angeben.")
        ip = ips[0]
        print(f"Gefunden: {ip}")
    input(f"Drück jetzt den runden Knopf auf der Hue-Bridge ({ip}) "
          "und dann hier Enter … ")
    res, _ = http_json("POST", f"https://{ip}/api",
                       {"devicetype": "ambiair-hue-bridge#server", "generateclientkey": True})
    r = res[0]
    if "error" in r:
        raise SystemExit(f"Fehler von der Bridge: {r['error'].get('description')}")
    s = r["success"]
    print("\nGekoppelt! Trag das in deine config.yaml ein:\n")
    print(f"hue:\n  bridge_ip: {ip}\n  app_key: {s['username']}\n"
          f"  client_key: {s['clientkey']}")
    b = HueBridge(ip, s["username"], s["clientkey"])
    print("\nEntertainment-Bereiche:")
    for c in b.ent_configs():
        print(f"  - {c['metadata']['name']}  ({len(c['channels'])} Kanäle)")


class HueStreamer:
    """Entertainment-Streaming über DTLS 1.2 (PSK) an Port 2100."""

    def __init__(self, bridge: HueBridge, cfg_id: str):
        self.bridge, self.cfg_id = bridge, cfg_id
        self.sock, self.seq = None, 0
        self.identity = None

    def start(self):
        from mbedtls import tls
        if not self.identity:
            self.identity = self.bridge.app_id() or self.bridge.app_key
        self.bridge.put(f"/clip/v2/resource/entertainment_configuration/{self.cfg_id}",
                        {"action": "start"})
        conf = tls.DTLSConfiguration(
            pre_shared_key=(self.identity, bytes.fromhex(self.bridge.client_key)),
            ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
            validate_certificates=False,
            lowest_supported_version=tls.DTLSVersion.DTLSv1_2,
            highest_supported_version=tls.DTLSVersion.DTLSv1_2,
            handshake_timeout_max=10.0)
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw.settimeout(10)
        s = tls.ClientContext(conf).wrap_socket(raw, server_hostname=None)
        s.connect((self.bridge.ip, 2100))
        deadline = time.time() + 10
        while True:
            try:
                s.do_handshake()
                break
            except (tls.WantReadError, tls.WantWriteError):
                if time.time() > deadline:
                    raise TimeoutError("DTLS-Handshake mit der Bridge fehlgeschlagen")
        self.sock = s
        log.info("Hue-Entertainment-Streaming gestartet")

    def send(self, channels: dict):
        hdr = (b"HueStream" + bytes([2, 0, self.seq & 0xFF, 0, 0, 0, 0])
               + self.cfg_id.encode())
        body = b"".join(struct.pack(">BHHH", ch, *rgb)
                        for ch, rgb in channels.items())
        self.seq += 1
        self.sock.send(hdr + body)

    def stop(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        try:
            self.bridge.put(f"/clip/v2/resource/entertainment_configuration/{self.cfg_id}",
                            {"action": "stop"})
        except Exception as e:
            log.debug("Stop fehlgeschlagen: %s", e)
        log.info("Hue-Entertainment-Streaming beendet")


def build_mapping(cfg, manual: dict):
    """channel_id -> Liste von Slot-Indizes."""
    mapping = {}
    for ch in cfg["channels"]:
        cid = ch["channel_id"]
        if cid in manual or str(cid) in manual:
            want = manual.get(cid, manual.get(str(cid)))
            want = [want] if isinstance(want, str) else list(want)
            mapping[cid] = [SLOTS.index(w) for w in want]
            continue
        p = ch.get("position", {})
        x, z = p.get("x", 0.0), p.get("z", 0.0)   # Hue: x links/rechts, z unten/oben
        best = min(SLOTS, key=lambda s: math.dist((x, z), SLOT_POS[s]))
        mapping[cid] = [SLOTS.index(best)]
    return mapping


# --------------------------------------------------------------------------
# Hauptschleife: UDP empfangen -> auf Kanäle abbilden -> an Hue senden
# --------------------------------------------------------------------------
def local_ip_towards(target):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def open_receivers(host_ip):
    mc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mc.bind(("", MCAST_PORT))
    mreq = socket.inet_aton(MCAST_GROUP) + socket.inet_aton(host_ip)
    try:
        mc.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        log.warning("Multicast-Beitritt fehlgeschlagen (%s) – nutze nur Unicast", e)
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    uc.bind(("", UCAST_PORT))
    return mc, uc


def run(cfg, dry_run=False):
    tv_ip = cfg.get("tv_ip") or "192.168.178.1"
    host_ip = cfg.get("host_ip") or "auto"
    if host_ip == "auto":
        host_ip = local_ip_towards(tv_ip)
    state = State(cfg.get("state_file", "ambiair_hue_state.json"))
    mac = cfg.get("mac") or ":".join(
        f"{b:02X}" for b in (0x02, 0xA1, *socket.inet_aton(host_ip)))

    bridge = streamer = None
    mapping, names, light_ids = {}, {}, []
    if not dry_run:
        h = cfg["hue"]
        bridge = HueBridge(h["bridge_ip"], h["app_key"], h["client_key"])
        ent = bridge.find_config(h.get("entertainment_area"))
        mapping = build_mapping(ent, cfg.get("mapping") or {})
        names = bridge.channel_names(ent)
        light_ids = bridge.light_ids(ent)
        streamer = HueStreamer(bridge, ent["id"])
        log.info("Entertainment-Bereich: %s", ent["metadata"]["name"])
        for cid, slots in mapping.items():
            log.info("  Kanal %d (%s) <- %s", cid, names.get(cid),
                     ", ".join(SLOTS[s] for s in slots))

    def identify():
        if not bridge:
            log.info("(Testmodus) Lampen würden jetzt blinken")
            return
        for lid in light_ids:
            try:
                bridge.put(f"/clip/v2/resource/light/{lid}",
                           {"identify": {"action": "identify"}})
            except Exception as e:
                log.debug("identify %s: %s", lid, e)

    httpd = ThreadingHTTPServer(("", int(cfg.get("http_port", 80))),
                                make_handler(state, mac, identify))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("AmbiAir-API läuft auf %s:%s", host_ip, cfg.get("http_port", 80))

    zc = None
    if cfg.get("mdns", True):
        zc, info = advertise(cfg.get("name", "Hue Bridge"), host_ip)

    mc, uc = open_receivers(host_ip)
    bright = float(cfg.get("brightness", 1.0))
    smooth = min(max(float(cfg.get("smoothing", 0.0)), 0.0), 0.95)
    timeout = float(cfg.get("timeout", 3.0))
    last_frame = last_ucast = 0.0
    streaming = False
    smoothed = {}
    frames = 0
    log.info("Warte auf Ambilight-Farben vom Fernseher …")

    try:
        while True:
            r, _, _ = select.select([mc, uc], [], [], 1.0)
            now = time.time()
            if streaming and now - last_frame > timeout:
                log.info("Keine Farben mehr seit %.0f s – pausiere", timeout)
                if streamer:
                    streamer.stop()
                streaming = False
            for s in r:
                data, src = s.recvfrom(2048)
                if s is uc:
                    last_ucast = now
                elif now - last_ucast < 1.0:
                    continue          # gleiches Bild kam schon per Unicast
                fr = parse_frame(data)
                if not fr:
                    continue
                key, colors = fr
                want = state.get("key")
                if want and key != want and not cfg.get("ignore_key", False):
                    log.debug("Paket mit fremdem Schlüssel von %s ignoriert", src[0])
                    continue
                last_frame = now
                frames += 1
                if not streaming:
                    log.info("Ambilight-Farben empfangen von %s", src[0])
                    if streamer:
                        try:
                            streamer.start()
                        except Exception as e:
                            log.error("Hue-Start fehlgeschlagen: %s", e)
                            time.sleep(2)
                            continue
                    streaming = True
                if dry_run:
                    if frames % 28 == 1:
                        log.info("Farben: %s", " ".join(
                            f"{SLOTS[i][:6]}=#{c[0]>>8:02x}{c[1]>>8:02x}{c[2]>>8:02x}"
                            for i, c in enumerate(colors)))
                    continue
                out = {}
                for cid, slots in mapping.items():
                    rgb = [sum(colors[i][k] for i in slots) / len(slots) for k in range(3)]
                    if smooth:
                        prev = smoothed.get(cid, rgb)
                        rgb = [prev[k] * smooth + rgb[k] * (1 - smooth) for k in range(3)]
                        smoothed[cid] = rgb
                    out[cid] = tuple(min(65535, int(v * bright)) for v in rgb)
                try:
                    streamer.send(out)
                except Exception as e:
                    log.warning("Senden an Hue fehlgeschlagen (%s) – starte neu", e)
                    streamer.stop()
                    streaming = False
    except KeyboardInterrupt:
        pass
    finally:
        if streaming and streamer:
            streamer.stop()
        if zc:
            zc.unregister_service(info)
            zc.close()
        httpd.shutdown()


def main():
    ap = argparse.ArgumentParser(description="Philips Ambilight -> Philips Hue")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--pair", action="store_true", help="Mit der Hue-Bridge koppeln")
    ap.add_argument("--bridge", help="IP der Hue-Bridge (für --pair)")
    ap.add_argument("--list", action="store_true",
                    help="Entertainment-Bereiche und Zuordnung anzeigen")
    ap.add_argument("--dry-run", action="store_true",
                    help="Ohne Hue: empfangene Farben nur anzeigen")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("zeroconf").setLevel(logging.WARNING)

    if a.pair:
        return pair(a.bridge)
    try:
        with open(a.config) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        if not a.dry_run:
            raise SystemExit(f"{a.config} fehlt – kopier config.example.yaml")
        cfg = {}
    if a.list:
        h = cfg["hue"]
        b = HueBridge(h["bridge_ip"], h["app_key"], h["client_key"])
        for c in b.ent_configs():
            print(f"\n{c['metadata']['name']}  (id {c['id']})")
            names = b.channel_names(c)
            for cid, slots in build_mapping(c, cfg.get("mapping") or {}).items():
                p = next(ch["position"] for ch in c["channels"] if ch["channel_id"] == cid)
                print(f"  Kanal {cid}: {names[cid]:<28} Position x={p['x']:+.2f} "
                      f"z={p['z']:+.2f}  ->  {', '.join(SLOTS[s] for s in slots)}")
        return
    run(cfg, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
