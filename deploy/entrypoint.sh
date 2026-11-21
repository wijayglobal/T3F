#!/bin/sh
set -e
python manage.py migrate --noinput

# Run the server as the unprivileged "app" user. The models volume may have been created by an
# older root-only image, so hand it over first. `docker compose exec` still runs as root, which the
# data commands need to write into the ./data_raw bind mount.
if [ "$(id -u)" = 0 ] && id app >/dev/null 2>&1; then
    chown -R app:app /models 2>/dev/null || true
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
