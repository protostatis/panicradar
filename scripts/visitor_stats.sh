#!/bin/bash
# Quick visitor stats from nginx access logs on EC2
# Usage: ./scripts/visitor_stats.sh [days]

DAYS=${1:-7}
KEY=~/.ssh/panicradar-ec2.pem
HOST=ec2-user@34.236.47.243
LOG=/opt/crypto-sentiment/logs/access.log

ssh -i "$KEY" "$HOST" "
echo '=============================='
echo ' PanicRadar Visitor Stats'
echo '=============================='
echo

if [ ! -f $LOG ]; then
  echo 'No log file found at $LOG'
  exit 1
fi

TOTAL_LINES=\$(wc -l < $LOG)
echo \"Total log entries: \$TOTAL_LINES\"
echo

# Filter: only page loads (HTML/SPA routes), exclude bots, API calls, static assets
echo '--- Unique Visitors (by IP) ---'
grep -E 'GET /(|beliefs|sources|signals|dashboard)' $LOG \
  | grep -v -E '(bot|crawler|spider|Wget|curl|python|Go-http|HEAD)' \
  | awk '{print \$1}' | sort -u | wc -l | xargs echo 'Unique IPs:'

echo
echo '--- Page Views (excl. API/assets/bots) ---'
grep -E 'GET /(|beliefs|sources|signals|dashboard)' $LOG \
  | grep -v -E '(bot|crawler|spider|Wget|curl|python|Go-http|HEAD|\.js|\.css|\.png|\.ico|/api/)' \
  | wc -l | xargs echo 'Page views:'

echo
echo '--- Top 10 Visitor IPs ---'
grep -E 'GET /' $LOG \
  | grep -v -E '(bot|crawler|spider|Wget|curl|python|Go-http)' \
  | awk '{print \$1}' | sort | uniq -c | sort -rn | head -10

echo
echo '--- Requests Per Day ---'
awk '{print \$4}' $LOG | cut -d: -f1 | tr -d '[' | sort | uniq -c | sort -k2

echo
echo '--- Top Pages ---'
awk '{print \$7}' $LOG \
  | grep -v -E '(\.(js|css|png|ico|svg|woff)|/api/)' \
  | sort | uniq -c | sort -rn | head -10

echo
echo '--- User Agents (top 5) ---'
awk -F'\"' '{print \$6}' $LOG \
  | grep -v -E '(bot|crawler|spider|Wget|curl|^-$|^$)' \
  | sort | uniq -c | sort -rn | head -5

echo
echo '--- Suspicious Requests ---'
grep -E '(\.env|\.git|wp-|admin|phpmyadmin|shell|passwd)' $LOG | wc -l | xargs echo 'Probe attempts:'
"
