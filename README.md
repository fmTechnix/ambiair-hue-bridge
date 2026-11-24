# ambiair-hue-bridge

**Use the Ambilight of your Philips Google TV with *any* Philips Hue lights – no Hue Sync Box, no screen capture, works with Netflix & co.**

🇩🇪 [Deutsche Anleitung](README.de.md)

Philips dropped *Ambilight + Hue* from its newer TVs. They still ship a hidden feature called
**AmbiAir**, which streams the Ambilight colors to Philips wireless speakers with built-in LEDs.
This project pretends to be such a speaker and forwards the colors to a Hue Entertainment area.

```
Philips TV ──AmbiAir (UDP, ~28 fps)──▶ ambiair-hue-bridge ──Hue Entertainment (DTLS)──▶ Hue Bridge ──▶ your lights
```

- The colors come straight from the TV's Ambilight processor. They are **not** taken from screenshots, so **DRM content (Netflix, Disney+, …) works**.
- Runs fully local, no cloud.
- Up to 10 positions around the screen. Lights are mapped automatically based on their placement in the Hue app.
- Hue lights return to their previous state when the TV stops sending.

> **Not affiliated with, endorsed by or sponsored by TP Vision, Philips or Signify.**
> Ambilight and Hue are trademarks of their respective owners. Use at your own risk.

## Tested TVs

| Model | OS | Result |
|---|---|---|
| Philips 65OLED810/12 (2025) | Google TV 14 | ✅ works |

Tried another model? Please open an issue or PR, whether it worked or not.

## Requirements

- Philips TV with the `org.droidtv.ambiair` app (check with ADB: `pm list packages | grep ambiair`)
- Philips Hue Bridge (v2, square) with an **Entertainment area**
- Something always-on in the **same network/VLAN** as TV and bridge: Proxmox LXC, Raspberry Pi, Docker host, …
- Port **80** free on that host (the TV always talks to port 80)
- ADB access to the TV once, to open the hidden setup wizard

## Install

### Option A: Debian/Ubuntu (LXC, Pi, VM)

```bash
git clone https://github.com/fmTechnix/ambiair-hue-bridge.git
cd ambiair-hue-bridge
sudo bash install.sh
```

The installer uses [uv](https://github.com/astral-sh/uv) to set up Python 3.11 (prebuilt `python-mbedtls` wheels) in `/opt/ambiair-hue-bridge` and installs a systemd service.

### Option B: Docker

```bash
mkdir -p data && cp config.example.yaml data/config.yaml
# in data/config.yaml set: state_file: /data/state.json
docker compose run --rm ambiair-hue-bridge --pair   # press the bridge button
# put the printed values into data/config.yaml
docker compose up -d
```

`network_mode: host` is required (mDNS and multicast).

## Setup

**1. Pair with the Hue Bridge**

```bash
/opt/ambiair-hue-bridge/venv/bin/python /opt/ambiair-hue-bridge/ambiair_hue_bridge.py --pair
```

Press the button on the bridge, hit Enter, then copy `bridge_ip`, `app_key` and `client_key` into `/opt/ambiair-hue-bridge/config.yaml`. Also set `tv_ip` and `entertainment_area`.

**2. Check the light mapping**

```bash
/opt/ambiair-hue-bridge/venv/bin/python /opt/ambiair-hue-bridge/ambiair_hue_bridge.py -c /opt/ambiair-hue-bridge/config.yaml --list
```

**3. Start the service**

```bash
systemctl enable --now ambiair-hue-bridge
journalctl -fu ambiair-hue-bridge
```

**4. Run the AmbiAir wizard on the TV**

Enable developer options and network ADB on the TV, then:

```bash
adb connect <TV-IP>:5555
adb shell am start -a org.droidtv.intent.action.ambiAir.LAUNCHWIZARD
```

(The Home Assistant *Android Debug Bridge* integration works too: `androidtv.adb_command`.)

In the wizard:
1. *Connect speaker LED*: the TV finds **`tpv_Hue Bridge`**, your Hue lights blink, and it says *Speaker LEDs connected: 1*. Ignore the "hold the button on the speaker" hint and press **BACK**.
2. *Select speaker LED*: keep **LED 1: playFi** checked → *Done*.
3. *Configure speaker LED*: accept the defaults.
4. *Exit*.

The log should now show:

```
TV 192.168.178.200 hat Schlüssel übergeben: …
Ambilight-Farben empfangen von 192.168.178.200
Hue-Entertainment-Streaming gestartet
```

## Configuration

See [`config.example.yaml`](config.example.yaml). The important options:

| Option | Meaning |
|---|---|
| `name` | Name shown in the TV wizard (`tpv_` is prepended) |
| `brightness` | 0.0 – 1.0 |
| `smoothing` | 0 = off, 0.3 = light, 0.7 = strong (against flicker) |
| `timeout` | Seconds without colors before the lights are released |
| `mapping` | Manual channel → position mapping, e.g. `1: [TopLeft, TopMiddle]` |

Positions: `BottomLeft LeftDown LeftUp TopLeft TopMiddle TopRight RightUp RightDown BottomRight BottomMiddle`

## Troubleshooting

| Problem | Fix |
|---|---|
| TV doesn't find `tpv_Hue Bridge` | mDNS blocked: same VLAN? UniFi: enable mDNS / multicast. Port 80 reachable? |
| Paired, but no colors | The TV derives its key from the Wi-Fi MAC. Wi-Fi must be enabled on the TV (it may stay on Ethernet) |
| Colors arrive, Hue stays dark | Entertainment area already in use (Hue Sync app, Sync Box)? |
| Flicker | `smoothing: 0.4` |
| Test without Hue | `--dry-run` prints the received colors |

## How it works

The protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md). It was reconstructed for interoperability purposes. This repository contains no Philips code.

## Development

`tests/` contains a simulated TV and a simulated Hue bridge (HTTPS + DTLS-PSK) for end-to-end tests without hardware:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 2 -subj /CN=bridge
sudo python tests/fake_bridge.py cert.pem key.pem &
python ambiair_hue_bridge.py -c tests/config.test.yaml &
python tests/fake_tv.py . 8080
```

## Support

If this brings your living room to life, you can [buy me a coffee](https://buymeacoffee.com/fmTechnix) ☕

## License

[MIT](LICENSE)
