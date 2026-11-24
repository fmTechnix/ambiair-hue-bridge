#!/usr/bin/env bash
# ambiair-hue-bridge installer (Debian/Ubuntu, run as root)
set -euo pipefail
DIR=/opt/ambiair-hue-bridge
SRC="$(cd "$(dirname "$0")" && pwd)"

apt-get update -qq
apt-get install -y -qq curl ca-certificates >/dev/null

# uv provides Python 3.11 (prebuilt python-mbedtls wheels exist for it)
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

mkdir -p "$DIR"
cp "$SRC/ambiair_hue_bridge.py" "$SRC/requirements.txt" "$SRC/config.example.yaml" "$DIR/"
[ -f "$DIR/config.yaml" ] || cp "$SRC/config.example.yaml" "$DIR/config.yaml"

uv venv -q --allow-existing -p 3.11 "$DIR/venv"
VIRTUAL_ENV="$DIR/venv" uv pip install -q -r "$DIR/requirements.txt"

cp "$SRC/ambiair-hue-bridge.service" /etc/systemd/system/ambiair-hue-bridge.service
systemctl daemon-reload

PY="$DIR/venv/bin/python $DIR/ambiair_hue_bridge.py"
echo
echo "Installed. Next steps / Nächste Schritte:"
echo "  1) Pair with Hue:   $PY --pair"
echo "  2) Edit config:     nano $DIR/config.yaml"
echo "  3) Check mapping:   $PY -c $DIR/config.yaml --list"
echo "  4) Start:           systemctl enable --now ambiair-hue-bridge && journalctl -fu ambiair-hue-bridge"
