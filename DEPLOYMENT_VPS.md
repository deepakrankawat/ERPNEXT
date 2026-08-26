# Production VPS Deployment & GitHub Guide

This guide provides instructions for pushing this repository to GitHub and deploying the complete **ERPNext & Lexocrates LPO Stack** onto a Linux VPS (Ubuntu 22.04 / 24.04 or Debian 12).

---

## 1. GitHub Push Instructions

### Step 1: Create GitHub Repositories
Create GitHub repositories for your setup:
1. Main Orchestration Repo (e.g., `your-org/erpnext-lpo-deployment`)
2. Custom App Repo (e.g., `your-org/lex`)
3. Custom ERPNext App Repo (e.g., `your-org/erpnext_custom`)

### Step 2: Push Main Bench Orchestration Project
From the root project directory (`c:\Users\Lexocrates\Desktop\ERPNEXT`):
```bash
git add .
git commit -m "feat: prepare ERPNext & LPO stack for production VPS deployment"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_ORCHESTRATION_REPO.git
git branch -M main
git push -u origin main
```

### Step 3: Push Custom App Repositories
#### A. Custom App `lex` (`lpo_msg`):
```bash
cd apps/lex
git remote add origin https://github.com/YOUR_USERNAME/lex.git
git push -u origin develop
```

#### B. Custom App `erpnext_custom`:
```bash
cd apps/erpnext_custom
git remote add origin https://github.com/YOUR_USERNAME/erpnext_custom.git
git push -u origin develop
```

---

## 2. VPS Deployment Guide

### Prerequisites
* Linux VPS (Ubuntu 22.04 LTS / 24.04 LTS or Debian 12) with at least 4GB RAM & 2 CPU cores.
* Domain DNS `A Record` pointing your domain (e.g., `erp.yourdomain.com`) to your VPS IP address.
* Installed software: `git`, `docker`, `docker-compose-plugin`.

### Step 1: Clone Repository on VPS
Connect to your VPS via SSH and clone the main repository:
```bash
git clone --recursive https://github.com/YOUR_USERNAME/YOUR_ORCHESTRATION_REPO.git /opt/erpnext-lpo
cd /opt/erpnext-lpo
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and set your production credentials:
```bash
cp .env.example .env
nano .env
```
Replace every `CHANGE_ME` value and ensure:
* `SITE_NAME=erp.yourdomain.com`
* `DB_ROOT_PASSWORD=YourStrongDatabasePasswordHere!`
* `ADMIN_PASSWORD=YourStrongAdminPasswordHere!`
* `DEVELOPER_MODE=0`

The deployment script intentionally refuses development hostnames, default passwords, missing secrets, or developer mode. The production Compose stack runs separate Gunicorn web, Socket.IO, scheduler, short/default worker, long worker, MariaDB, Redis, and ClamAV updater services.

### Step 3: Execute Automated VPS Deployment
Run the complete application/controller/architecture suite before deployment:
```bash
cd /path/to/frappe-bench
bash apps/lex/scripts/run_full_tests.sh your-staging-site.example.com
```

Run the automated deployment script:
```bash
chmod +x deploy-vps.sh
./deploy-vps.sh
```

---

## 3. Nginx Reverse Proxy & SSL (HTTPS) Setup

To secure your ERPNext instance with a free Let's Encrypt SSL certificate:

### Step 1: Install Nginx & Certbot
```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Step 2: Configure Nginx Site Block
Create `/etc/nginx/sites-available/erpnext`:
```nginx
# Map block for dynamic WebSocket connection upgrade
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    server_name erp.yourdomain.com;

    # Maximum file upload size for Frappe/ERPNext attachments
    client_max_body_size 100M;

    # Main Frappe HTTP Application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Realtime Socket.IO Messaging & Chat
    location /socket.io {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Origin $http_origin;

        # Keep WebSocket connection alive (prevent 60s drop)
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

Enable the configuration:
```bash
sudo ln -s /etc/nginx/sites-available/erpnext /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 3: Issue SSL Certificate
```bash
sudo certbot --nginx -d erp.yourdomain.com
```

---

## 4. Database Backup & Maintenance

### Take On-Demand Backup
```bash
docker compose -f docker-compose.prod.yml exec -T frappe-web bench --site erp.yourdomain.com backup --with-files
```
Backups are saved in `./sites/erp.yourdomain.com/private/backups/`.

### Automated Daily Backup Cron Job
Add to root crontab (`sudo crontab -e`):
```cron
0 2 * * * cd /opt/erpnext-lpo && docker compose -f docker-compose.prod.yml exec -T frappe-web bench --site erp.yourdomain.com backup --with-files > /dev/null 2>&1
```
