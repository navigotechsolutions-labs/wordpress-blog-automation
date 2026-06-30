#!/bin/bash
# Move to the script's directory
cd "$(dirname "$0")"

# Ensure log directory exists
mkdir -p logs

# Pull latest keywords/changes from GitHub
echo "[$(date)] Pulling latest changes from GitHub..." >> logs/git.log 2>&1
git pull origin main >> logs/git.log 2>&1

# Run the agent based on argument
if [ "$1" == "breaking" ]; then
    echo "[$(date)] Running Breaking News Check..."
    export BREAKING_NEWS_ONLY=true
    venv/bin/python main.py
else
    echo "[$(date)] Running Daily Blog Generation..."
    venv/bin/python main.py
fi

# Flush Rank Math sitemap cache so new posts appear immediately (WP-Cron is unreliable on Hostinger)
echo "[$(date)] Flushing Rank Math sitemap cache..."
curl -s -k "https://navigotechsolutions.com/blog/?navigo_flush=43886fb74f756cfc778a7c4f0a0145c0e4d8ee22" >> logs/sitemap_flush.log 2>&1
# Warm the sitemap so it regenerates right away
curl -s -k -o /dev/null "https://navigotechsolutions.com/blog/sitemap_index.xml" "https://navigotechsolutions.com/blog/post-sitemap.xml"

# Check if used_topics.txt or keywords.txt changed, and push back to GitHub
git add used_topics.txt keywords.txt
if ! git diff --cached --quiet; then
    echo "Topic history modified. Committing and pushing back to GitHub..."
    git commit -m "chore: sync VPS run updates [skip ci]" >> logs/git.log 2>&1
    git push origin main >> logs/git.log 2>&1
else
    echo "No topic changes. Everything in sync."
fi
