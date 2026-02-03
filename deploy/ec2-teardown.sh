#!/bin/bash
# Teardown EC2 resources
# Usage: ./ec2-teardown.sh [INSTANCE_ID]

set -e

REGION="${AWS_REGION:-us-east-1}"
INSTANCE_ID="${1:-}"

echo "=== EC2 Teardown ==="

# Check AWS credentials
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "ERROR: AWS credentials not configured."
    exit 1
fi

# Find instance if not provided
if [ -z "$INSTANCE_ID" ]; then
    echo "Finding crypto-sentiment-crawler instance..."
    INSTANCE_ID=$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=crypto-sentiment-crawler" "Name=instance-state-name,Values=running,stopped" \
        --query "Reservations[0].Instances[0].InstanceId" \
        --output text \
        --region $REGION)

    if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
        echo "No running instance found with tag 'crypto-sentiment-crawler'"
        exit 0
    fi
fi

echo "Instance ID: $INSTANCE_ID"

# Confirm deletion
read -p "Are you sure you want to terminate this instance? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Terminate instance
echo "Terminating instance..."
aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION > /dev/null

echo "Waiting for termination..."
aws ec2 wait instance-terminated --instance-ids $INSTANCE_ID --region $REGION

echo ""
echo "=== Instance Terminated ==="
echo ""
echo "Note: Security group and key pair are preserved for future use."
echo "To delete them manually:"
echo "  aws ec2 delete-security-group --group-name crypto-sentiment-sg --region $REGION"
echo "  aws ec2 delete-key-pair --key-name crypto-sentiment-key --region $REGION"
echo "  rm ~/.ssh/crypto-sentiment-key.pem"
