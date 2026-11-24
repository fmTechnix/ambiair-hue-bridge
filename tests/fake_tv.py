"""Simulierter Philips-TV: Einrichtung wie AmbiAirManager, dann UDP-Frames."""
import json, socket, sys, time, urllib.request
sys.path.insert(0, sys.argv[1])
from ambiair_hue_bridge import build_frame

HOST = "127.0.0.1"
PORT = int(sys.argv[2])
BASE = f"http://{HOST}:{PORT}/1/ambiair/multicast"
KEY = "02A1C0A8B2C81234"   # 12 Hex (MAC) + 4 Ziffern, wie GenerateSecretAirKey


def post(path, obj):
    # wie HttpChannel.executePostRequest: JSON roh in der URL, leerer Body
    url = f"{BASE}/{path}/post_value=" + json.dumps(obj, separators=(",", ":"))
    url = url.replace('"', "%22").replace(" ", "%20")
    r = urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=3)
    return r.read().decode()


cfg = urllib.request.urlopen(BASE + "/config", timeout=3).read().decode()
print("TV config:", cfg)
c = json.loads(cfg[cfg.index("{"):cfg.rindex("}") + 1])
assert c["capability"] and c["multicast"] and "MAC address" in c and "status" in c
for path, obj in [("key", {"key": KEY}), ("checkkey", {"key": KEY}),
                  ("config", {"key": KEY, "status": {"angle": "Left 1 (L1)", "brightness": 7}}),
                  ("configured", {"key": KEY, "configured": 1}),
                  ("stream", {"key": KEY, "status": True})]:
    res = post(path, obj)
    assert "success" in res, (path, res)
    print("TV", path, "->", res)
r = urllib.request.urlopen(urllib.request.Request(
    f"http://{HOST}:{PORT}/1/ambiair/light/state/post_value=%7B%22alert%22:%22select%22%7D",
    data=b"", method="POST"), timeout=3).read().decode()
print("TV blink ->", r)

u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Fremder Schlüssel muss ignoriert werden
u.sendto(build_frame("XXXXXXXXXXXXXXXX", [(65535, 0, 0)] * 10), (HOST, 2930))
t0 = time.time()
n = 0
while time.time() - t0 < 3:
    k = n % 84
    # Links rot -> Rechts blau, oben grün
    cols = []
    for i in range(10):
        r = 0xFF00 if i in (0, 1, 2) else 0x0100
        g = 0xFF00 if i in (3, 4, 5) else 0x0100
        b = 0xFF00 if i in (6, 7, 8) else 0x0100
        cols.append((r, g, b))
    u.sendto(build_frame(KEY, cols), (HOST, 2930))
    n += 1
    time.sleep(0.035)
print("TV hat", n, "Frames gesendet, warte auf Pause …")
time.sleep(5)
print("TV fertig")
