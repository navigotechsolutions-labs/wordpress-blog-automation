# NaviGo Blog Automation Agent 🤖📰

This repository contains the autonomous AI agent that automatically researches, generates, styles, and publishes high-converting, SEO-optimized blog posts for Indian small businesses and marketers.

## Features
* **Automated Topic Discovery**: Gathers trending headlines from Google News RSS feeds, reframes them specifically for Indian small business owners, and selects the best daily topic.
* **Topic Queue Fallback**: Falls back to a local queue in `keywords.txt` if headlines aren't available.
* **Breaking News Detector**: Checks every 4 hours for major AI company announcements (OpenAI, Anthropic, Google, Microsoft) and publishes hot breaking articles instantly.
* **Premium Design Engine**: Generates and injects highly styled HTML, custom CSS variables, and responsive layouts into WordPress.
* **AI Graphic Generation**: Creates custom featured graphics using Google Gemini Nano Banana, fallbacks to Pexels stock photos if API limits are hit.
* **Instant Indexing**: Automatically pings search engines (Bing/Yandex via IndexNow, Google Sitemap) for immediate indexing.
* **Activity Logging**: Logs all published posts and topics in `used_topics.txt` and a shared Google Sheet.

---

## 🚀 VPS Hosting Setup (Sole Dependency)
To make your blog automation run **solely** on your Hostinger VPS, follow these steps to migrate it away from GitHub Actions.

### Step 1: Clone Repo & Setup on VPS
SSH into your Hostinger VPS and run:
```bash
git clone https://github.com/navigotechsolutions-labs/ai-wordpress-agent.git
cd ai-wordpress-agent
```

### Step 2: Run Setup Automation Script
Run the helper setup script. This will create a virtual environment, install requirements, create log directories, and generate your `.env` file:
```bash
chmod +x setup_vps.sh run_vps_agent.sh
./setup_vps.sh
```

### Step 3: Configure Environment Variables
Open the `.env` file on the VPS and paste your API keys:
```bash
nano .env
```
Fill in the following fields:
* `DEEPSEEK_API_KEY`
* `ANTHROPIC_API_KEY`
* `WP_SITE_URL` (e.g. `https://navigotechsolutions.com/blog`)
* `WP_USERNAME`
* `WP_APP_PASSWORD` (Your WordPress Application Password)
* `GOOGLE_SHEET_URL`
* `PEXELS_API_KEY`
* `GEMINI_API_KEY`

### Step 4: Automate the Runs (Crontab)
The setup script automatically adds the following schedule to your VPS crontab:
* **Daily Blog Post**: Runs at **6:30 AM** and **12:30 PM** daily.
* **Breaking News Check**: Runs **every 4 hours** to catch major announcements.

You can view or edit this schedule at any time by running:
```bash
crontab -e
```

### Step 5 (Optional): Set up Git Push to Sync History
The script is configured to automatically pull changes from GitHub before running, and push updated files (`used_topics.txt`, `keywords.txt`) back to GitHub after publishing. 
To enable this:
1. Configure git on your VPS:
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "your-email@example.com"
   ```
2. Set up an SSH key on the VPS and add it to your GitHub account so git commands can run passwordless:
   ```bash
   ssh-keygen -t ed25519 -C "your-email@example.com"
   cat ~/.ssh/id_ed25519.pub
   ```
   (Copy this key and add it to GitHub Settings -> SSH Keys).

---

## 🛠️ File Structure
* [main.py](file:///d:/Blog%20automation/ai-wordpress-agent/main.py): The main entry point containing discovery, generation, and posting logic.
* [keywords.txt](file:///d:/Blog%20automation/ai-wordpress-agent/keywords.txt): Queue of keywords used as a fallback.
* [used_topics.txt](file:///d:/Blog%20automation/ai-wordpress-agent/used_topics.txt): Database of already published topics.
* [setup_vps.sh](file:///d:/Blog%20automation/ai-wordpress-agent/setup_vps.sh): Automates Python venv and cron setup on the VPS.
* [run_vps_agent.sh](file:///d:/Blog%20automation/ai-wordpress-agent/run_vps_agent.sh): Wrapper script that pulls remote changes, runs the agent, and pushes history back to GitHub.
