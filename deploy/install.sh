#!/usr/bin/env bash
# Install (or update) InternProMax as an always-on service on an Ubuntu/Debian server.
# By default it's reachable only over your private Tailscale network, protected by a password.
#
#   From a clone on the server:  sudo ./deploy/install.sh
#   Update later:                cd InternProMax && git pull && sudo ./deploy/install.sh
#
# Optional environment variables:
#   IPM_PASSWORD=...         set (or change) the password without being asked
#   IPM_PORT=8420            port to listen on
#   IPM_TS_HOSTNAME=name     Tailscale machine name (default: internpromax)
#   IPM_NO_TAILSCALE=1       listen on all interfaces instead (put your own HTTPS proxy in front;
#                            also set IPM_ALLOWED_HOSTS=your.domain)
#   IPM_REPO=<git url>       where to clone from when not run from a clone
set -euo pipefail

APP_DIR=/opt/internpromax
DATA_DIR=/var/lib/internpromax
ENV_FILE=/etc/internpromax.env
SERVICE_FILE=/etc/systemd/system/internpromax.service
REPO="${IPM_REPO:-https://github.com/anishlaha007/InternProMax.git}"
PORT="${IPM_PORT:-8420}"
TS_NAME="${IPM_TS_HOSTNAME:-internpromax}"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo."
command -v apt-get >/dev/null || die "This script supports Ubuntu/Debian. For anything else see docs/DEPLOY.md (Docker)."

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl rsync ca-certificates >/dev/null
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10+ is required (Ubuntu 22.04+ or Debian 12+)."

say "Getting the code"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
if [ -n "$SRC" ] && [ -f "$SRC/internpromax/server.py" ] && [ "$SRC" != "$APP_DIR" ]; then
  mkdir -p "$APP_DIR"
  rsync -a --delete --exclude .git --exclude .venv --exclude data --exclude node_modules "$SRC/" "$APP_DIR/"
elif [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
elif [ ! -f "$APP_DIR/internpromax/server.py" ]; then
  git clone --depth 1 "$REPO" "$APP_DIR" \
    || die "Couldn't clone $REPO. If the repo is private, clone it on the server first and run ./deploy/install.sh from that clone."
fi

id internpromax >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin internpromax
mkdir -p "$DATA_DIR"
chown -R internpromax:internpromax "$DATA_DIR"
chmod 700 "$DATA_DIR"

say "Installing Python dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ -z "${IPM_NO_TAILSCALE:-}" ]; then
  if ! command -v tailscale >/dev/null; then
    say "Installing Tailscale (private network between your devices and this server)"
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  if ! tailscale ip -4 >/dev/null 2>&1; then
    say "Connect this server to your Tailscale account: open the link below in a browser"
    tailscale up --hostname="$TS_NAME"
  fi
  BIND="$(tailscale ip -4 | head -n1)"
  TS_DNS="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  SHORT="${TS_DNS%%.*}"
  HOSTS="$BIND"
  [ -n "$TS_DNS" ] && HOSTS="$HOSTS,$TS_DNS,$SHORT"
  # Some cloud images (Oracle's Ubuntu) reject all inbound traffic except SSH: let Tailscale traffic reach the app.
  if command -v iptables >/dev/null && iptables -S INPUT 2>/dev/null | grep -q -- '-j REJECT'; then
    iptables -C INPUT -i tailscale0 -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT -i tailscale0 -p tcp --dport "$PORT" -j ACCEPT
    if command -v netfilter-persistent >/dev/null; then netfilter-persistent save >/dev/null 2>&1 || true; fi
  fi
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow in on tailscale0 to any port "$PORT" proto tcp >/dev/null
  fi
else
  BIND=0.0.0.0
  HOSTS="${IPM_ALLOWED_HOSTS:-}"
  SHORT=""
  [ -n "$HOSTS" ] || die "With IPM_NO_TAILSCALE=1, also set IPM_ALLOWED_HOSTS to the host name you'll use (e.g. jobs.example.com)."
fi

PW_FILE=/etc/internpromax.password
if [ -n "${IPM_PASSWORD:-}" ] || [ ! -s "$PW_FILE" ]; then
  PASSWORD="${IPM_PASSWORD:-}"
  if [ -z "$PASSWORD" ]; then
    say "Choose a password for your dashboard and the Chrome extension"
    while :; do
      read -rsp "Password (8+ characters): " PASSWORD </dev/tty; echo
      read -rsp "Repeat it: " AGAIN </dev/tty; echo
      if [ "$PASSWORD" = "$AGAIN" ] && [ "${#PASSWORD}" -ge 8 ]; then break; fi
      echo "They didn't match or were too short. Try again."
    done
  fi
  [ "${#PASSWORD}" -ge 8 ] || die "The password must be at least 8 characters."
  # stored verbatim in its own file: no quoting or escaping to get wrong
  (umask 077; printf '%s' "$PASSWORD" > "$PW_FILE")
fi
chown root:internpromax "$PW_FILE"
chmod 640 "$PW_FILE"

say "Writing settings to $ENV_FILE"
umask 077
cat > "$ENV_FILE" <<EOF
# InternProMax server settings (rewritten by deploy/install.sh). The password lives in /etc/internpromax.password.
IPM_HOST=$BIND
IPM_PORT=$PORT
IPM_DATA_DIR=$DATA_DIR
IPM_ALLOWED_HOSTS=$HOSTS
IPM_PASSWORD_FILE=$PW_FILE
EOF
chmod 600 "$ENV_FILE"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=InternProMax (internship finder, resume tailor and tracker)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=internpromax
Group=internpromax
EnvironmentFile=$ENV_FILE
Environment=PYTHONDONTWRITEBYTECODE=1
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m internpromax serve --no-browser
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

say "Starting the service"
systemctl daemon-reload
systemctl enable internpromax >/dev/null 2>&1
systemctl restart internpromax
for _ in $(seq 1 30); do
  if curl -fsS "http://$BIND:$PORT/api/health" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    OK=1
    break
  fi
  sleep 1
done
if [ -z "${OK:-}" ]; then
  journalctl -u internpromax -n 30 --no-pager || true
  die "The service didn't come up. The log is above."
fi

URL="http://${SHORT:-$BIND}:$PORT"
[ -n "${IPM_NO_TAILSCALE:-}" ] && URL="https://${HOSTS%%,*} (through your proxy to port $PORT)"
cat <<EOF

  InternProMax is running.

  Dashboard:   $URL   (also http://$BIND:$PORT)
  Log in with the password you chose.

  On your laptop and phone: install Tailscale and sign in with the same account.
  Chrome extension: Options → Server address "$URL" → your password → Connect.

  Logs:     journalctl -u internpromax -f
  Update:   git pull && sudo ./deploy/install.sh   (from your clone)
  Backup:   sudo tar czf internpromax-backup.tgz -C /var/lib internpromax
EOF
