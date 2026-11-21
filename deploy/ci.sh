#!/bin/sh
# Entry point for GitHub Actions. It is the ONLY thing the CI key can run: on the server the key sits in
# /home/deploy/.ssh/authorized_keys as a forced command (deploy/setup_server.sh writes it):
#   command="sudo -n /opt/kalaichol/deploy/ci.sh \"$SSH_ORIGINAL_COMMAND\"",restrict ssh-ed25519 …
#
# Tasks:  deploy [commit] | backup | status | restart | build-embeddings
# By hand on the server:  sudo /opt/kalaichol/deploy/ci.sh status
set -eu
set -f  # never glob while splitting the request

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG=/var/log/kalaichol_ci.log

# The request arrives as one string; split it into words (globbing is off).
# shellcheck disable=SC2086
set -- $*
TASK="${1:-}"
ARG="${2:-}"
[ $# -le 2 ] || { echo "Too many arguments." >&2; exit 2; }

matches() { printf '%s' "$2" | grep -Eqx "$1"; }
SHA='[0-9a-f]{7,40}'

reject() { echo "Rejected: '$TASK $ARG'. Allowed: deploy [commit], backup, status, restart, build-embeddings" >&2; exit 2; }

case "$TASK" in
    deploy) [ -z "$ARG" ] || matches "$SHA" "$ARG" || reject ;;
    backup|status|restart|build-embeddings) [ -z "$ARG" ] || reject ;;
    *) reject ;;
esac

# One task at a time (two quick pushes, or a deploy during a backup).
exec 9>/tmp/kalaichol-ci.lock
flock -w 900 9 || { echo "Another task is still running; gave up after 15 minutes." >&2; exit 1; }

echo "$(date '+%F %T') ${SUDO_USER:-$(id -un)} $TASK $ARG" >> "$LOG"
cd "$APP_DIR"

case "$TASK" in
    deploy)  exec "$APP_DIR/deploy/deploy.sh" "$ARG" ;;
    backup)  exec "$APP_DIR/deploy/backup.sh" ;;
    restart) docker compose restart web && docker compose ps --format 'table {{.Service}}\t{{.Status}}' ;;
    build-embeddings) exec docker compose exec -T web python manage.py build_embeddings ;;
    status)
        git log -1 --format='Deployed commit: %h %s (%cr)'
        docker compose ps --format 'table {{.Service}}\t{{.Status}}'
        ls -1t backups/kalaichol-*.sql.gz 2>/dev/null | head -1 | sed 's/^/Latest backup: /' || true
        ;;
esac
