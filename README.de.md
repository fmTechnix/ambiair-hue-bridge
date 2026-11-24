# ambiair-hue-bridge

**Ambilight deines Philips Google TV auf *beliebige* Philips-Hue-Lampen – ohne Sync Box, ohne Bildschirmaufnahme, funktioniert auch mit Netflix & Co.**

🇬🇧 [English](README.md)

Philips hat *Ambilight + Hue* bei den neueren Fernsehern gestrichen. Versteckt ist aber noch
**AmbiAir** drauf: Damit schickt der Fernseher seine Ambilight-Farben an Philips-Funklautsprecher
mit LEDs. Dieses Projekt gibt sich als so ein Lautsprecher aus und reicht die Farben an einen
Hue-Entertainment-Bereich weiter.

- Die Farben kommen direkt aus dem Ambilight-Chip, nicht aus Screenshots. Deshalb klappt es **auch bei DRM-Inhalten (Netflix, Disney+ …)**.
- Läuft komplett lokal, ohne Cloud.
- Bis zu 10 Positionen rund ums Bild. Die Zuordnung zu deinen Lampen läuft automatisch über die Platzierung in der Hue-App.
- Hört der Fernseher auf zu senden, gehen deine Lampen zurück in ihren vorherigen Zustand.

> **Kein offizielles Produkt, nicht verbunden mit TP Vision, Philips oder Signify.**
> Ambilight und Hue sind Marken der jeweiligen Inhaber. Nutzung auf eigene Gefahr.

## Getestete Fernseher

| Modell | System | Ergebnis |
|---|---|---|
| Philips 65OLED810/12 (2025) | Google TV 14 | ✅ läuft |

## Voraussetzungen

- Philips-TV mit der App `org.droidtv.ambiair` (prüfen per ADB: `pm list packages | grep ambiair`)
- Hue Bridge (v2, eckig) mit **Entertainment-Bereich**
- Ein dauerhaft laufendes Gerät im **selben Netz/VLAN** wie Fernseher und Bridge: Proxmox-LXC, Raspberry Pi, Docker …
- Port **80** frei (der Fernseher spricht immer Port 80 an)
- Einmalig ADB-Zugriff auf den Fernseher, um den versteckten Assistenten zu öffnen

## Installation (Debian/Ubuntu, z. B. Proxmox-LXC)

```bash
git clone https://github.com/fmTechnix/ambiair-hue-bridge.git
cd ambiair-hue-bridge
sudo bash install.sh
```

Docker geht auch, siehe [englische README](README.md#option-b-docker).

## Einrichtung

**1. Mit der Hue-Bridge koppeln**

```bash
/opt/ambiair-hue-bridge/venv/bin/python /opt/ambiair-hue-bridge/ambiair_hue_bridge.py --pair
```

Knopf auf der Bridge drücken, Enter. Danach `bridge_ip`, `app_key` und `client_key` in
`/opt/ambiair-hue-bridge/config.yaml` eintragen, dazu `tv_ip` und `entertainment_area`.

**2. Zuordnung prüfen**

```bash
/opt/ambiair-hue-bridge/venv/bin/python /opt/ambiair-hue-bridge/ambiair_hue_bridge.py -c /opt/ambiair-hue-bridge/config.yaml --list
```

**3. Dienst starten**

```bash
systemctl enable --now ambiair-hue-bridge
journalctl -fu ambiair-hue-bridge
```

**4. AmbiAir-Assistent am Fernseher**

Am Fernseher Entwickleroptionen und ADB übers Netzwerk aktivieren, dann:

```bash
adb connect <TV-IP>:5555
adb shell am start -a org.droidtv.intent.action.ambiAir.LAUNCHWIZARD
```

(Geht auch über die Home-Assistant-Integration *Android Debug Bridge* mit `androidtv.adb_command`.)

Im Assistenten:
1. *Lautsprecher-LED verbinden*: Der Fernseher findet **`tpv_Hue Bridge`**, deine Hue-Lampen blinken, und es erscheint „Lautsprecher-LEDs verbunden: 1". Den Hinweis mit der Taste am Lautsprecher ignorieren und **ZURÜCK** drücken.
2. *Lautsprecher-LED auswählen*: **LED 1: playFi** angehakt lassen → *Fertig*.
3. *Lautsprecher-LED konfigurieren*: Vorgaben bestätigen.
4. *Beenden*.

## Fehlersuche

| Problem | Lösung |
|---|---|
| Fernseher findet `tpv_Hue Bridge` nicht | mDNS kommt nicht durch: gleiches VLAN? In UniFi mDNS/Multicast aktivieren. Port 80 erreichbar? |
| Gekoppelt, aber keine Farben | Der Fernseher bildet seinen Schlüssel aus der WLAN-MAC. WLAN am Fernseher muss eingeschaltet sein (er darf trotzdem am Kabel hängen) |
| Farben kommen, Hue bleibt dunkel | Entertainment-Bereich gerade anderweitig belegt (Hue-Sync-App, Sync Box)? |
| Flackern | `smoothing: 0.4` |
| Test ohne Hue | `--dry-run` zeigt die empfangenen Farben |

## Unterstützen

Wenn's dein Wohnzimmer zum Leuchten bringt: [Buy me a coffee](https://buymeacoffee.com/fmTechnix) ☕

## Lizenz

[MIT](LICENSE)
