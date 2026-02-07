# Connectivity Verification Guide

## How It Works

### EC2 Deployment Architecture

```
Internet ──> EC2 Security Group (Port 80)
         ──> Nginx (0.0.0.0:80 - all interfaces)
         ──> Streamlit (127.0.0.1:8501 - localhost only)
```

**Why this setup?**
- ✅ **Secure:** Streamlit not directly exposed to internet
- ✅ **Standard:** Industry-standard reverse proxy pattern
- ✅ **Flexible:** Easy to add SSL, auth, rate limiting at Nginx level

## Pre-Deployment Checklist

### 1. EC2 Security Group Configuration

Your security group **MUST** allow:

| Type | Protocol | Port | Source | Purpose |
|------|----------|------|--------|---------|
| HTTP | TCP | 80 | 0.0.0.0/0 | Dashboard access |
| HTTPS | TCP | 443 | 0.0.0.0/0 | SSL (optional) |
| SSH | TCP | 22 | YOUR_IP/32 | Management |

**Critical:** Without port 80 open, your dashboard won't be accessible from the internet!

#### How to Configure Security Group:

**Via AWS Console:**
1. Go to EC2 → Security Groups
2. Select your instance's security group
3. Click "Edit inbound rules"
4. Add rule: HTTP, TCP, 80, Source: 0.0.0.0/0
5. Save rules

**Via AWS CLI:**
```bash
# Get your security group ID
aws ec2 describe-instances --instance-ids i-xxxxx \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId'

# Allow HTTP from anywhere
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

# Allow SSH from your IP only
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 22 \
  --cidr $(curl -s ifconfig.me)/32
```

### 2. Verify Nginx Configuration

```bash
# Check Nginx is listening on all interfaces
sudo netstat -tulpn | grep :80
# Should show: 0.0.0.0:80 (not 127.0.0.1:80)

# Check Nginx configuration
sudo nginx -t

# Check Nginx status
sudo systemctl status nginx

# View Nginx access logs
sudo tail -f /var/log/nginx/access.log
```

### 3. Verify Streamlit Service

```bash
# Check Streamlit is running
sudo systemctl status ainews-dashboard

# Check Streamlit is listening on localhost
sudo netstat -tulpn | grep :8501
# Should show: 127.0.0.1:8501 (correct - not exposed)

# View Streamlit logs
sudo journalctl -u ainews-dashboard -f
```

## Testing Connectivity

### From the EC2 Instance (SSH):

```bash
# Test Streamlit directly
curl http://127.0.0.1:8501
# Should return HTML

# Test Nginx
curl http://localhost
# Should return Streamlit HTML (proxied)

# Test from external IP (simulates internet access)
curl http://$(curl -s ifconfig.me)
# Should return Streamlit HTML
```

### From Your Computer:

```bash
# Get EC2 public IP
# (From EC2 console or: ssh ec2-user@... 'curl -s ifconfig.me')

# Test HTTP access
curl http://YOUR_EC2_PUBLIC_IP

# Test in browser
open http://YOUR_EC2_PUBLIC_IP
```

### Expected Results:

✅ **Working:**
- Browser shows Streamlit dashboard
- curl returns HTML content
- No connection refused errors

❌ **Not Working:**
- "Connection refused" → Security group blocking port 80
- "Timeout" → Security group blocking or Nginx not running
- "502 Bad Gateway" → Nginx running but Streamlit down

## Troubleshooting

### Issue: Can't Connect from Browser

**Symptom:** Connection timeout or refused

**Solutions:**
1. **Check security group allows port 80**
   ```bash
   aws ec2 describe-security-groups --group-ids sg-xxxxx \
     --query 'SecurityGroups[0].IpPermissions'
   ```

2. **Check Nginx is running**
   ```bash
   sudo systemctl status nginx
   sudo systemctl start nginx  # if not running
   ```

3. **Check Nginx is listening on all interfaces**
   ```bash
   sudo netstat -tulpn | grep :80
   # Should show: 0.0.0.0:80
   ```

4. **Check EC2 public IP is correct**
   ```bash
   curl -4 ifconfig.me
   ```

### Issue: 502 Bad Gateway

**Symptom:** Nginx loads but shows error

**Solutions:**
1. **Check Streamlit is running**
   ```bash
   sudo systemctl status ainews-dashboard
   sudo systemctl start ainews-dashboard  # if not running
   ```

2. **Check Streamlit logs for errors**
   ```bash
   sudo journalctl -u ainews-dashboard -n 50
   ```

3. **Verify config.yaml exists with API key**
   ```bash
   cat /opt/ainews/config.yaml
   ```

### Issue: RSS Feed Not Accessible

**Symptom:** `/rss/high_priority.xml` returns 404

**Solutions:**
1. **Check RSS file exists**
   ```bash
   ls -la /opt/ainews/data/high_priority.xml
   ```

2. **Generate RSS feed manually**
   ```bash
   cd /opt/ainews
   ./venv/bin/python generate_rss_feed.py
   ```

3. **Check Nginx RSS configuration**
   ```bash
   sudo nginx -t
   curl http://localhost/rss/high_priority.xml
   ```

## Firewall Considerations

### UFW (Ubuntu Firewall)

If UFW is enabled:

```bash
# Check UFW status
sudo ufw status

# Allow HTTP
sudo ufw allow 80/tcp

# Allow HTTPS (if using SSL)
sudo ufw allow 443/tcp

# Allow SSH
sudo ufw allow 22/tcp
```

### Cloud Firewall

Some AWS regions/VPCs have additional firewall layers. Ensure:
- VPC has internet gateway attached
- Route table has 0.0.0.0/0 → igw-xxxxx
- Network ACLs allow inbound 80/443

## Performance Testing

### Check Response Time

```bash
# Measure response time
time curl -s http://YOUR_EC2_IP >/dev/null

# Load test (requires apache2-utils)
ab -n 100 -c 10 http://YOUR_EC2_IP/
```

### Monitor Connections

```bash
# Active connections to Nginx
sudo ss -ant | grep :80 | wc -l

# Active connections to Streamlit
sudo ss -ant | grep :8501 | wc -l
```

## Security Verification

### Check Open Ports

```bash
# From outside (replace with your EC2 IP)
nmap YOUR_EC2_IP

# Should only show:
# 22/tcp open  ssh
# 80/tcp open  http
```

### Verify Streamlit Not Exposed

```bash
# This should FAIL (timeout):
telnet YOUR_EC2_IP 8501

# This should SUCCEED:
ssh ec2-user@YOUR_EC2_IP 'telnet localhost 8501'
```

**If port 8501 is accessible from internet, your Streamlit is exposed! Fix the systemd service to bind to 127.0.0.1 only.**

## Summary

✅ **Correct Setup:**
- Nginx listens on `0.0.0.0:80` (all interfaces)
- Streamlit listens on `127.0.0.1:8501` (localhost only)
- Security group allows port 80
- Dashboard accessible from internet via Nginx proxy

❌ **Insecure Setup (DON'T DO THIS):**
- Streamlit listening on `0.0.0.0:8501`
- Port 8501 open in security group
- Direct Streamlit exposure to internet

---

Need help? Check the main troubleshooting guide: [README-AWS.md](README-AWS.md#troubleshooting)
