# Secure Frappe v15 / ERPNext Local Docker Development & Multi-Device Git Setup

This repository provides a complete, security-hardened Docker development environment for **Frappe v15** and **ERPNext**, designed for custom app development and seamless multi-device Git synchronization without leaking credentials.

---

## 🏗 Architecture Overview

```
ERPNEXT/                               <-- Root Workspace (Docker Infrastructure)
├── .env.example                       # Environment Variable Template (Safe to Commit)
├── .env                               # Local Credentials & Secrets (GIT-IGNORED!)
├── .gitignore                         # Workspace gitignore (Excludes .env, sites/, backups)
├── .dockerignore                      # Build exclusions (Excludes .env, secrets)
├── docker-compose.yml                 # MariaDB 10.6, Redis Cache, Redis Queue, Frappe Bench
├── Dockerfile.dev                     # Frappe Bench v15 Dev Container definition
├── setup-dev.ps1 / setup-dev.sh       # Bootstrap automation scripts
└── apps/
    └── my_custom_app/                 <-- INDEPENDENT GIT REPOSITORY (GitHub/GitLab)
        ├── .gitignore                 # Custom App gitignore
        ├── my_custom_app/             # Application Python logic & JavaScript JS
        └── pyproject.toml / hooks.py  # App metadata
```

---

## 🔒 1. Secure Environment Setup

### Step 1.1: Clone/Initialize Root Infrastructure Workspace
On **Device A** (Primary Machine), initialize the root workspace directory:
```bash
git init
```

### Step 1.2: Create `.env` File from Template
Copy `.env.example` to `.env`:
```bash
# On Windows PowerShell:
Copy-Item .env.example .env

# On Linux / macOS:
cp .env.example .env
```

Open `.env` in your text editor and set your secure local credentials:
```env
SITE_NAME=development.localhost
HTTP_PORT=8000
DEVELOPER_MODE=1

DB_ROOT_PASSWORD=YourStrongLocalDbPassword123!
ADMIN_PASSWORD=YourStrongLocalAdminPassword123!
ENCRYPTION_KEY=32CharacterRandomSecretEncryptionKey!
```

> [!CAUTION]
> **Never commit `.env` to Git!** Verify that `.gitignore` contains `.env` before pushing any code.

### Step 1.3: Launch Docker Containers
Run the automated setup script or execute Docker Compose directly:

**PowerShell (Windows):**
```powershell
.\setup-dev.ps1
```

**Bash (Linux/macOS):**
```bash
chmod +x setup-dev.sh
./setup-dev.sh
```

Or manually:
```bash
docker compose up -d --build
```

---

## 🚀 2. Initializing Frappe Site & Creating Custom App

### Step 2.1: Access the Bench Container
Enter the running `frappe-bench` container:
```bash
docker exec -it frappe-bench bash
```

### Step 2.2: Create Frappe Site
Inside the container, run `bench new-site`:
```bash
bench new-site development.localhost \
  --admin-password SecretAdminPassword123! \
  --db-root-password SecretDbRootPassword123! \
  --no-mariadb-socket
```

Enable Developer Mode on the site:
```bash
bench --site development.localhost set-config developer_mode 1
bench use development.localhost
bench set-config -g webserver_port "${HTTP_PORT:-8000}"
bench setup procfile
```

The host and container HTTP ports must match. Frappe Socket.IO validates the
browser origin by calling the web process on that same port; mapping (for
example) host `8001` to container `8000` breaks authenticated realtime events.

*(Optional)* Install ERPNext if needed:
```bash
bench get-app erpnext --branch v15
bench --site development.localhost install-app erpnext
```

### Step 2.3: Create Custom App inside Container
Run `bench new-app` inside the container:
```bash
bench new-app my_custom_app
```
Follow the interactive prompts to set App Title, Description, Publisher, and License.

Install your custom app on the local site:
```bash
bench --site development.localhost install-app my_custom_app
```

---

## 🐙 3. Git Integration for Custom App

Because `apps/my_custom_app` is mounted as a volume from `./apps/my_custom_app` on your host machine, all code edits are instantly mirrored on your host machine.

### Step 3.1: Configure App Git Repository (Host Machine)
On your host machine, navigate to `apps/my_custom_app`:
```bash
cd apps/my_custom_app
```

Verify/Create `apps/my_custom_app/.gitignore`:
```gitignore
# Python cache & build artifacts
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Node / Web Assets
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Environment & IDE
.env
.vscode/
.idea/
.DS_Store
```

### Step 3.2: Connect App to Remote Repository (GitHub / GitLab)
Initialize Git (if not already created by `bench new-app`) and add your remote:
```bash
git init
git add .
git commit -m "feat: initial commit for my_custom_app"
git branch -M main
git remote add origin git@github.com:your-username/my_custom_app.git
git push -u origin main
```

---

## 💻 4. Multi-Device Secure Workflow (Setting up Device B)

To seamlessly work from a second device (Device B) without sharing passwords or private site data:

### Step 4.1: Clone Repositories on Device B
1. Clone the Root Docker Infrastructure Repo:
   ```bash
   git clone git@github.com:your-username/frappe-docker-dev.cmd ERPNEXT
   cd ERPNEXT
   ```
2. Clone your Custom App into `apps/my_custom_app`:
   ```bash
   mkdir -p apps
   git clone git@github.com:your-username/my_custom_app.git apps/my_custom_app
   ```

### Step 4.2: Configure Isolated `.env` on Device B
Create `.env` on Device B using `.env.example`:
```bash
cp .env.example .env
```
Update `.env` with passwords unique to Device B (or matching Device A if you prefer consistency).

### Step 4.3: Launch & Link on Device B
1. Start containers:
   ```bash
   docker compose up -d
   ```
2. Enter container and setup site:
   ```bash
   docker exec -it frappe-bench bash
   bench new-site development.localhost --admin-password LocalDevAdminPassword456! --db-root-password LocalDevDbPassword456!
   bench --site development.localhost set-config developer_mode 1
   bench --site development.localhost install-app my_custom_app
   ```

---

## 🔄 5. Multi-Device Code & Schema Sync Best Practices

### Synchronizing Application Code
- **Pushing changes from Device A**:
  ```bash
  cd apps/my_custom_app
  git add .
  git commit -m "feat: add custom DocType and API hooks"
  git push origin main
  ```
- **Pulling changes on Device B**:
  ```bash
  cd apps/my_custom_app
  git pull origin main
  ```

### Synchronizing Database Schemas & Customizations
Frappe automatically generates JSON schema files for DocTypes inside `apps/my_custom_app/my_custom_app/doctype/`. When you push these JSON files to Git, pulling them on Device B and running `bench migrate` applies the schema changes:

On **Device B** after pulling new code:
```bash
docker exec -it frappe-bench bench --site development.localhost migrate
```

### Exporting Fixtures (Custom Fields, Property Setters)
If you make customizations via the UI (e.g. Custom Fields, Property Setters), export them to your custom app's `hooks.py`:

1. In `apps/my_custom_app/my_custom_app/hooks.py`:
   ```python
   fixtures = [
       "Custom Field",
       "Property Setter"
   ]
   ```
2. Export fixtures to JSON files in your custom app:
   ```bash
   docker exec -it frappe-bench bench --site development.localhost export-fixtures
   ```
3. Commit the generated JSON files in `apps/my_custom_app/fixtures/` to Git. On Device B, `bench migrate` will import them automatically!

---

## 🛡 Security Checklist Summary

| Area | Practice | Implementation |
|---|---|---|
| **Credentials** | Isolated per environment | Stored exclusively in local `.env` |
| **Git Tracking** | Exclude sensitive files | `.gitignore` filters `.env`, `sites/`, backups, logs |
| **Docker Context** | Exclude secrets from builds | `.dockerignore` blocks secret files |
| **Custom App** | Isolated code repository | Independent Git repo in `apps/my_custom_app` |
| **Schema Sync** | Version control schema | DocType JSONs & `export-fixtures` committed to Git |
