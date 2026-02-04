#!/bin/bash
# Daily database backup script for Panic Radar
# Backs up to local directory and S3
# Add to crontab: 0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh >> /opt/crypto-sentiment/logs/backup.log 2>&1

set -e

DATA_DIR="/opt/crypto-sentiment/data"
BACKUP_DIR="/opt/crypto-sentiment/backups"
DB_FILE="$DATA_DIR/sentiment.db"
STATE_FILE="$DATA_DIR/orchestrator_state.json"
S3_BUCKET="${S3_BACKUP_BUCKET:-panicradar-backups}"
RETENTION_DAYS=14

# Create backup directory if needed
mkdir -p "$BACKUP_DIR"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_PREFIX=$(date +%Y/%m)

echo "$(date): Starting backup..."

# Backup database if exists
if [ -f "$DB_FILE" ]; then
    BACKUP_NAME="sentiment_daily_${TIMESTAMP}.db"
    LOCAL_BACKUP="$BACKUP_DIR/$BACKUP_NAME"

    # Use sqlite3 backup command if available (safer for live DB)
    if command -v sqlite3 &> /dev/null; then
        sqlite3 "$DB_FILE" ".backup '$LOCAL_BACKUP'"
    else
        cp "$DB_FILE" "$LOCAL_BACKUP"
    fi

    echo "$(date): Database backed up locally to $BACKUP_NAME"

    # Upload to S3
    if command -v aws &> /dev/null; then
        aws s3 cp "$LOCAL_BACKUP" "s3://$S3_BUCKET/db/$DATE_PREFIX/$BACKUP_NAME"
        echo "$(date): Database uploaded to S3: s3://$S3_BUCKET/db/$DATE_PREFIX/$BACKUP_NAME"
    else
        echo "$(date): WARNING - AWS CLI not installed, skipping S3 upload"
    fi
else
    echo "$(date): No database file found at $DB_FILE"
fi

# Backup state file if exists
if [ -f "$STATE_FILE" ]; then
    STATE_BACKUP="orchestrator_state_${TIMESTAMP}.json"
    cp "$STATE_FILE" "$BACKUP_DIR/$STATE_BACKUP"

    # Upload to S3
    if command -v aws &> /dev/null; then
        aws s3 cp "$BACKUP_DIR/$STATE_BACKUP" "s3://$S3_BUCKET/state/$DATE_PREFIX/$STATE_BACKUP"
        echo "$(date): State file uploaded to S3"
    fi
fi

# Clean up old local backups (keep last N days)
find "$BACKUP_DIR" -name "sentiment_daily_*.db" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "sentiment_predeploy_*.db" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "orchestrator_state_*.json" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

# Report
echo "$(date): Local backups:"
ls -lh "$BACKUP_DIR"/*.db 2>/dev/null | tail -5 || echo "No database backups found"

echo "$(date): Backup complete"
