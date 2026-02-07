#!/usr/bin/env bash
# Daily traffic report for panicradar.ai
# Parses nginx access logs and sends an email summary via AWS SES.
#
# Usage:
#   ./scripts/daily_traffic_report.sh [--date YYYY-MM-DD] [--dry-run]
#
# Environment:
#   REPORT_EMAIL_TO    - recipient email (required)
#   REPORT_EMAIL_FROM  - sender email (required, must be SES-verified)
#   AWS_REGION         - SES region (default: us-east-1)
#
# Cron example (run at 00:05 UTC daily for previous day's report):
#   5 0 * * * /opt/crypto-sentiment/scripts/daily_traffic_report.sh

set -euo pipefail

# --- Config ---
LOG_DIR="${LOG_DIR:-/opt/crypto-sentiment/logs}"
ACCESS_LOG="${ACCESS_LOG:-$LOG_DIR/access.log}"
REPORT_DIR="${REPORT_DIR:-/opt/crypto-sentiment/reports}"
AWS_REGION="${AWS_REGION:-us-east-1}"
DRY_RUN=false
REPORT_DATE=""

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) REPORT_DATE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Default to yesterday
if [[ -z "$REPORT_DATE" ]]; then
  REPORT_DATE=$(date -u -d "yesterday" +%Y-%m-%d 2>/dev/null || date -u -v-1d +%Y-%m-%d)
fi

# Convert date to nginx log format (e.g., 07/Feb/2026)
LOG_DATE=$(date -u -d "$REPORT_DATE" +%d/%b/%Y 2>/dev/null || date -u -jf "%Y-%m-%d" "$REPORT_DATE" +%d/%b/%Y)

mkdir -p "$REPORT_DIR"
REPORT_FILE="$REPORT_DIR/traffic_${REPORT_DATE}.txt"

echo "Generating traffic report for $REPORT_DATE ..."

# --- Extract day's logs ---
DAY_LOG=$(mktemp)
grep "\[$LOG_DATE:" "$ACCESS_LOG" > "$DAY_LOG" 2>/dev/null || true
TOTAL_LINES=$(wc -l < "$DAY_LOG" | tr -d ' ')

if [[ "$TOTAL_LINES" -eq 0 ]]; then
  echo "No log entries found for $REPORT_DATE"
  rm -f "$DAY_LOG"
  exit 0
fi

# --- Generate report ---
cat > "$REPORT_FILE" <<HEADER
========================================
 PanicRadar.ai Daily Traffic Report
 Date: $REPORT_DATE
========================================

HEADER

# Total requests (exclude internal health checks)
TOTAL_REQS=$(grep -cv '172\.18\.0\.1.*curl' "$DAY_LOG" 2>/dev/null || echo "0")
echo "Total Requests: $TOTAL_REQS (excl. internal health checks)" >> "$REPORT_FILE"

# Unique IPs
UNIQUE_IPS=$(awk '$1 != "172.18.0.1" {print $1}' "$DAY_LOG" | sort -u | wc -l | tr -d ' ')
echo "Unique Visitors (IPs): $UNIQUE_IPS" >> "$REPORT_FILE"

# Page views (non-API, non-static, GET 200)
PAGE_VIEWS=$(awk '$1 != "172.18.0.1" && /GET/ && /\" 200 / && !/\/api\// && !/\.(js|css|png|jpg|svg|ico|woff|ttf|map|json)/' "$DAY_LOG" | wc -l | tr -d ' ')
echo "Page Views: $PAGE_VIEWS" >> "$REPORT_FILE"

echo "" >> "$REPORT_FILE"

# --- Top Pages ---
echo "--- Top Pages (non-API, non-static, GET 200) ---" >> "$REPORT_FILE"
awk '$1 != "172.18.0.1" && /GET/ && /\" 200 / && !/\/api\// && !/\.(js|css|png|jpg|svg|ico|woff|ttf|map|json)/' "$DAY_LOG" \
  | awk -F'"' '{split($2, a, " "); print a[2]}' \
  | sort | uniq -c | sort -rn | head -15 >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Top Visitor IPs ---
echo "--- Top 10 Visitor IPs ---" >> "$REPORT_FILE"
awk '$1 != "172.18.0.1" {print $1}' "$DAY_LOG" \
  | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- New vs returning (identify site owner by top IP) ---
TOP_IP=$(awk '$1 != "172.18.0.1" {print $1}' "$DAY_LOG" | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
TOP_IP_REQS=$(awk -v ip="$TOP_IP" '$1 == ip' "$DAY_LOG" | wc -l | tr -d ' ')
OTHER_REQS=$((TOTAL_REQS - TOP_IP_REQS))
echo "--- Traffic Split ---" >> "$REPORT_FILE"
echo "Site owner ($TOP_IP): $TOP_IP_REQS requests" >> "$REPORT_FILE"
echo "Other visitors: $OTHER_REQS requests from $((UNIQUE_IPS - 1)) IPs" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Bots vs Real ---
BOT_REQS=$(awk '$1 != "172.18.0.1"' "$DAY_LOG" \
  | grep -iE '(bot|crawl|spider|wget|curl|scan|zgrab|censys|python|leakix|l9scan)' \
  | wc -l | tr -d ' ')
echo "--- Bot Traffic ---" >> "$REPORT_FILE"
echo "Bot/Scanner requests: $BOT_REQS" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Scanner probes ---
SCANNER_REQS=$(grep -iE '\.(env|git|aws|DS_Store)|wp-login|xmlrpc|phpmyadmin|PROPFIND|/admin' "$DAY_LOG" | wc -l | tr -d ' ')
echo "--- Security Probes ---" >> "$REPORT_FILE"
echo "Scanner probes (.env, .git, wp-login, etc.): $SCANNER_REQS" >> "$REPORT_FILE"
if [[ "$SCANNER_REQS" -gt 0 ]]; then
  echo "Top probed paths:" >> "$REPORT_FILE"
  grep -iE '\.(env|git|aws|DS_Store)|wp-login|xmlrpc|phpmyadmin|PROPFIND|/admin' "$DAY_LOG" \
    | awk -F'"' '{split($2, a, " "); print a[2]}' \
    | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# --- External referrers ---
echo "--- External Referrers ---" >> "$REPORT_FILE"
awk -F'"' '{print $4}' "$DAY_LOG" \
  | grep -v '^-$' \
  | grep -v 'panicradar.ai' \
  | grep -v '^$' \
  | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE"
EXTERNAL_REFS=$(awk -F'"' '{print $4}' "$DAY_LOG" | grep -v '^-$' | grep -v 'panicradar.ai' | grep -v '^$' | wc -l | tr -d ' ')
if [[ "$EXTERNAL_REFS" -eq 0 ]]; then
  echo "(none)" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# --- HTTP status codes ---
echo "--- HTTP Status Codes ---" >> "$REPORT_FILE"
awk '$1 != "172.18.0.1"' "$DAY_LOG" \
  | awk '{print $9}' \
  | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Top API endpoints ---
echo "--- Top API Endpoints ---" >> "$REPORT_FILE"
awk '$1 != "172.18.0.1" && /\/api\//' "$DAY_LOG" \
  | awk -F'"' '{split($2, a, " "); sub(/\?.*/, "", a[2]); print a[2]}' \
  | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Hourly breakdown ---
echo "--- Hourly Traffic ---" >> "$REPORT_FILE"
for h in $(seq -w 0 23); do
  HOUR_LINES=$(grep "\[$LOG_DATE:$h:" "$DAY_LOG" 2>/dev/null || true)
  if [[ -z "$HOUR_LINES" ]]; then
    COUNT=0
  else
    COUNT=$(echo "$HOUR_LINES" | grep -cv '172\.18\.0\.1.*curl' 2>/dev/null || echo "0")
    COUNT=$(echo "$COUNT" | tr -d '[:space:]')
  fi
  if [[ "$COUNT" -gt 0 ]]; then
    BAR_LEN=$(( COUNT / 50 + 1 ))
    BAR=$(printf '#%.0s' $(seq 1 "$BAR_LEN"))
    printf "  %s:00  %5d  %s\n" "$h" "$COUNT" "$BAR" >> "$REPORT_FILE"
  fi
done
echo "" >> "$REPORT_FILE"

# --- Summary line ---
echo "---" >> "$REPORT_FILE"
echo "Generated at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$REPORT_FILE"

# --- Print report ---
cat "$REPORT_FILE"

# --- Send email via SES ---
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "[DRY RUN] Report saved to $REPORT_FILE (email not sent)"
  rm -f "$DAY_LOG"
  exit 0
fi

if [[ -z "${REPORT_EMAIL_TO:-}" || -z "${REPORT_EMAIL_FROM:-}" ]]; then
  echo ""
  echo "Warning: REPORT_EMAIL_TO or REPORT_EMAIL_FROM not set. Report saved to $REPORT_FILE only."
  rm -f "$DAY_LOG"
  exit 0
fi

SUBJECT="PanicRadar Traffic Report - $REPORT_DATE"

# Build JSON payload for SES (avoids jq dependency and shell escaping issues)
EMAIL_JSON=$(mktemp)
python3 -c "
import json, sys
body = open('$REPORT_FILE').read()
msg = {
    'Source': '$REPORT_EMAIL_FROM',
    'Destination': {'ToAddresses': ['$REPORT_EMAIL_TO']},
    'Message': {
        'Subject': {'Data': '$SUBJECT'},
        'Body': {'Text': {'Data': body}}
    }
}
json.dump(msg, sys.stdout)
" > "$EMAIL_JSON"

aws ses send-email \
  --region "$AWS_REGION" \
  --cli-input-json "file://$EMAIL_JSON" \
  2>&1 && echo "Email sent to $REPORT_EMAIL_TO" || echo "Failed to send email (check SES permissions)"

rm -f "$EMAIL_JSON"

rm -f "$DAY_LOG"
