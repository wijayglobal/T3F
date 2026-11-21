#!/bin/sh
# One-time setup of a server for GitHub Actions deploys. Run as root on the server, from the checkout:
#   sudo git clone https://github.com/godisai-in/kalaisol.git /opt/kalaichol
#   sudo cp /opt/kalaichol/.env.example /opt/kalaichol/.env && sudo nano /opt/kalaichol/.env
#   sudo sh /opt/kalaichol/deploy/setup_server.sh
#
# It creates the "deploy" user, a sudo rule that lets it run only deploy/ci.sh, and a CI key whose
# authorized_keys line is a forced command. It prints the GitHub secrets to add. Safe to re-run.
set -eu

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
KEY_DIR=/root/github-keys
CI_KEY="$KEY_DIR/kalaichol_deploy"
HOST_NAME="${1:-$(hostname -f)}"

[ "$(id -u)" = 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
command -v docker >/dev/null || { echo "Install Docker with the compose plugin first: https://docs.docker.com/engine/install/" >&2; exit 1; }
docker compose version >/dev/null || { echo "The docker compose plugin is missing." >&2; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "$APP_DIR/.env is missing; copy .env.example and fill it in first." >&2; exit 1; }

chmod 600 "$APP_DIR/.env"
chmod 755 "$APP_DIR/deploy/ci.sh" "$APP_DIR/deploy/deploy.sh" "$APP_DIR/deploy/backup.sh"
mkdir -p "$APP_DIR/data" "$APP_DIR/backups"
touch /var/log/kalaichol_ci.log
# git refuses to work in a repo owned by another user unless it is marked safe.
git config --system --get-all safe.directory | grep -qx "$APP_DIR" || git config --system --add safe.directory "$APP_DIR"

# 1. The restricted user.
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/sh deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh

# 2. It may run ci.sh as root, nothing else.
SUDOERS=/etc/sudoers.d/kalaichol-deploy
printf 'deploy ALL=(root) NOPASSWD: %s/deploy/ci.sh *\n' "$APP_DIR" > "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" >/dev/null && chmod 440 "$SUDOERS.tmp" && mv "$SUDOERS.tmp" "$SUDOERS"

# 3. The CI key, usable only as a forced command.
install -d -m 700 "$KEY_DIR"
[ -f "$CI_KEY" ] || ssh-keygen -q -t ed25519 -N '' -C kalaichol-ci -f "$CI_KEY"
LINE="command=\"sudo -n $APP_DIR/deploy/ci.sh \\\"\$SSH_ORIGINAL_COMMAND\\\"\",restrict $(cat "$CI_KEY.pub")"
AUTH=/home/deploy/.ssh/authorized_keys
touch "$AUTH"
grep -qF "$(cut -d' ' -f2 "$CI_KEY.pub")" "$AUTH" || printf '%s\n' "$LINE" >> "$AUTH"
chown deploy:deploy "$AUTH" && chmod 600 "$AUTH"

cat <<EOF

Done. Add these at GitHub: repo → Settings → Environments → production → Environment secrets
(or Settings → Secrets and variables → Actions):

  DEPLOY_SSH_HOST     $HOST_NAME
  DEPLOY_SSH_USER     deploy
  DEPLOY_SSH_KEY      (the whole private key below)
  DEPLOY_KNOWN_HOSTS  (the lines below)

----- DEPLOY_SSH_KEY -----
$(cat "$CI_KEY")
----- DEPLOY_KNOWN_HOSTS -----
$(for f in /etc/ssh/ssh_host_*_key.pub; do echo "$HOST_NAME $(cut -d' ' -f1,2 "$f")"; done)
--------------------------

Then the first deploy:   sudo $APP_DIR/deploy/ci.sh deploy
EOF
