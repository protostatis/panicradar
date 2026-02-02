#!/bin/bash
# EC2 Deployment Script for Crypto Sentiment Crawler
# This script creates an EC2 instance and deploys the application

set -e

# Configuration
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
KEY_NAME="${KEY_NAME:-crypto-sentiment-key}"
SECURITY_GROUP="${SECURITY_GROUP:-crypto-sentiment-sg}"
REGION="${AWS_REGION:-us-east-1}"
AMI_ID=""  # Will be auto-detected

echo "=== Crypto Sentiment Crawler - EC2 Deployment ==="
echo "Region: $REGION"
echo "Instance Type: $INSTANCE_TYPE"

# Check AWS credentials
echo ""
echo "Checking AWS credentials..."
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "ERROR: AWS credentials not configured."
    echo ""
    echo "Please run: aws configure"
    echo "You'll need:"
    echo "  - AWS Access Key ID"
    echo "  - AWS Secret Access Key"
    echo "  - Default region (e.g., us-east-1)"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "AWS Account: $ACCOUNT_ID"

# Get latest Amazon Linux 2023 AMI
echo ""
echo "Finding latest Amazon Linux 2023 AMI..."
AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
              "Name=state,Values=available" \
    --query "Images | sort_by(@, &CreationDate) | [-1].ImageId" \
    --output text \
    --region $REGION)
echo "AMI ID: $AMI_ID"

# Create key pair if not exists
echo ""
echo "Setting up SSH key pair..."
if ! aws ec2 describe-key-pairs --key-names $KEY_NAME --region $REGION > /dev/null 2>&1; then
    echo "Creating new key pair: $KEY_NAME"
    aws ec2 create-key-pair \
        --key-name $KEY_NAME \
        --query 'KeyMaterial' \
        --output text \
        --region $REGION > ~/.ssh/${KEY_NAME}.pem
    chmod 400 ~/.ssh/${KEY_NAME}.pem
    echo "Key saved to: ~/.ssh/${KEY_NAME}.pem"
else
    echo "Key pair already exists: $KEY_NAME"
fi

# Create security group if not exists
echo ""
echo "Setting up security group..."
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region $REGION)

if ! aws ec2 describe-security-groups --group-names $SECURITY_GROUP --region $REGION > /dev/null 2>&1; then
    echo "Creating security group: $SECURITY_GROUP"
    SG_ID=$(aws ec2 create-security-group \
        --group-name $SECURITY_GROUP \
        --description "Crypto Sentiment Crawler Security Group" \
        --vpc-id $VPC_ID \
        --query 'GroupId' \
        --output text \
        --region $REGION)

    # Allow SSH
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 22 \
        --cidr 0.0.0.0/0 \
        --region $REGION

    # Allow HTTP
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 80 \
        --cidr 0.0.0.0/0 \
        --region $REGION

    # Allow HTTPS
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 443 \
        --cidr 0.0.0.0/0 \
        --region $REGION

    echo "Security group created: $SG_ID"
else
    SG_ID=$(aws ec2 describe-security-groups --group-names $SECURITY_GROUP --query "SecurityGroups[0].GroupId" --output text --region $REGION)
    echo "Security group already exists: $SG_ID"
fi

# Create user data script for EC2 initialization
USER_DATA=$(cat << 'EOF'
#!/bin/bash
set -e

# Update system
dnf update -y

# Install Docker
dnf install -y docker git
systemctl start docker
systemctl enable docker

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Create app directory
mkdir -p /opt/crypto-sentiment
chown ec2-user:ec2-user /opt/crypto-sentiment

# Clone repository (placeholder - will be replaced with actual repo)
echo "EC2 instance ready for deployment"
EOF
)

# Launch EC2 instance
echo ""
echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type $INSTANCE_TYPE \
    --key-name $KEY_NAME \
    --security-group-ids $SG_ID \
    --user-data "$USER_DATA" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=crypto-sentiment-crawler}]" \
    --query 'Instances[0].InstanceId' \
    --output text \
    --region $REGION)

echo "Instance ID: $INSTANCE_ID"

# Wait for instance to be running
echo ""
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text \
    --region $REGION)

echo ""
echo "=== Deployment Complete ==="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "Wait 2-3 minutes for initialization, then:"
echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
echo ""
echo "To deploy the application:"
echo "  1. SSH into the instance"
echo "  2. Clone your repository"
echo "  3. Create .env file with your API keys"
echo "  4. Run: docker-compose up -d"
echo ""
echo "Dashboard will be available at: http://$PUBLIC_IP"
