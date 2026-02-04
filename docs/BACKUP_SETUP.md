# Database Backup Setup

Panic Radar automatically backs up the database locally and to S3.

## Backup Schedule

- **Pre-deploy**: Automatic backup before each deployment
- **Daily**: Cron job runs at midnight UTC
- **Retention**: 14 days locally, indefinite on S3

## S3 Setup (One-time)

### 1. Create S3 Bucket

```bash
aws s3 mb s3://panicradar-backups --region us-east-1
```

### 2. Create IAM Policy

Create a policy named `PanicRadarBackupPolicy`:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::panicradar-backups",
                "arn:aws:s3:::panicradar-backups/*"
            ]
        }
    ]
}
```

### 3. Attach to EC2 Instance Role

Option A: If EC2 has an instance role:
```bash
aws iam attach-role-policy \
  --role-name <your-ec2-role> \
  --policy-arn arn:aws:iam::<account-id>:policy/PanicRadarBackupPolicy
```

Option B: Create and attach a new role:
```bash
# Create role with EC2 trust policy
aws iam create-role \
  --role-name PanicRadarEC2Role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach backup policy
aws iam attach-role-policy \
  --role-name PanicRadarEC2Role \
  --policy-arn arn:aws:iam::<account-id>:policy/PanicRadarBackupPolicy

# Create instance profile
aws iam create-instance-profile --instance-profile-name PanicRadarProfile
aws iam add-role-to-instance-profile \
  --instance-profile-name PanicRadarProfile \
  --role-name PanicRadarEC2Role

# Attach to EC2 instance
aws ec2 associate-iam-instance-profile \
  --instance-id <instance-id> \
  --iam-instance-profile Name=PanicRadarProfile
```

### 4. Install AWS CLI on EC2 (if needed)

```bash
ssh -i ~/.ssh/panicradar-ec2.pem ec2-user@<ec2-ip>
sudo dnf install -y aws-cli
```

### 5. Verify Setup

```bash
# Test S3 access
aws s3 ls s3://panicradar-backups/

# Run manual backup
/home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh
```

## Backup Locations

### Local (EC2)
```
/opt/crypto-sentiment/backups/
├── sentiment_daily_20260203_000000.db
├── sentiment_predeploy_20260203_153000.db
└── orchestrator_state_20260203_000000.json
```

### S3
```
s3://panicradar-backups/
├── db/
│   └── 2026/02/
│       ├── sentiment_daily_20260203_000000.db
│       └── sentiment_daily_20260204_000000.db
└── state/
    └── 2026/02/
        └── orchestrator_state_20260203_000000.json
```

## Restore from Backup

### From Local Backup
```bash
# Stop services
docker stop crypto-api crypto-crawler

# Restore
cp /opt/crypto-sentiment/backups/sentiment_daily_YYYYMMDD_HHMMSS.db \
   /opt/crypto-sentiment/data/sentiment.db

# Restart services
docker start crypto-api crypto-crawler
```

### From S3 Backup
```bash
# Stop services
docker stop crypto-api crypto-crawler

# Download and restore
aws s3 cp s3://panicradar-backups/db/2026/02/sentiment_daily_YYYYMMDD_HHMMSS.db \
   /opt/crypto-sentiment/data/sentiment.db

# Restart services
docker start crypto-api crypto-crawler
```

## Monitoring

Check backup logs:
```bash
tail -f /opt/crypto-sentiment/logs/backup.log
```

List recent backups:
```bash
ls -lah /opt/crypto-sentiment/backups/
aws s3 ls s3://panicradar-backups/db/2026/02/ --human-readable
```
