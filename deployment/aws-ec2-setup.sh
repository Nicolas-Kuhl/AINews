#!/bin/bash
# AWS EC2 Deployment Script for AI News Aggregator
# Run this on a fresh Ubuntu 22.04 EC2 instance

set -e

echo "=== AI News Aggregator - EC2 Setup ==="

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.12
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev -y

# Install Nginx
sudo apt install nginx -y

# Create application directory
APP_DIR="/opt/ainews"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Clone or copy your application files
# (You'll need to upload your code to the instance first)
# For now, assuming code is already in current directory
cp -r . $APP_DIR/

# Create virtual environment
cd $APP_DIR
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps

# Create systemd service for Streamlit
sudo tee /etc/systemd/system/ainews-dashboard.service > /dev/null <<EOF
[Unit]
Description=AI News Aggregator Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/streamlit run dashboard.py --server.port 8501 --server.address 127.0.0.1
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Configure Nginx reverse proxy
sudo tee /etc/nginx/sites-available/ainews > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;  # Replace with your domain if you have one

    # Dashboard
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # RSS Feed
    location /rss {
        alias /opt/ainews/data;
        autoindex off;

        location ~ \.xml$ {
            add_header Content-Type application/rss+xml;
        }
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/ainews /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# Create cron job for fetch pipeline
(crontab -l 2>/dev/null || echo ""; echo "# AI News Aggregator - Run pipeline every 6 hours") | crontab -
(crontab -l; echo "0 */6 * * * cd $APP_DIR && $APP_DIR/venv/bin/python fetch_news.py >> $APP_DIR/data/pipeline.log 2>&1") | crontab -

# Start dashboard service
sudo systemctl daemon-reload
sudo systemctl enable ainews-dashboard
sudo systemctl start ainews-dashboard

# Set up config.yaml
echo "Setting up configuration..."
if [ ! -f "$APP_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"
    echo "IMPORTANT: Edit $APP_DIR/config.yaml and add your Anthropic API key!"
fi

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Edit config.yaml and add your Anthropic API key:"
echo "   nano $APP_DIR/config.yaml"
echo ""
echo "2. Check dashboard status:"
echo "   sudo systemctl status ainews-dashboard"
echo ""
echo "3. View dashboard logs:"
echo "   sudo journalctl -u ainews-dashboard -f"
echo ""
echo "4. Run the pipeline manually:"
echo "   cd $APP_DIR && ./venv/bin/python fetch_news.py"
echo ""
echo "5. Access dashboard at: http://YOUR_EC2_PUBLIC_IP/"
echo "6. RSS feed available at: http://YOUR_EC2_PUBLIC_IP/rss/high_priority.xml"
echo ""
echo "Don't forget to:"
echo "- Configure EC2 security group to allow HTTP (port 80)"
echo "- Set up an Elastic IP for a stable address"
echo "- Consider setting up SSL with Let's Encrypt (certbot)"
