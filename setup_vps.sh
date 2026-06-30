#!/bin/bash
# VPS Setup Script for NaviGo Blog Automation Agent

# Exit on error
set -e

echo "============================================="
echo "   NaviGo Blog Automation VPS Setup"
echo "============================================="

# 1. Verify Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed. Please install it first (e.g., sudo apt install python3 python3-venv python3-pip)"
    exit 1
fi
echo "[OK] Python 3 detected."

# 2. Make wrapper script executable
chmod +x run_vps_agent.sh
echo "[OK] Wrapper script set to executable."

# 3. Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "[OK] Virtual environment 'venv' created."
else
    echo "[OK] Virtual environment 'venv' already exists."
fi

# 4. Install dependencies
echo "Installing/upgrading dependencies..."
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
echo "[OK] Dependencies installed successfully."

# 5. Create logs directory
mkdir -p logs
echo "[OK] Logs directory created."

# 6. Check .env file
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "[IMPORTANT] Created '.env'. Please edit it and fill in your API keys and credentials!"
else
    echo "[OK] .env file already exists."
fi

# 7. Configure cron jobs
echo "Setting up crontab schedules..."
SCRIPT_PATH="$(pwd)/run_vps_agent.sh"
DAILY_LOG="$(pwd)/logs/daily_run.log"
BREAKING_LOG="$(pwd)/logs/breaking_run.log"

# Define cron lines
CRON_DAILY_1="30 6 * * * $SCRIPT_PATH daily >> $DAILY_LOG 2>&1"
CRON_DAILY_2="30 12 * * * $SCRIPT_PATH daily >> $DAILY_LOG 2>&1"
CRON_BREAKING="0 */4 * * * $SCRIPT_PATH breaking >> $BREAKING_LOG 2>&1"

# Get current crontab
tmp_cron=$(mktemp)
crontab -l 2>/dev/null > "$tmp_cron" || true

# Remove existing references to this script to prevent duplicates
sed -i "/run_vps_agent.sh/d" "$tmp_cron"

# Append new cron jobs
echo "$CRON_DAILY_1" >> "$tmp_cron"
echo "$CRON_DAILY_2" >> "$tmp_cron"
echo "$CRON_BREAKING" >> "$tmp_cron"

# Install new crontab
crontab "$tmp_cron"
rm "$tmp_cron"

echo "[OK] Cron jobs added successfully to crontab!"
echo "---------------------------------------------"
echo "Cron Schedule Installed:"
echo "  - Daily Blog Generation: 6:30 AM & 12:30 PM (VPS local time)"
echo "  - Breaking News Detector: Every 4 hours"
echo "---------------------------------------------"
echo "Setup complete! Please make sure to fill in your API secrets in the .env file."
echo "If you want the VPS to push history back to GitHub automatically,"
echo "ensure you have run 'git config --global user.name' / 'user.email' and set up SSH keys."
echo "============================================="
