# Security Guide - AI News Aggregator

This guide covers authentication and security options for your deployed dashboard.

---

## Quick Comparison

| Method | Difficulty | Security | UX | Best For |
|--------|-----------|----------|----|----|
| Basic Auth (Nginx) | ⭐ Easy | Good | Fair | Quick setup |
| Streamlit Auth | ⭐⭐ Medium | Good | Excellent | Multiple users |
| IP Whitelist | ⭐ Easy | Good | Excellent | Fixed IP |
| VPN/Tailscale | ⭐⭐ Medium | Excellent | Excellent | Remote access |
| OAuth (Google) | ⭐⭐⭐ Hard | Excellent | Excellent | Enterprise |

---

## Option 1: Basic Authentication (Nginx)

**Setup time:** 2 minutes
**Security:** Good for personal use
**Pros:** Simple, works immediately
**Cons:** Browser-based login (no logout button)

### Setup

```bash
# Run the auth setup script
chmod +x deployment/add-basic-auth.sh
./deployment/add-basic-auth.sh

# Enter password when prompted
```

### Manage Users

```bash
# Add a new user
sudo htpasswd /etc/nginx/.htpasswd newuser

# Change password
sudo htpasswd /etc/nginx/.htpasswd admin

# Remove a user
sudo htpasswd -D /etc/nginx/.htpasswd username
```

**Note:** RSS feed at `/rss/high_priority.xml` remains publicly accessible for RSS readers.

---

## Option 2: Streamlit-Authenticator (Recommended)

**Setup time:** 10 minutes
**Security:** Good
**Pros:** Native Streamlit, nice UX, logout button
**Cons:** Requires code changes

### Install

```bash
pip install streamlit-authenticator
```

### Implementation

Create `auth_config.yaml`:

```yaml
credentials:
  usernames:
    admin:
      email: you@example.com
      name: Admin User
      password: $2b$12$... # bcrypt hash (generate below)

cookie:
  expiry_days: 30
  key: random_signature_key_here  # Generate a random string
  name: ainews_auth
```

### Generate Password Hash

```python
import streamlit_authenticator as stauth

# Generate hashed password
hashed = stauth.Hasher(['your_password']).generate()
print(hashed[0])  # Use this in auth_config.yaml
```

### Add to dashboard.py

Add at the top of `dashboard.py`:

```python
import streamlit_authenticator as stauth
import yaml

# Load auth config
with open('auth_config.yaml') as file:
    auth_config = yaml.safe_load(file)

# Create authenticator
authenticator = stauth.Authenticate(
    auth_config['credentials'],
    auth_config['cookie']['name'],
    auth_config['cookie']['key'],
    auth_config['cookie']['expiry_days']
)

# Login form
name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status == False:
    st.error('Username/password is incorrect')
    st.stop()
elif authentication_status == None:
    st.warning('Please enter your username and password')
    st.stop()

# Add logout button in sidebar
authenticator.logout('Logout', 'sidebar')

# Rest of your dashboard code goes here...
```

**Docs:** https://github.com/mkhorasani/Streamlit-Authenticator

---

## Option 3: IP Whitelisting (AWS Security Groups)

**Setup time:** 1 minute
**Security:** Excellent
**Pros:** Simple, no login needed, very secure
**Cons:** Only works from fixed IPs

### Setup

```bash
# Get your current IP
curl -4 ifconfig.me

# Update EC2 security group
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr YOUR_IP/32

# Remove all other IPs access to port 80
# (Keep SSH port 22 open from your IP too!)
```

**Best for:** Home internet with static IP or office network

---

## Option 4: VPN Access (Tailscale)

**Setup time:** 5 minutes
**Security:** Excellent
**Pros:** Private network, works from anywhere, no public exposure
**Cons:** Need VPN client on devices

### Setup Tailscale

```bash
# Install Tailscale on EC2
curl -fsSL https://tailscale.com/install.sh | sh

# Start and authenticate
sudo tailscale up

# Get Tailscale IP
tailscale ip -4
```

### Update Nginx

```bash
# Only listen on Tailscale IP
sudo nano /etc/nginx/sites-available/ainews

# Change:
# listen 80;
# To:
# listen YOUR_TAILSCALE_IP:80;

sudo systemctl reload nginx
```

### Remove public access

```bash
# Remove HTTP from security group (keep SSH)
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0
```

**Access:** Install Tailscale on your devices, access via `http://TAILSCALE_IP`

---

## Option 5: OAuth (Google/GitHub)

**Setup time:** 30+ minutes
**Security:** Excellent
**Pros:** Enterprise-grade, SSO
**Cons:** Complex setup, requires domain

Use **Streamlit OAuth component**: https://github.com/dnplus/streamlit-oauth

---

## Recommended Approach

### For Personal Use:
1. **Start with:** IP Whitelist (if you have static IP)
2. **Or use:** Basic Auth (quick and easy)
3. **Upgrade to:** Streamlit-Authenticator (better UX)

### For Team Use:
1. **Use:** Streamlit-Authenticator (multiple users)
2. **Or:** VPN (Tailscale) for sensitive data
3. **Consider:** OAuth for enterprise

### For Public Demo:
1. **Use:** Streamlit-Authenticator with demo credentials
2. **Add:** Rate limiting via Nginx

---

## Additional Security

### 1. Enable HTTPS (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

### 2. Add Rate Limiting

Add to Nginx config:

```nginx
# Limit requests to 10 per second per IP
limit_req_zone $binary_remote_addr zone=dashboard:10m rate=10r/s;

server {
    location / {
        limit_req zone=dashboard burst=20;
        # ... rest of config
    }
}
```

### 3. Hide Streamlit Branding

Add to `~/.streamlit/config.toml`:

```toml
[server]
headless = true

[theme]
base = "dark"

[browser]
gatherUsageStats = false
```

### 4. Secure API Keys

Never commit `config.yaml`. Use AWS Secrets Manager in production:

```python
import boto3

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])
```

---

## Security Checklist

Before going live:

- [ ] Authentication enabled (Basic Auth minimum)
- [ ] HTTPS/SSL configured
- [ ] API keys in Secrets Manager (not in code)
- [ ] Security groups restrict access to needed ports only
- [ ] SSH key-based auth (disable password auth)
- [ ] Regular backups enabled
- [ ] CloudWatch monitoring set up
- [ ] Rate limiting configured
- [ ] Streamlit usage stats disabled
- [ ] Database file not publicly accessible

---

## Troubleshooting

### Basic Auth not working

```bash
# Check password file exists
sudo cat /etc/nginx/.htpasswd

# Test Nginx config
sudo nginx -t

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
```

### Locked out of Streamlit Auth

```bash
# Reset by editing auth_config.yaml
nano auth_config.yaml

# Or disable auth temporarily in dashboard.py
```

### Can't access after IP whitelist

```bash
# Check current IP
curl -4 ifconfig.me

# Update security group with new IP
```

---

## Cost Impact

- **Basic Auth:** $0 (included)
- **Streamlit Auth:** $0 (open source)
- **IP Whitelist:** $0 (AWS feature)
- **Tailscale:** $0 for personal use
- **OAuth:** $0 (Google/GitHub free tier)
- **SSL (Let's Encrypt):** $0

**Total security cost: $0** ✨
