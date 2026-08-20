#!/bin/bash
# ==============================================================================
# Automated VPS Deployment Script for ERPNext & Lexocrates LPO Application
# Works on Ubuntu 20.04 / 22.04 / 24.04 & Debian 11 / 12
# ==============================================================================

set -e

echo -e "\e[36m==========================================================\e[0m"
echo -e "\e[36m   Lexocrates LPO & ERPNext VPS Deployment Bootstrap       \e[0m"
echo -e "\e[36m==========================================================\e[0m"

# 1. Environment check
if [ ! -f ".env" ]; then
    echo -e "\e[33m[1/6] Creating .env file from .env.example...\e[0m"
    cp .env.example .env
    echo -e "\e[32mCreated .env! Please review credentials if needed.\e[0m"
else
    echo -e "\e[32m[1/6] .env configuration file found.\e[0m"
fi

# 2. Check Docker installation
if ! command -v docker &> /dev/null; then
    echo -e "\e[31mDocker is not installed. Please install Docker and Docker Compose before running this script.\e[0m"
    exit 1
fi

# 3. Build & start containers
echo -e "\e[33m[2/6] Building and launching production Docker containers...\e[0m"
docker compose -f docker-compose.prod.yml up -d --build

# 4. Wait for MariaDB health check
echo -e "\e[33m[3/6] Waiting 15 seconds for MariaDB container initialization...\e[0m"
sleep 15

# 5. Check Bench site initialization
SITE_NAME=$(grep SITE_NAME .env | cut -d '=' -f2 | tr -d '\r' || echo "development.localhost")
ADMIN_PASS=$(grep ADMIN_PASSWORD .env | cut -d '=' -f2 | tr -d '\r' || echo "admin")
DB_ROOT_PASS=$(grep DB_ROOT_PASSWORD .env | cut -d '=' -f2 | tr -d '\r' || echo "SecretDbRootPassword123!")

echo -e "\e[33m[4/6] Verifying site setup for ${SITE_NAME}...\e[0m"
docker exec frappe-bench bench --site ${SITE_NAME} migrate || {
    echo -e "\e[33mInitializing new site ${SITE_NAME}...\e[0m"
    docker exec frappe-bench bench new-site ${SITE_NAME} --admin-password ${ADMIN_PASS} --db-root-password ${DB_ROOT_PASS}
}

# 6. Install custom apps
echo -e "\e[33m[5/6] Installing LPO custom apps (lex, erpnext_custom)...\e[0m"
docker exec frappe-bench bench --site ${SITE_NAME} install-app lex || true
docker exec frappe-bench bench --site ${SITE_NAME} install-app erpnext_custom || true

# 7. Migrate & clear cache
echo -e "\e[33m[6/6] Running bench migrate and clearing cache...\e[0m"
docker exec frappe-bench bench --site ${SITE_NAME} migrate
docker exec frappe-bench bench --site ${SITE_NAME} clear-cache

echo -e "\e[32m==========================================================\e[0m"
echo -e "\e[32m   Deployment Successful!                                  \e[0m"
echo -e "\e[32m   Site URL: http://${SITE_NAME}:8000                     \e[0m"
echo -e "\e[32m==========================================================\e[0m"
