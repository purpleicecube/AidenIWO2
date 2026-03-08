#!/usr/bin/env bash
# backup-db.sh — Back up AIDEN PostgreSQL database
# Keeps last 7 daily backups. Run manually or via cron.
set -euo pipefail

CONTAINER="aiden-postgres"
DB_USER="aiden"
DB_NAME="aiden_iwo"
BACKUP_DIR="/home/virgina/VS_AIDEN/backups"
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

# Check container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "[backup] ERROR: ${CONTAINER} is not running. Skipping backup."
  exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/aiden_iwo_${TIMESTAMP}.sql.gz"

echo "[backup] Dumping ${DB_NAME}..."
docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[backup] Saved: ${BACKUP_FILE} (${SIZE})"

# Prune old backups
DELETED=0
find "$BACKUP_DIR" -name "aiden_iwo_*.sql.gz" -mtime "+${KEEP_DAYS}" -print -delete | while read -r f; do
  DELETED=$((DELETED + 1))
done
echo "[backup] Pruned backups older than ${KEEP_DAYS} days"

# Quick restore instructions
echo ""
echo "To restore: gunzip -c <backup>.sql.gz | docker exec -i ${CONTAINER} psql -U ${DB_USER} ${DB_NAME}"
