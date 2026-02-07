# AWS Deployment Guide - AI News Aggregator

This guide provides two deployment options for AWS: a simple EC2 deployment and a production-ready serverless architecture.

---

## Option 1: Simple EC2 Deployment

**Best for:** Quick setup, low traffic, cost-sensitive deployments

**Monthly Cost:** ~$10-20 (t3.small instance)

### Architecture
```
User → EC2 (Nginx) → Streamlit Dashboard
                   → RSS Feed (static file)
Cron Job → Fetch Pipeline
```

### Prerequisites
- AWS account
- EC2 key pair created
- Basic Linux knowledge

### Step 1: Launch EC2 Instance

1. **Launch an EC2 instance:**
   - **AMI:** Ubuntu 22.04 LTS or Amazon Linux 2023
   - Instance type: `t3.small` (2 vCPU, 2GB RAM)
   - Storage: 20GB gp3
   - Security group: Allow inbound SSH (22), HTTP (80), HTTPS (443)

2. **Allocate Elastic IP** (optional but recommended)

**Note:** The deployment script auto-detects your OS and uses the appropriate package manager (apt for Ubuntu, dnf for AL2023).

### Step 2: Deploy Application

SSH into your instance and run:

```bash
# Upload your code (use 'ubuntu' for Ubuntu, 'ec2-user' for Amazon Linux)
scp -r ~/AINews ubuntu@YOUR_EC2_IP:/home/ubuntu/
# OR for Amazon Linux:
# scp -r ~/AINews ec2-user@YOUR_EC2_IP:/home/ec2-user/

# SSH into instance
ssh ubuntu@YOUR_EC2_IP
# OR for Amazon Linux:
# ssh ec2-user@YOUR_EC2_IP

# Run setup script (adjust path based on your user)
cd ~/AINews
chmod +x deployment/aws-ec2-setup.sh
./deployment/aws-ec2-setup.sh
```

### Step 3: Configure

```bash
# Edit config with your API key
nano /opt/ainews/config.yaml

# Restart dashboard
sudo systemctl restart ainews-dashboard
```

### Step 4: Add Authentication (Recommended)

**⚠️ Important:** The dashboard has no authentication by default. Anyone with the URL can access it.

```bash
# Quick: Add Basic Authentication
chmod +x deployment/add-basic-auth.sh
./deployment/add-basic-auth.sh
```

See **[SECURITY.md](SECURITY.md)** for all authentication options.

### Step 5: Configure Security Group ⚠️

**CRITICAL:** Your EC2 security group must allow inbound HTTP traffic!

```bash
# Allow HTTP from anywhere
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0
```

Or via AWS Console: **EC2 → Security Groups → Edit Inbound Rules → Add HTTP (port 80)**

### Step 6: Access & Verify

- **Dashboard:** `http://YOUR_EC2_IP/`
- **RSS Feed:** `http://YOUR_EC2_IP/rss/high_priority.xml`

**Test connectivity:**
```bash
# From your computer
curl http://YOUR_EC2_PUBLIC_IP

# Should return HTML (Streamlit dashboard)
```

**Can't connect?** See **[CONNECTIVITY.md](CONNECTIVITY.md)** for detailed troubleshooting.

### Optional: Add SSL Certificate

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Get SSL certificate (replace with your domain)
sudo certbot --nginx -d yourdomain.com

# Auto-renewal is configured automatically
```

### Maintenance

```bash
# View dashboard logs
sudo journalctl -u ainews-dashboard -f

# View pipeline logs
tail -f /opt/ainews/data/pipeline.log

# Restart dashboard
sudo systemctl restart ainews-dashboard

# Check cron jobs
crontab -l

# Manual pipeline run
cd /opt/ainews && ./venv/bin/python fetch_news.py
```

### Adjust Pipeline Frequency

By default, the pipeline runs **every 15 minutes**. To change this:

```bash
# Edit crontab
crontab -e

# Current: */15 * * * * (every 15 minutes)
# Hourly: 0 * * * *
# Every 30 min: */30 * * * *
# Every 6 hours: 0 */6 * * *
# Daily at 9am: 0 9 * * *
```

**Note:** More frequent runs = more API calls to Anthropic. Monitor your usage and costs.

---

## Option 2: Production AWS Deployment

**Best for:** High availability, scalability, production workloads

**Monthly Cost:** ~$30-50 (depending on usage)

### Architecture
```
User → CloudFront → S3 (RSS Feed)
     → ALB → App Runner (Dashboard)

EventBridge Scheduler → ECS Fargate Task (Pipeline)
                      ↓
                    EFS (Database)
                      ↑
                    App Runner
```

### Prerequisites
- AWS CLI configured
- Docker installed locally
- AWS account with appropriate permissions

### Step 1: Create Dockerfile

Already created at `deployment/Dockerfile` (see below)

### Step 2: Set Up Infrastructure

We'll use CloudFormation or Terraform. Here's the manual approach:

#### 2.1: Create EFS for Database

```bash
# Create EFS file system
aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --encrypted \
  --tags Key=Name,Value=ainews-db

# Note the FileSystemId from output
EFS_ID=fs-xxxxxxxxx

# Create mount targets in your VPC subnets
aws efs create-mount-target \
  --file-system-id $EFS_ID \
  --subnet-id subnet-xxxxxxxx \
  --security-groups sg-xxxxxxxx
```

#### 2.2: Create S3 Bucket for RSS Feed

```bash
# Create bucket
aws s3 mb s3://ainews-rss-feed-YOURUNIQUEID

# Enable public read for RSS
aws s3api put-bucket-policy \
  --bucket ainews-rss-feed-YOURUNIQUEID \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::ainews-rss-feed-YOURUNIQUEID/high_priority.xml"
    }]
  }'
```

#### 2.3: Store API Key in Secrets Manager

```bash
aws secretsmanager create-secret \
  --name ainews/anthropic-api-key \
  --secret-string "your-anthropic-api-key"
```

#### 2.4: Build and Push Docker Image to ECR

```bash
# Create ECR repository
aws ecr create-repository --repository-name ainews

# Get login token
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Build image
cd deployment
docker build -t ainews .

# Tag and push
docker tag ainews:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ainews:latest
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ainews:latest
```

#### 2.5: Deploy Dashboard to App Runner

```bash
# Create apprunner.yaml configuration
# Then deploy via AWS Console or CLI

aws apprunner create-service \
  --service-name ainews-dashboard \
  --source-configuration '{
    "ImageRepository": {
      "ImageIdentifier": "ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ainews:latest",
      "ImageRepositoryType": "ECR"
    },
    "AutoDeploymentsEnabled": false
  }' \
  --instance-configuration '{
    "Cpu": "1 vCPU",
    "Memory": "2 GB"
  }'
```

#### 2.6: Create ECS Task for Pipeline

Create an ECS task definition for the pipeline and an EventBridge Scheduler rule to run it every 15 minutes:

```bash
# Create EventBridge rule (every 15 minutes)
aws events put-rule \
  --name ainews-pipeline-schedule \
  --schedule-expression "rate(15 minutes)" \
  --state ENABLED

# Add ECS task as target
# (This requires creating ECS task definition first - see AWS ECS documentation)
```

**Adjust frequency:** Change `rate(15 minutes)` to:
- `rate(30 minutes)` - Every 30 minutes
- `rate(1 hour)` - Hourly
- `rate(6 hours)` - Every 6 hours
- `cron(0 9 * * ? *)` - Daily at 9am UTC

#### 2.7: Set Up CloudFront Distribution

Point CloudFront to S3 bucket for RSS feed distribution with caching.

### Environment Variables

Set these in App Runner and ECS:
- `ANTHROPIC_API_KEY_SECRET_ARN`: ARN of Secrets Manager secret
- `EFS_MOUNT_PATH`: `/mnt/efs`
- `RSS_S3_BUCKET`: Your S3 bucket name

### Monitoring

- CloudWatch Logs for application logs
- CloudWatch Metrics for resource usage
- CloudWatch Alarms for error rates

---

## Cost Comparison

| Component | EC2 | App Runner + ECS |
|-----------|-----|------------------|
| Compute | $15/mo (t3.small) | $25/mo (App Runner + ECS tasks) |
| Storage | Included | $3/mo (EFS) |
| Data Transfer | $1/mo | $2/mo (CloudFront) |
| **Total** | **~$16/mo** | **~$30/mo** |

---

## Security Best Practices

1. **Never commit API keys** - Use Secrets Manager or environment variables
2. **Enable VPC** - Run services in private subnets
3. **Use IAM roles** - No hardcoded credentials
4. **Enable encryption** - For EFS and S3
5. **Set up CloudWatch Alarms** - Monitor for errors
6. **Regular updates** - Keep dependencies updated
7. **Rate limiting** - Use AWS WAF if publicly accessible

---

## Scaling Considerations

- **EC2 Approach**: Upgrade instance size or add auto-scaling group
- **App Runner Approach**: Auto-scales automatically
- **Database**: Consider migrating from SQLite to RDS for high concurrency

---

## Troubleshooting

### Dashboard won't start
```bash
# Check logs
sudo journalctl -u ainews-dashboard -f

# Check if port is already in use
sudo netstat -tulpn | grep 8501

# Restart service
sudo systemctl restart ainews-dashboard
```

### Pipeline fails
```bash
# Check cron logs
tail -f /opt/ainews/data/pipeline.log

# Run manually to see errors
cd /opt/ainews && ./venv/bin/python fetch_news.py
```

### RSS feed not accessible
```bash
# Check Nginx config
sudo nginx -t

# Check file permissions
ls -la /opt/ainews/data/high_priority.xml

# Restart Nginx
sudo systemctl restart nginx
```
