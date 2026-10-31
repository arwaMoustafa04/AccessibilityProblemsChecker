#!/usr/bin/env bash
# One-time (and re-runnable) setup for an Ubuntu 22.04/24.04 EC2 instance.
#
# Run from the repo folder on the server:
#     cd ~/AccessibilityProblemsChecker && bash deploy/setup.sh
#
# Result:
#     http://<server-ip>/system  -> the system  (uvicorn main:app, port 8001)
#     http://<server-ip>/tester  -> the tester  (uvicorn app:app,  port 8002)
# Both start automatically on boot and restart if they crash.
# Re-run this script after you update the code to reinstall and restart.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
VENV="$APP_DIR/.venv"

echo "==> Installing system packages (python, nginx, curl)"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip nginx curl

echo "==> Creating Python environment in $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" -r "$APP_DIR/tester/requirements.txt"

# veraPDF (PDF/UA-1 validator, used by the checks). Optional: if this step fails,
# the service still works and each response says veraPDF was not used.
# Skip it with:  SKIP_VERAPDF=1 bash deploy/setup.sh
VERAPDF_DIR=/opt/verapdf
if [ "${SKIP_VERAPDF:-0}" != "1" ] && [ ! -x "$VERAPDF_DIR/verapdf" ]; then
    echo "==> Installing Java and veraPDF into $VERAPDF_DIR"
    if sudo apt-get install -y openjdk-17-jre-headless unzip \
        && TMP="$(mktemp -d)" \
        && curl -fsSL -o "$TMP/verapdf.zip" https://software.verapdf.org/rel/verapdf-installer.zip \
        && unzip -q "$TMP/verapdf.zip" -d "$TMP" \
        && sudo "$(ls -d "$TMP"/verapdf-greenfield-*)/verapdf-install" "$APP_DIR/deploy/verapdf-auto-install.xml"; then
        echo "veraPDF installed: $("$VERAPDF_DIR/verapdf" --version 2>/dev/null | head -1)"
    else
        echo "WARNING: veraPDF could not be installed; checks will run without it."
    fi
fi
VERAPDF_ENV=""
if [ -x "$VERAPDF_DIR/verapdf" ]; then
    VERAPDF_ENV="Environment=VERAPDF_PATH=$VERAPDF_DIR/verapdf"
fi

echo "==> Creating services"
sudo tee /etc/systemd/system/pdf-system.service > /dev/null <<EOF
[Unit]
Description=PDF accessibility system (Team 1)
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
$VERAPDF_ENV
ExecStart=$VENV/bin/uvicorn main:app --host 127.0.0.1 --port 8001 --root-path /system --no-access-log
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/pdf-tester.service > /dev/null <<EOF
[Unit]
Description=PDF accessibility tester (Team 1)
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR/tester
ExecStart=$VENV/bin/uvicorn app:app --host 127.0.0.1 --port 8002 --root-path /tester --no-access-log
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring nginx (/system and /tester)"
sudo tee /etc/nginx/sites-available/pdf-accessibility > /dev/null <<'EOF'
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 100m;    # larger than 20 MB, so the app (not nginx) returns the JSON 413
    proxy_read_timeout 900s;      # a full tester run can take minutes
    proxy_send_timeout 900s;

    location /system/ {
        proxy_pass http://127.0.0.1:8001/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location /tester/ {
        proxy_pass http://127.0.0.1:8002/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location = /system { return 301 /system/; }
    location = /tester { return 301 /tester/; }
}
EOF
sudo ln -sf /etc/nginx/sites-available/pdf-accessibility /etc/nginx/sites-enabled/pdf-accessibility
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

echo "==> Starting everything"
sudo systemctl daemon-reload
sudo systemctl enable --now pdf-system pdf-tester
sudo systemctl restart pdf-system pdf-tester nginx
sleep 3

echo "==> Checking"
curl -fsS http://127.0.0.1/system/health && echo
curl -fsS -o /dev/null -w "tester docs: HTTP %{http_code}\n" http://127.0.0.1/tester/docs

IP="$(curl -fsS --max-time 3 https://checkip.amazonaws.com 2>/dev/null || echo '<server-ip>')"
cat <<EOF

Done. Your registry URLs:
    System base URL: http://$IP/system
    Tester base URL: http://$IP/tester

Try in a browser:  http://$IP/system/docs   and   http://$IP/tester/docs
Logs if something breaks:  sudo journalctl -u pdf-system -n 50   (or pdf-tester)
EOF
