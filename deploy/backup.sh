#!/bin/sh
# Daily Postgres dump of the kalaichol database, keeps the last 14 days.
# Cron (as the user that runs docker):
#   15 3 * * * /path/to/tamil_translation/deploy/backup.sh >> /path/to/tamil_translation/backups/backup.log 2>&1
# Restore:
#   gunzip -c backups/kalaichol-YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U kalaichol -d kalaichol
set -eu
cd "$(dirname "$0")/.."
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups
out="backups/kalaichol-$(date +%F).sql.gz"
docker compose exec -T db pg_dump -U kalaichol -d kalaichol --no-owner | gzip > "$out.tmp"
mv "$out.tmp" "$out"
find backups -name 'kalaichol-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) wrote $out ($(du -h "$out" | cut -f1))"
