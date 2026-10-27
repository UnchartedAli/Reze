#!/usr/bin/env bash
# Automated safe backup script for Reze database and settings
set -e

BACKUP_DIR="backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

if [ -f "data/reze.db" ]; then
    sqlite3 data/reze.db ".backup '$BACKUP_DIR/reze_backup_$TIMESTAMP.db'"
    echo "✅ Database backup created at $BACKUP_DIR/reze_backup_$TIMESTAMP.db"
else
    echo "⚠️ Database data/reze.db not found."
fi
