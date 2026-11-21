#!/bin/sh
# Pull origin/main and apply it. Called by GitHub Actions through deploy/ci.sh, or by hand:
#   sudo /opt/kalaichol/deploy/deploy.sh
#
# App files changed (anything outside docs/, .github/, deploy/*.sh, deploy/Caddyfile, top-level *.md):
# rebuild and restart the containers (the entrypoint runs migrations), then check the site answers.
# Otherwise only the checkout is updated.
set -eu

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
EXPECTED="${1:-}"

# A private repo is fetched with a read-only GitHub deploy key (docs/DEPLOY.md, "Private repo").
for PULL_KEY in "${REPO_PULL_KEY:-}" "${HOME:-/nonexistent}/.ssh/github_pull" /root/github-keys/github_pull; do
    if [ -n "$PULL_KEY" ] && [ -r "$PULL_KEY" ]; then
        export GIT_SSH_COMMAND="ssh -i $PULL_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        break
    fi
done

[ -f .env ] || { echo "$APP_DIR/.env is missing; copy .env.example and fill it in first." >&2; exit 1; }
mkdir -p data backups

OLD=$(git rev-parse HEAD)
git fetch --quiet origin main
NEW=$(git rev-parse origin/main)

if [ -n "$EXPECTED" ] && ! git merge-base --is-ancestor "$EXPECTED" "$NEW"; then
    echo "Commit $EXPECTED is not on origin/main; refusing to deploy." >&2
    exit 1
fi

FIRST_RUN=no
docker compose ps --status running --services 2>/dev/null | grep -qx web || FIRST_RUN=yes

if [ "$OLD" = "$NEW" ] && [ "$FIRST_RUN" = no ]; then
    echo "Already at $(git log -1 --format='%h %s')."
    exit 0
fi

if [ "$OLD" != "$NEW" ]; then
    git merge --ff-only --quiet origin/main
    echo "Updated $(git rev-parse --short "$OLD") → $(git log -1 --format='%h %s')"
fi

CHANGED=$(git diff --name-only "$OLD" "$NEW")
APP_CHANGED=$(printf '%s\n' "$CHANGED" | grep -Ev '^(docs/|\.github/|deploy/[^/]+\.sh$|deploy/Caddyfile$|[^/]+\.md$)' | grep -v '^$' || true)

wait_for_web() {
    # The entrypoint runs migrations before gunicorn starts; wait until they are applied and the site answers.
    PORT=$(sed -n 's/^WEB_PORT=//p' .env | tail -1)
    PORT="${PORT:-8081}"
    # Django answers 400 to a Host it doesn't know, so ask as the first name in ALLOWED_HOSTS.
    SITE_HOST=$(sed -n 's/^ALLOWED_HOSTS=//p' .env | tail -1 | cut -d, -f1 | tr -d "\"' " | sed 's/^\.//')
    case "$SITE_HOST" in ''|'*') SITE_HOST=localhost ;; esac
    for _ in $(seq 1 90); do
        if docker compose exec -T web python manage.py migrate --check >/dev/null 2>&1 \
           && curl -fsS -o /dev/null -H "Host: $SITE_HOST" "http://127.0.0.1:$PORT/"; then
            echo "Site answers on 127.0.0.1:$PORT."
            return 0
        fi
        sleep 2
    done
    echo "The web container did not become ready in 3 minutes." >&2
    docker compose logs --tail 50 web >&2
    return 1
}

if [ -n "$APP_CHANGED" ] || [ "$FIRST_RUN" = yes ]; then
    [ -z "$APP_CHANGED" ] || { echo "App files changed:"; printf '  %s\n' $APP_CHANGED; }
    docker compose up -d --build --remove-orphans
    wait_for_web
    docker image prune -f >/dev/null
else
    echo "Only docs, workflow or script files changed; nothing to rebuild."
fi
echo "Deploy finished."
