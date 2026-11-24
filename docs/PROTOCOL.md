# AmbiAir protocol

Reconstructed for interoperability from the behaviour of the TV-side app
`org.droidtv.ambiair` (Philips Google TV, 2025). No Philips code is included here.

## 1. Discovery (mDNS)

- The TV browses for the service type `_tpv_al._tcp`.
- It only accepts instances whose name contains `tpv_`.
- It uses the resolved IPv4 address. The port from the SRV record is ignored, because all HTTP goes to port **80**.

> `_tpv_al` contains an underscore, which strict RFC 6763 implementations reject.
> With python-zeroconf, use `register_service(info, strict=False)`.

## 2. Setup (HTTP, port 80)

Base path: `/1/ambiair/multicast`

JSON payloads are put into the **URL path**, not the body:
`POST /1/ambiair/multicast/<endpoint>/post_value=<json>` with an empty body.
Every response that contains the string `success` counts as OK.

| Method | Endpoint | Payload (example) | Purpose |
|---|---|---|---|
| GET | `/config` | – | Device info (see below) |
| POST | `/key` | `{"key":"D40ADCBB4EA21234"}` | TV hands over its 16-char secret |
| POST | `/checkkey` | `{"key":"…"}` | TV verifies the key |
| POST | `/clearkey` | `{"key":"…"}` | Unpair |
| POST | `/config` | `{"key":"…","status":{"angle":"…","brightness":5}}` | Position / brightness |
| POST | `/configured` | `{"key":"…","configured":1}` | Mark as configured |
| POST | `/stream` | `{"key":"…","status":true}` | Start / stop streaming |
| POST | `/1/ambiair/light/state/post_value=…` | – | Blink to identify the device |

`GET /config` response:

```json
{"capability": true, "multicast": true, "speaker type": "playFi",
 "MAC address": "02:A1:C0:A8:B2:4D", "configured": 0,
 "status": {"angle": "Left 1 (L1)", "brightness": 5}}
```

### Key

The TV builds the key from its **Wi-Fi MAC** (12 hex digits, no colons) plus 4 digits.
If Wi-Fi is disabled entirely, no valid key is generated and the TV never streams.
The Wi-Fi radio only has to be enabled. The TV can stay connected via Ethernet.

## 3. Color stream (UDP)

Every ~35 ms (~28 fps) the TV sends the same packet to

- multicast `224.8.0.8:2920`
- unicast `<device IP>:2930` for every selected device

### Packet (120 bytes)

| Offset | Length | Content |
|---|---|---|
| 0 | 12 | ASCII `AmbilightAir` |
| 12 | 1 | `0x01` |
| 13 | 1 | `0x00` |
| 14 | 16 | Key (ASCII, plaintext) |
| 30 + 9·i | 2 | `0x00 0x00` |
| 32 + 9·i | 1 | Pixel ID (i+1) |
| 33 + 9·i | 6 | R, G, B, 16 bit each, big endian |

`i = 0 … 9`. The values are 16-bit. The TV clamps anything below `0x0100` to `0x0100`.

### Slot order (positions around the screen)

| i | Position |
|---|---|
| 0 | BottomLeft |
| 1 | LeftDown |
| 2 | LeftUp |
| 3 | TopLeft |
| 4 | TopMiddle |
| 5 | TopRight |
| 6 | RightUp |
| 7 | RightDown |
| 8 | BottomRight |
| 9 | BottomMiddle |

The slots are fixed. They do **not** depend on which or how many devices are selected,
so a single emulated device receives all 10 positions.

There is no encryption and no authentication beyond the plaintext key.
