#!/bin/bash
# Add HTTP Basic Authentication to Nginx

set -e

echo "=== Adding Basic Authentication to AI News Dashboard ==="

# Install apache2-utils for htpasswd
sudo apt-get update
sudo apt-get install -y apache2-utils

# Create password file
echo "Creating password for user 'admin'..."
sudo htpasswd -c /etc/nginx/.htpasswd admin

# Update Nginx config to add auth
sudo tee /etc/nginx/sites-available/ainews > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    # Basic Authentication
    auth_basic "AI News Dashboard";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # Dashboard
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # RSS Feed (no auth required for RSS readers)
    location /rss {
        auth_basic off;  # Allow public RSS access
        alias /opt/ainews/data;
        autoindex off;

        location ~ \.xml$ {
            add_header Content-Type application/rss+xml;
        }
    }
}
EOF

# Test and reload Nginx
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "✓ Basic Authentication enabled!"
echo ""
echo "Dashboard: http://YOUR_EC2_IP/"
echo "Username: admin"
echo "Password: (the password you just entered)"
echo ""
echo "To add more users:"
echo "  sudo htpasswd /etc/nginx/.htpasswd newusername"
echo ""
echo "To change password:"
echo "  sudo htpasswd /etc/nginx/.htpasswd admin"
