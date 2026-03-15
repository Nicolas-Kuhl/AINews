# AWS Deployment Quick Start

Choose your deployment method based on your needs:

## 🚀 Fast & Simple: EC2 Deployment (5 minutes)

**Best for:** Getting started quickly, low traffic, learning

1. **Launch EC2 instance:**
   ```bash
   # Ubuntu 22.04+ or Amazon Linux 2023
   # Instance: t3.small, 20GB storage
   # Security group: Allow ports 22, 80, 443
   ```

2. **Clone repository and run setup:**
   ```bash
   # SSH into instance (Ubuntu or Amazon Linux)
   ssh ubuntu@YOUR_EC2_IP  # or ec2-user@YOUR_EC2_IP

   # Clone to /opt/ainews (lowercase)
   sudo mkdir -p /opt
   cd /opt
   sudo git clone https://github.com/Nicolas-Kuhl/AINews ainews
   sudo chown -R $USER:$USER /opt/ainews

   # Run setup (auto-detects OS, prompts for API key)
   cd /opt/ainews/deployment
   chmod +x aws-ec2-setup.sh
   ./aws-ec2-setup.sh
   ```

3. **Configure (if needed):**
   ```bash
   # If you skipped API key during setup:
   nano /opt/ainews/config.yaml
   sudo systemctl restart ainews-dashboard
   ```

4. **Add authentication:**
   ```bash
   chmod +x deployment/add-basic-auth.sh
   ./deployment/add-basic-auth.sh
   ```

5. **Set up cron jobs:**
   ```bash
   crontab -e
   # Trusted sources every 15 min
   */15 * * * * cd /opt/ainews && /opt/ainews/venv/bin/python fetch_news.py --category trusted >> /opt/ainews/data/pipeline.log 2>&1
   # Open sources + newsletters daily at 5am AEDT (18:00 UTC)
   0 18 * * * cd /opt/ainews && . /opt/ainews/.env && export AINEWS_EMAIL_PASSWORD && /opt/ainews/venv/bin/python fetch_news.py --category open >> /opt/ainews/data/pipeline.log 2>&1
   ```

6. **Access:**
   - Dashboard: `http://YOUR_EC2_IP/` (login: admin)
   - Combined RSS (8+): `http://YOUR_EC2_IP/rss/high_priority.xml`
   - Trusted RSS (all): `http://YOUR_EC2_IP/rss/high_priority_trusted.xml`
   - Digest RSS (7+): `http://YOUR_EC2_IP/rss/high_priority_digest.xml`

**Monthly cost:** ~$15

**📖 See [SECURITY.md](SECURITY.md) for all auth options**

---

## 🏢 Production: App Runner + ECS (30 minutes)

**Best for:** Production workloads, auto-scaling, high availability

See [README-AWS.md](README-AWS.md#option-2-production-aws-deployment) for full guide.

**Quick steps:**
1. Build and push Docker image to ECR
2. Create EFS for database
3. Deploy dashboard to App Runner
4. Set up ECS scheduled task for pipeline
5. Configure S3 + CloudFront for RSS

**Monthly cost:** ~$30-50

---

## 🐳 Local Testing: Docker (1 minute)

Test before deploying:

```bash
# Create config.yaml with your API key
cp config.example.yaml config.yaml
nano config.yaml  # Add API key

# Start dashboard
docker-compose up dashboard

# Run pipeline manually
docker-compose run pipeline

# Access at http://localhost:8501
```

---

## 📊 Comparison

| Feature | EC2 | App Runner + ECS | Docker Local |
|---------|-----|------------------|--------------|
| Setup Time | 5 min | 30 min | 1 min |
| Cost/month | $15 | $30-50 | $0 |
| Auto-scaling | ❌ | ✅ | ❌ |
| High Availability | ❌ | ✅ | ❌ |
| Maintenance | Medium | Low | N/A |
| Best for | Small projects | Production | Development |

---

## 🔒 Security Checklist

Before going live:

- [ ] **Authentication enabled** (Basic Auth minimum) - See [SECURITY.md](SECURITY.md)
- [ ] API key stored in Secrets Manager (not in code)
- [ ] Security groups configured (minimal ports)
- [ ] SSL/HTTPS enabled (Let's Encrypt)
- [ ] CloudWatch monitoring set up
- [ ] Regular backups configured
- [ ] IAM roles with least privilege
- [ ] VPC with private subnets (production)

**⚠️ Critical:** By default, the dashboard has no authentication. Anyone with the URL can access it.

---

## 🆘 Need Help?

- **EC2 deployment issues:** Check `/opt/ainews/data/pipeline.log`
- **Dashboard not loading:** `sudo journalctl -u ainews-dashboard -f`
- **Pipeline failing:** Run manually to see errors: `python fetch_news.py`

For detailed troubleshooting, see [README-AWS.md](README-AWS.md#troubleshooting)
