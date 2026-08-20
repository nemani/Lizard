#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${SERVICE_USER:-lizard}"
INSTALL_DIR="${INSTALL_DIR:-/opt/lizard}"
CONFIG_FILE="${CONFIG_FILE:-/etc/lizard/egg.env}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-15}"
MQTT_HOST="${MQTT_HOST:-}"
MQTT_PORT="${MQTT_PORT:-1883}"
CPU_PERCENT_THRESHOLDS="${CPU_PERCENT_THRESHOLDS:-[{\"level\":\"warning\",\"value\":50},{\"level\":\"critical\",\"value\":90}]}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ -z "${MQTT_HOST}" ]]; then
  echo "MQTT_HOST is required, for example: sudo MQTT_HOST=nest.example.com scripts/lay-egg.sh" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "lay-egg must run as root because it installs a systemd service." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

mkdir -p "${INSTALL_DIR}" /etc/lizard
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install "${PROJECT_DIR}[gpu]"

cat > "${CONFIG_FILE}" <<EOF
LIZARD_MQTT_HOST='${MQTT_HOST}'
LIZARD_MQTT_PORT='${MQTT_PORT}'
LIZARD_INTERVAL_SECONDS='${INTERVAL_SECONDS}'
LIZARD_CPU_PERCENT_THRESHOLDS='${CPU_PERCENT_THRESHOLDS}'
EOF

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
chown root:"${SERVICE_USER}" /etc/lizard "${CONFIG_FILE}"
chmod 750 /etc/lizard
chmod 640 "${CONFIG_FILE}"

cat > /etc/systemd/system/lizard-egg.service <<EOF
[Unit]
Description=Lizard Egg GPU Server Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${CONFIG_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/lizard-egg
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now lizard-egg.service
systemctl status --no-pager lizard-egg.service
