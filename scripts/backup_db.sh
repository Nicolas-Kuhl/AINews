#!/usr/bin/env bash
#
# Daily backup of the AINews SQLite database.
#
# Makes a consistent snapshot using SQLite's online backup API (safe to run
# while the dashboard/pipeline are reading or writing — unlike a raw cp), keeps
# the last N local copies, and optionally uploads the snapshot to S3.
#
# Configure via environment (e.g. in /etc/ainews.env sourced by cron, or export
# before running):
#   AINEWS_DB         path to the live DB        (default: <repo>/data/ainews.db)
#   AINEWS_BACKUP_DIR local backup directory     (default: <repo>/data/backups)
#   AINEWS_BACKUP_KEEP local copies to retain     (default: 14)
#   AINEWS_BACKUP_S3  s3://bucket/prefix to also upload to (optional; needs awscli)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

DB_PATH="${AINEWS_DB:-$REPO_DIR/data/ainews.db}"
BACKUP_DIR="${AINEWS_BACKUP_DIR:-$REPO_DIR/data/backups}"
KEEP="${AINEWS_BACKUP_KEEP:-14}"
S3_DEST="${AINEWS_BACKUP_S3:-}"

if [ ! -f "$DB_PATH" ]; then
    echo "$(date -u +%FT%TZ) ERROR: database not found at $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
SNAPSHOT="$BACKUP_DIR/ainews-$STAMP.db"

# Online backup — consistent even under concurrent writes. Falls back to a
# plain copy only if the sqlite3 CLI is unavailable.
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$SNAPSHOT'"
else
    cp "$DB_PATH" "$SNAPSHOT"
fi
gzip -f "$SNAPSHOT"
SNAPSHOT="$SNAPSHOT.gz"
echo "$(date -u +%FT%TZ) wrote $SNAPSHOT ($(du -h "$SNAPSHOT" | cut -f1))"

# Retain only the most recent $KEEP local snapshots.
ls -1t "$BACKUP_DIR"/ainews-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old"
    echo "$(date -u +%FT%TZ) pruned $old"
done

# Optional off-box copy.
if [ -n "$S3_DEST" ]; then
    if command -v aws >/dev/null 2>&1; then
        aws s3 cp "$SNAPSHOT" "${S3_DEST%/}/$(basename "$SNAPSHOT")"
        echo "$(date -u +%FT%TZ) uploaded to ${S3_DEST%/}/$(basename "$SNAPSHOT")"
    else
        echo "$(date -u +%FT%TZ) WARNING: AINEWS_BACKUP_S3 set but awscli not installed; skipped upload" >&2
    fi
fi
