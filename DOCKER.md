# Docker Deployment Guide

This guide covers deploying the Crypto Sentiment Crawler using Docker.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND                            │
│              (React + Nginx on :80)                     │
│         Proxies /api/* to backend                       │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                    API SERVICE                          │
│              (FastAPI + Uvicorn on :8000)              │
│         Dashboard data, signals, health checks          │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
        ▼                           ▼
┌───────────────┐           ┌───────────────┐
│   CRAWLER     │           │   DATABASE    │
│  (Scheduler)  │           │   (SQLite)    │
│  Background   │           │  ./data/      │
│  sentiment    │           │  sentiment.db │
│  collection   │           │               │
└───────────────┘           └───────────────┘
```

## Quick Start

### 1. Setup Environment

```bash
# Copy environment template
cp .env.docker.example .env

# Edit with your credentials
nano .env
```

Required credentials:
- `REDDIT_CLIENT_ID` - From https://www.reddit.com/prefs/apps
- `REDDIT_CLIENT_SECRET` - From Reddit app settings

### 2. Build and Run

```bash
# Build all services
docker compose build

# Start services (crawler, api, frontend)
docker compose up -d

# View logs
docker compose logs -f
```

### 3. Access Dashboard

- **Dashboard**: http://localhost
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Services

### Core Services (default)

| Service | Description | Port |
|---------|-------------|------|
| `frontend` | React dashboard | 80 |
| `api` | FastAPI backend | 8000 |
| `crawler` | Background sentiment crawler | - |

### Backfill Services (on-demand)

Run with `--profile backfill`:

```bash
# Run historical Reddit backfill
docker compose --profile backfill up backfill

# Run gap backfill (fill missing days)
docker compose --profile backfill up gap-backfill

# Run user sentiment scoring
docker compose --profile backfill up score-backfill
```

## Commands

### Start/Stop

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Restart a specific service
docker compose restart crawler
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f crawler

# Last 100 lines
docker compose logs --tail=100 api
```

### Database Access

```bash
# Enter API container
docker compose exec api bash

# Access SQLite directly
docker compose exec api sqlite3 /app/data/sentiment.db

# Query example
docker compose exec api sqlite3 /app/data/sentiment.db "SELECT COUNT(*) FROM sentiment_raw;"
```

### Rebuild

```bash
# Rebuild after code changes
docker compose build --no-cache

# Rebuild specific service
docker compose build api
```

## Data Persistence

Data is stored in mounted volumes:

- `./data/` - SQLite database, state files
- `./logs/` - Application logs

To backup:
```bash
cp -r ./data ./data-backup-$(date +%Y%m%d)
```

## Production Deployment

### With Traefik (HTTPS)

```yaml
# Add to docker-compose.yml frontend service
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.crypto.rule=Host(`yourdomain.com`)"
  - "traefik.http.routers.crypto.tls.certresolver=letsencrypt"
```

### Resource Limits

Add to each service in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      cpus: '0.5'
      memory: 512M
```

### Health Monitoring

All services include health checks. Monitor with:

```bash
docker compose ps
```

## Troubleshooting

### Crawler not collecting data

1. Check Reddit credentials in `.env`
2. View crawler logs: `docker compose logs crawler`
3. Verify database exists: `ls -la ./data/`

### API returns 500 errors

1. Check API logs: `docker compose logs api`
2. Verify database connectivity
3. Check database file permissions

### Frontend shows "Failed to load"

1. Verify API is running: `curl http://localhost:8000/health`
2. Check frontend logs: `docker compose logs frontend`
3. Verify nginx proxy config

### Reset Everything

```bash
# Stop and remove containers, networks
docker compose down

# Remove data (WARNING: deletes all crawled data)
rm -rf ./data/*

# Rebuild and start fresh
docker compose build --no-cache
docker compose up -d
```
