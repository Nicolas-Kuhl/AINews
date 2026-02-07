# AWS Deployment Quick Start

Choose your deployment method based on your needs:

## 🚀 Fast & Simple: EC2 Deployment (5 minutes)

**Best for:** Getting started quickly, low traffic, learning

1. **Launch EC2 instance:**
   ```bash
   # Ubuntu 22.04, t3.small, 20GB storage
   # Security group: Allow ports 22, 80, 443
   ```

2. **Upload code and run setup:**
   ```bash
   scp -r ~/AINews ubuntu@YOUR_EC2_IP:/home/ubuntu/
   ssh ubuntu@YOUR_EC2_IP
   cd /home/ubuntu/AINews
   chmod +x deployment/aws-ec2-setup.sh
   ./deployment/aws-ec2-setup.sh
   ```

3. **Add API key:**
   ```bash
   nano /opt/ainews/config.yaml
   # Add your anthropic_api_key
   sudo systemctl restart ainews-dashboard
   ```

4. **Add authentication:**
   ```bash
   chmod +x deployment/add-basic-auth.sh
   ./deployment/add-basic-auth.sh
   ```

5. **Access:**
   - Dashboard: `http://YOUR_EC2_IP/` (login: admin)
   - RSS: `http://YOUR_EC2_IP/rss/high_priority.xml`

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
