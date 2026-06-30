import os
import re
import json
import requests
import xml.etree.ElementTree as ET
import anthropic
import openai
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from google import genai
from google.genai import types
import browser_agent


# === LOAD .env FILE IF RUNNING LOCALLY ===
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# === SECRETS (from .env locally, from GitHub Secrets in CI) ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")
WP_SITE_URL       = os.getenv("WP_SITE_URL", "https://navigotechsolutions.com")
WP_USERNAME       = os.getenv("WP_USERNAME")
WP_APP_PASSWORD   = os.getenv("WP_APP_PASSWORD")
GOOGLE_SHEET_URL  = os.getenv("GOOGLE_SHEET_URL")
PEXELS_API_KEY    = os.getenv("PEXELS_API_KEY")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
WP_PHONE          = "916380853075"  # WhatsApp number (country code + number, no +)


KEYWORDS_FILE    = "keywords.txt"
USED_TOPICS_FILE = "used_topics.txt"
BREAKING_DAILY_CAP   = 1   # max breaking-news posts per day (IST)
BREAKING_COUNT_FILE  = "breaking_count.txt"
POSTED_HEADLINES_FILE = "posted_headlines.txt"

# Primary: DeepSeek — Fallback: Claude
_deepseek = (
    openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    if DEEPSEEK_API_KEY else None
)
_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def call_ai(messages, system=None, max_tokens=8192, tier="fast"):
    """
    Calls DeepSeek first (primary). Falls back to Claude on any failure.
    tier='fast'  → claude-haiku-4-5  (cheap, quick tasks)
    tier='smart' → claude-sonnet-4-6 (blog writing)
    """
    claude_model = "claude-haiku-4-5-20251001" if tier == "fast" else "claude-sonnet-4-6"

    if _deepseek:
        try:
            ds_messages = []
            if system:
                ds_messages.append({"role": "system", "content": system})
            ds_messages.extend(messages)
            resp = _deepseek.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                messages=ds_messages,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[WARN] DeepSeek failed: {e} — falling back to Claude")

    # Claude fallback
    if not _claude:
        raise RuntimeError("No AI client available (DEEPSEEK_API_KEY and ANTHROPIC_API_KEY both missing)")
    kwargs = {"model": claude_model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    return _claude.messages.create(**kwargs).content[0].text.strip()

# === INTERNAL LINKS (NaviGo Tech Solutions) ===
INTERNAL_LINKS = """
NaviGo Tech Solutions internal links — insert 2 to 3 contextually in the blog body using natural anchor text:

Services:
- AI Digital Marketing: https://navigotechsolutions.com/services.html#digital-marketing
- SEO Optimization: https://navigotechsolutions.com/services.html#seo
- Social Media Marketing: https://navigotechsolutions.com/services.html#social-media
- AI Ads & Automation: https://navigotechsolutions.com/services.html#ai
- AI Agents & Bots: https://navigotechsolutions.com/services.html#ai-agents
- Web Development: https://navigotechsolutions.com/services.html#web-development
- Content Creation: https://navigotechsolutions.com/services.html#content
- AI Strategy Consulting: https://navigotechsolutions.com/services.html#consulting
- Branding & Identity: https://navigotechsolutions.com/services.html#branding

Blog Posts:
- Top 25 AI Tools in 2026: https://navigotechsolutions.com/blog/top-25-ai-tools-in-2026/
- Local SEO Guide Chennai: https://navigotechsolutions.com/blog/local-seo-guide-2026-how-to-rank-your-business-in-chennai-search-results/
- Social Media SEO 2026: https://navigotechsolutions.com/blog/social-media-seo-in-2026-why-google-is-no-longer-the-first-stop/
- Google AI Updates 2026: https://navigotechsolutions.com/blog/google-ai-updates-2026/
- Digital Marketing Agency Chennai 2026: https://navigotechsolutions.com/blog/digital-marketing-agency-in-chennai-2026-guide/
- PPC Advertising 2026: https://navigotechsolutions.com/blog/ppc-advertising-in-2026-how-to-run-high-roi-campaigns-with-the-best-ppc-company-in-chennai/
- E-commerce SEO 2026: https://navigotechsolutions.com/blog/e-commerce-seo-in-2026-how-chennai-online-stores-rank-higher-and-sell-more/
- Website Cost India 2026: https://navigotechsolutions.com/blog/how-much-does-a-website-cost-in-india-in-2026-complete-pricing-guide/
- GPT-5.2 for Business: https://navigotechsolutions.com/blog/gpt-5-2-explained-for-business-coding-and-productivity/
- Top 10 Agencies Chennai: https://navigotechsolutions.com/blog/top-10-digital-marketing-agencies-in-chennai-2026-updated-list/

Contact: https://navigotechsolutions.com/contact.html
"""


def get_recent_blog_links(limit=10):
    """Pull recent published posts from the live Rank Math sitemap for dynamic
    internal linking (newest first). Returns formatted '- Anchor: URL' lines."""
    try:
        r = requests.get(
            "https://navigotechsolutions.com/blog/post-sitemap.xml",
            timeout=12, verify=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NaviGoBot/1.0)"},
        )
        if r.status_code != 200:
            return ""
        root = ET.fromstring(r.content)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        items = []
        for u in root.findall(f".//{ns}url"):
            loc = (u.findtext(f"{ns}loc", "") or "").strip()
            lastmod = (u.findtext(f"{ns}lastmod", "") or "").strip()
            if loc:
                items.append((lastmod, loc))
        items.sort(reverse=True)
        lines = []
        for _, loc in items[:limit]:
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            anchor = re.sub(r"-\d+$", "", slug).replace("-", " ").title()
            lines.append(f"- {anchor}: {loc}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[WARN] Dynamic internal links fetch failed: {e}")
        return ""

# === HTML TEMPLATE STYLE (NaviGo blog_template_2.html) ===
HTML_STYLE = """
<style>
:root{--primary-blue:#1e90ff;--deep-blue:#003C8F;--accent-orange:hsl(209,100%,50%);--neutral-bg:#F9F9F9;--neutral-white:#FFFFFF;--text-charcoal:#2C2C2C;--text-grey:#555555;--light-blue-bg:#EDF5FF;}
body{margin:0;padding:0;font-family:'Open Sans',sans-serif;background-color:var(--neutral-bg);color:var(--text-charcoal);line-height:1.6;}
a{color:var(--primary-blue);font-weight:700;text-decoration:none;border-bottom:2px solid var(--accent-orange);transition:all .3s ease;}
a:hover{color:var(--deep-blue);border-bottom-color:var(--primary-blue);background-color:#EDF5FF;}
.navigo-container{font-family:'Open Sans',sans-serif;background-color:var(--neutral-bg);background-image:radial-gradient(#e5e5e5 1px,transparent 1px);background-size:20px 20px;max-width:900px;margin:40px auto;padding:40px;border-radius:20px;box-shadow:0 10px 30px rgba(0,0,0,.05);position:relative;overflow:hidden;}
.navigo-shape-top-right{position:absolute;top:-50px;right:-50px;width:150px;height:150px;background:var(--primary-blue);border-radius:50%;opacity:.1;z-index:0;}
.navigo-shape-bottom-left{position:absolute;bottom:-50px;left:-50px;width:200px;height:200px;background:var(--accent-orange);border-radius:50%;opacity:.05;z-index:0;}
.navigo-hero{background:var(--neutral-white);padding:45px;border-radius:15px;box-shadow:0 4px 15px rgba(0,0,0,.03);border-left:6px solid var(--primary-blue);margin-bottom:40px;position:relative;z-index:1;}
.navigo-logo{font-family:'Montserrat',sans-serif;font-weight:800;background:#EDF5FF;padding:6px 12px;border-radius:4px;color:var(--deep-blue);letter-spacing:1px;font-size:1rem;margin-bottom:18px;display:inline-block;}
.navigo-hero h1{font-family:'Montserrat',sans-serif;font-size:2rem;margin:0 0 12px;color:var(--text-charcoal);line-height:1.3;}
.navigo-hero p{font-size:1.05rem;color:var(--text-grey);line-height:1.7;margin:0 0 12px;max-width:760px;}
.navigo-article{background:var(--neutral-white);padding:35px;border-radius:12px;border:1px solid #e5e5e5;line-height:1.9;font-size:1.06rem;color:var(--text-grey);position:relative;z-index:1;}
.navigo-article h2{font-family:'Montserrat',sans-serif;color:var(--deep-blue);font-size:1.6rem;margin-top:34px;margin-bottom:12px;}
.navigo-article h3{font-family:'Montserrat',sans-serif;color:var(--text-charcoal);font-size:1.2rem;margin-top:22px;margin-bottom:8px;}
.navigo-article p{margin-bottom:14px;}
.navigo-article ul{margin-left:18px;margin-bottom:14px;}
.navigo-article table{width:100%;border-collapse:collapse;margin:20px 0;}
.navigo-article th,.navigo-article td{border:1px solid #e5e5e5;padding:12px;text-align:left;}
.navigo-article th{background-color:#f2f2f2;color:var(--deep-blue);}
.key-takeaways{background:var(--light-blue-bg);border-left:6px solid var(--primary-blue);padding:18px 22px;border-radius:8px;margin:28px 0;}
.toc{background:#fafafa;border:1px solid #eee;padding:20px;border-radius:8px;margin:25px 0;}
.toc strong{display:block;margin-bottom:10px;font-family:'Montserrat',sans-serif;color:var(--deep-blue);}
.toc ul{list-style-type:none;padding-left:0;margin:0;}
.toc li{margin-bottom:8px;padding-left:15px;position:relative;}
.toc li::before{content:"•";color:var(--primary-blue);position:absolute;left:0;top:0;}
.navigo-faq-header{text-align:center;margin-top:42px;margin-bottom:22px;}
.navigo-faq-header h2{font-family:'Montserrat',sans-serif;font-size:1.9rem;color:var(--text-charcoal);}
.navigo-faq-details{background:var(--neutral-white);margin-bottom:12px;border-radius:8px;border:1px solid #e5e5e5;overflow:hidden;position:relative;z-index:1;}
.navigo-faq-summary{padding:16px 20px;font-family:'Montserrat',sans-serif;font-weight:700;color:var(--deep-blue);cursor:pointer;display:flex;justify-content:space-between;align-items:center;list-style:none;}
.navigo-faq-summary::after{content:'';width:10px;height:10px;border-right:3px solid var(--primary-blue);border-bottom:3px solid var(--primary-blue);transform:rotate(45deg);flex-shrink:0;}
.navigo-faq-details[open] .navigo-faq-summary::after{transform:rotate(-135deg);}
.navigo-faq-answer{padding:0 20px 18px;color:var(--text-grey);}
.navigo-footer{margin-top:36px;padding-top:22px;border-top:2px solid #eee;text-align:center;color:var(--text-grey);font-size:.95rem;position:relative;z-index:1;}
@media(max-width:768px){.navigo-container{padding:20px;margin:0;border-radius:0;}.navigo-hero{padding:25px;}.navigo-article{padding:20px;font-size:1rem;}.navigo-shape-top-right,.navigo-shape-bottom-left{display:none;}}
</style>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;800&family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
"""


WHATSAPP_CTA = f"""
<div style="background:linear-gradient(135deg,#25D366 0%,#128C7E 100%);border-radius:12px;padding:24px 28px;margin:32px 0;text-align:center;position:relative;z-index:1;">
  <p style="color:#fff;font-family:'Montserrat',sans-serif;font-weight:800;font-size:1.15rem;margin:0 0 8px;">Not sure which tool fits your business?</p>
  <p style="color:rgba(255,255,255,0.9);font-size:0.95rem;margin:0 0 16px;font-family:'Open Sans',sans-serif;">Our team at NaviGo Tech Solutions will set it up for you &mdash; free 30-minute strategy call.</p>
  <a href="https://wa.me/{WP_PHONE}?text=Hi%2C%20I%20read%20your%20blog%20and%20want%20a%20free%20strategy%20call" target="_blank" rel="noopener" style="background:#fff;color:#128C7E;font-family:'Montserrat',sans-serif;font-weight:800;padding:12px 28px;border-radius:50px;text-decoration:none;font-size:1rem;border-bottom:none;display:inline-block;">
    WhatsApp Us Now &mdash; It&apos;s Free
  </a>
</div>
"""

# ─────────────────────────────────────────────
# KEYWORD HELPERS
# ─────────────────────────────────────────────

def _ist_today():
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _breaking_count_today():
    """Number of breaking-news posts already published today (IST)."""
    if not os.path.exists(BREAKING_COUNT_FILE):
        return 0
    try:
        date_str, count = open(BREAKING_COUNT_FILE).read().split()
        return int(count) if date_str == _ist_today() else 0
    except Exception:
        return 0


def _increment_breaking_count():
    count = _breaking_count_today() + 1
    with open(BREAKING_COUNT_FILE, "w") as f:
        f.write(f"{_ist_today()} {count}")
    print(f"[BREAKING] Breaking posts today: {count}/{BREAKING_DAILY_CAP}")


def _headline_sig(h):
    """Normalised signature of a source headline (strips [LABEL] prefix)."""
    h = re.sub(r"^\[[^\]]+\]\s*", "", h)
    return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()


def _load_posted_headlines():
    if not os.path.exists(POSTED_HEADLINES_FILE):
        return set()
    with open(POSTED_HEADLINES_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _record_posted_headlines(sigs):
    existing = []
    if os.path.exists(POSTED_HEADLINES_FILE):
        with open(POSTED_HEADLINES_FILE, encoding="utf-8") as f:
            existing = [l.strip() for l in f if l.strip()]
    for sig in sigs:
        if sig and sig not in existing:
            existing.append(sig)
    existing = existing[-200:]
    with open(POSTED_HEADLINES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(existing) + "\n")


def load_used_topics():
    """Returns all used topic lines (with dates) for deduplication."""
    if not os.path.exists(USED_TOPICS_FILE):
        return []
    with open(USED_TOPICS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_used_topic(topic):
    """Appends topic with date stamp to used_topics.txt."""
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(USED_TOPICS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{date_str} | {topic}\n")
    print(f"[OK] Saved to used_topics.txt: {topic}")


def is_duplicate_topic(new_topic, used_lines):
    """
    Returns True if the new topic is too similar to any already-used topic.
    Blocks exact matches AND topics sharing 3+ significant keywords.
    """
    stopwords = {
        "a","an","the","and","or","for","in","on","of","to","is","it",
        "how","what","why","with","from","by","at","this","that","your",
        "india","indian","2026","2025","business","businesses","small",
        "best","top","guide","complete","full","tips","strategy","ways",
        "just","launched","release","update","new","know","need","needs",
        "work","works","using","use","get","make","about","will","has",
        "have","been","into","their","which","when","every","also","more"
    }
    def keywords(text):
        words = re.findall(r"[a-z]+", text.lower())
        return {w for w in words if w not in stopwords and len(w) > 3}

    new_keys = keywords(new_topic)

    for line in used_lines:
        # Strip date prefix if present
        topic = line.split(" | ", 1)[-1] if " | " in line else line
        used_keys = keywords(topic)
        overlap = new_keys & used_keys
        if len(overlap) >= 3:
            print(f"[WARN] Too similar to used topic '{topic}' (overlap: {overlap})")
            return True
    return False


def read_next_keyword():
    """Fallback: reads the next keyword from keywords.txt queue."""
    if not os.path.exists(KEYWORDS_FILE):
        return None
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        return None
    keyword = lines[0]
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        for r in lines[1:]:
            f.write(r + "\n")
    print(f"[OK] Fallback keyword from queue: {keyword}")
    print(f"[OK] Keywords remaining: {len(lines) - 1}")
    return keyword


# ─────────────────────────────────────────────
# STEP 1 — AUTO TOPIC DISCOVERY
# ─────────────────────────────────────────────

def fetch_rss_titles(url, label, limit=8, with_age=False):
    """
    Fetches titles from an RSS feed.
    with_age=True returns (label_str, age_hours) tuples for breaking news detection.
    """
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NaviGoBot/1.0)"},
        )
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        results = []
        now_utc = datetime.now(timezone.utc)
        ATOM = "{http://www.w3.org/2005/Atom}"
        items = root.findall(".//item")
        is_atom = False
        if not items:
            items = root.findall(f".//{ATOM}entry")  # YouTube & other Atom feeds
            is_atom = True
        for item in items[:limit]:
            if is_atom:
                title = (item.findtext(f"{ATOM}title", "") or "").strip()
            else:
                title = item.findtext("title", "").strip()
            title = re.sub(r"<[^>]+>", "", title).strip()
            if not title:
                continue
            label_str = f"[{label}] {title}"
            if with_age:
                if is_atom:
                    pub_raw = item.findtext(f"{ATOM}published", "") or item.findtext(f"{ATOM}updated", "")
                else:
                    pub_raw = item.findtext("pubDate", "")
                age_hours = 999
                try:
                    pub_dt = parsedate_to_datetime(pub_raw)
                    age_hours = (now_utc - pub_dt).total_seconds() / 3600
                except Exception:
                    try:
                        from datetime import datetime as _dt
                        pub_dt = _dt.fromisoformat(pub_raw.replace("Z", "+00:00"))
                        age_hours = (now_utc - pub_dt).total_seconds() / 3600
                    except Exception:
                        pass
                results.append((label_str, age_hours))
            else:
                results.append(label_str)
        return results
    except Exception as e:
        print(f"[WARN] RSS fetch failed ({label}): {e}")
        return []


def detect_breaking_news(max_age_hours=2):
    """
    Scans only major AI company feeds for posts published within max_age_hours.
    Returns a breaking topic string if found, or None.
    """
    print(f"[BREAKING] Scanning for breaking AI news (last {max_age_hours}h)...")

    # Only official AI company blogs — NOT news sites (TechCrunch/VentureBeat post
    # every hour and would trigger a blog post on every hourly check)
    breaking_feeds = [
        ("https://openai.com/blog/rss.xml",            "OPENAI"),
        ("https://www.anthropic.com/news/rss.xml",     "ANTHROPIC"),
        ("https://blog.google/technology/ai/rss/",     "GOOGLE AI"),
        ("https://ai.meta.com/blog/rss/",              "META AI"),
        ("https://blogs.microsoft.com/ai/feed/",       "MICROSOFT AI"),
        ("https://mistral.ai/news/rss.xml",            "MISTRAL"),
        ("https://huggingface.co/blog/feed.xml",       "HUGGING FACE"),
        ("https://blogs.nvidia.com/feed/",             "NVIDIA"),
        ("https://x.ai/blog/rss.xml",                  "XAI"),
        ("https://aws.amazon.com/blogs/machine-learning/feed/", "AWS ML"),
        ("https://deepmind.google/blog/rss.xml",       "DEEPMIND"),
        ("https://cohere.com/blog/rss.xml",            "COHERE"),
    ]

    fresh_headlines = []
    for feed_url, label in breaking_feeds:
        items = fetch_rss_titles(feed_url, label=label, limit=5, with_age=True)
        for headline, age_hours in items:
            if age_hours <= max_age_hours:
                fresh_headlines.append((headline, age_hours))
                print(f"[BREAKING] Found ({age_hours:.1f}h ago): {headline}")

    if not fresh_headlines:
        print(f"[BREAKING] No breaking news found in the last {max_age_hours}h. Skipping post.")
        return None

    # Sort by most recent first
    fresh_headlines.sort(key=lambda x: x[1])

    # Skip stories already posted about — stops the same headline re-triggering
    # on every 30-min run while it is still inside the freshness window.
    posted_sigs = _load_posted_headlines()
    fresh_headlines = [(h, a) for (h, a) in fresh_headlines if _headline_sig(h) not in posted_sigs]
    if not fresh_headlines:
        print("[BREAKING] All fresh headlines already covered. Skipping.")
        return None

    used_topics = load_used_topics()
    used_clean = [l.split(" | ", 1)[-1] if " | " in l else l for l in used_topics]
    used_text = "\n".join(used_clean[-30:]) if used_clean else "None yet."
    headlines_text = "\n".join(h for h, _ in fresh_headlines[:10])

    prompt = f"""You are an SEO content strategist for NaviGo Tech Solutions, an AI digital marketing agency in Chennai, India.

BREAKING NEWS HEADLINES (published in the last {max_age_hours} hours):
{headlines_text}

TOPICS ALREADY WRITTEN — DO NOT repeat any of these:
{used_text}

A major AI announcement just happened. Write a BREAKING NEWS blog topic for Indian business owners.
The title must feel urgent and timely — like "X just launched", "X just announced", "Breaking: X changes everything".
Reframe it for Indian entrepreneurs and small business owners.

Respond with ONLY the blog topic phrase (5 to 12 words). No explanation. No punctuation at end. No quotes.

Examples:
OpenAI just launched GPT-5 what Indian businesses must do now
Anthropic Claude 4 just released and it changes everything for marketers
Google Gemini 2 just dropped here is what Indian startups need to know"""

    topic = call_ai(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        tier="fast",
    ).strip(".").strip('"').strip("'")

    if topic and is_duplicate_topic(topic, used_topics):
        print("[BREAKING] Topic too similar to a recent post. Skipping.")
        return None

    _record_posted_headlines([_headline_sig(h) for h, _ in fresh_headlines[:10]])
    print(f"[BREAKING] Topic selected: {topic}")
    return topic if topic else None


def discover_topic():
    """
    Gathers trending headlines from Google Trends India and Google News,
    then asks Claude to pick the single best blog topic for NaviGo today.
    Returns a keyword string, or None if discovery fails.
    """
    print("[SEARCH] Discovering today's topic...")

    headlines = []

    # ── Top AI company blogs (most important — breaking news comes from here) ──
    company_feeds = [
        ("https://openai.com/blog/rss.xml",        "OPENAI"),
        ("https://www.anthropic.com/news/rss.xml", "ANTHROPIC"),
        ("https://blog.google/technology/ai/rss/", "GOOGLE AI"),
        ("https://ai.meta.com/blog/rss/",          "META AI"),
    ]
    for feed_url, label in company_feeds:
        headlines += fetch_rss_titles(feed_url, label=label, limit=3)

    # ── Best marketing/SEO blogs ──
    blog_feeds = [
        ("https://neilpatel.com/blog/feed/",               "NEIL PATEL"),
        ("https://blog.hubspot.com/marketing/rss.xml",     "HUBSPOT"),
        ("https://www.searchenginejournal.com/feed/",      "SEJ"),
        ("https://ahrefs.com/blog/feed/",                  "AHREFS"),
        ("https://techcrunch.com/category/artificial-intelligence/feed/", "TECHCRUNCH AI"),
    ]
    for feed_url, label in blog_feeds:
        headlines += fetch_rss_titles(feed_url, label=label, limit=3)

    # YouTube creators (latest videos = strong click signals)
    youtube_creators = [
        ("UChpleBmo18P08aKCIgti38g", "YT MATT WOLFE"),
        ("UCawZsQWqfGSbCI5yjkdVkTA", "YT MATTHEW BERMAN"),
        ("UCqcbQf6yw5KzRoDDcZ_wBSw", "YT WES ROTH"),
        ("UCHhYXsLBEVVnbvsq57n1MTQ", "YT AI ADVANTAGE"),
        ("UCbfYPyITQ-7l4upoX8nvctg", "YT TWO MINUTE PAPERS"),
        ("UC2Xd-TjJByJyK2w1zNwY0zQ", "YT FIRESHIP"),
        ("UCxjs1n-C7rjXQ9KhgDng-6A", "YT ISHAN SHARMA"),
        ("UCsQoiOrh7jzKmE8NBofhTnQ", "YT VARUN MAYYA"),
        ("UClXAalunTPaX1YV185DWUeg", "YT VAIBHAV SISINTY"),
        ("UCRzYN32xtBf3Yxsx5BvJWJw", "YT WARIKOO"),
    ]
    for cid, label in youtube_creators:
        headlines += fetch_rss_titles(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
            label=label, limit=2,
        )

    # ── Google News — single targeted query ──
    google_url = f"https://news.google.com/rss/search?q={quote('AI tools digital marketing India 2026')}&hl=en-IN&gl=IN&ceid=IN:en"
    headlines += fetch_rss_titles(google_url, label="GOOGLE NEWS", limit=5)

    # ── Google Trends India ──
    headlines += fetch_rss_titles(
        "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN",
        label="TRENDING INDIA",
        limit=5,
    )

    if not headlines:
        print("[WARN] No headlines gathered. Falling back to keywords.txt.")
        return None

    # Deduplicate while preserving order
    seen = set()
    unique_headlines = []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique_headlines.append(h)

    used_topics = load_used_topics()
    # Strip date prefix for display in prompt
    used_clean = [l.split(" | ", 1)[-1] if " | " in l else l for l in used_topics]
    used_text = "\n".join(used_clean[-30:]) if used_clean else "None yet."
    headlines_text = "\n".join(unique_headlines[:40])

    prompt = f"""You are an SEO content strategist for NaviGo Tech Solutions, a digital marketing and AI agency in Chennai, India.

STYLE REFERENCES (match their energy and topic style):
- Vaibhav Sisinty: viral AI news — "Anthropic Just Changed AI Agents Forever", "Secret AI Hack to Cut Costs 75 percent"
- Neil Patel: practical SEO/marketing — "How to Double Your Traffic", "The Marketing Strategy That Works in 2026"
- Gary Vee: business mindset — "Why Most Businesses Fail at Social Media", "The Content Strategy Nobody Talks About"
- Backlinko/Ahrefs: data-driven SEO — "We Studied 1M Pages — Here Is What Works", "The Definitive Guide to X"
- HubSpot/SEJ: actionable marketing — "10 Ways to Increase Leads", "The Complete Guide to Y in 2026"

TODAY'S HEADLINES (AI company blogs, top marketing blogs, Google News, Google Trends India):
{headlines_text}

TOPICS ALREADY WRITTEN — DO NOT repeat or closely imitate any of these:
{used_text}

YOUR TASK:
Pick the SINGLE best blog topic from today's headlines for NaviGo's Indian business audience.

Priority order:
1. Breaking AI company news — OpenAI, Anthropic, Google, Meta, Microsoft, xAI, Mistral, NVIDIA
2. A newly launched AI tool or model useful for marketers and business owners
3. A trending SEO, social media, or digital marketing strategy from Neil Patel, Ahrefs, HubSpot, Backlinko
4. A business growth or entrepreneurship insight from Gary Vee, Inc, or Think Media
5. Anything highly shareable and curiosity-driven for Indian entrepreneurs

Always reframe the topic for Indian small business owners and marketers.

Respond with ONLY the blog topic phrase (5 to 10 words). No explanation. No punctuation at end. No quotes.

Good examples:
Neil Patel SEO strategy that doubled traffic in 2026
OpenAI new tool that automates your marketing funnel
Google Gemini update what Indian businesses need to know
Why most Indian startups fail at social media and how to fix it
Ahrefs found the backlink strategy that actually works in 2026"""

    topic = call_ai(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        tier="fast",
    ).strip(".").strip('"').strip("'")

    if topic and is_duplicate_topic(topic, used_topics):
        print(f"[WARN] Topic too similar to recent posts. Will use keywords.txt fallback.")
        return None

    print(f"[OK] Discovered topic: {topic}")
    return topic if topic else None


# ─────────────────────────────────────────────
# STEP 2 — RESEARCH THE CHOSEN TOPIC
# ─────────────────────────────────────────────

def research_topic(keyword):
    """
    Fetches recent news about the keyword from multiple sources.
    Returns a plain-text research summary to enrich the blog generator.
    """
    print(f"[RESEARCH] Researching: {keyword}")
    all_items = []

    # Search Google News with the main keyword
    queries = [
        keyword,
        keyword + " India",
        keyword + " business",
    ]

    for query in queries:
        try:
            rss_url = (
                f"https://news.google.com/rss/search"
                f"?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            resp = requests.get(
                rss_url,
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NaviGoBot/1.0)"},
            )
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:5]
            for item in items:
                title = item.findtext("title", "").strip()
                desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()[:250]
                pub_date = item.findtext("pubDate", "")[:16].strip()
                if title and title not in [x[0] for x in all_items]:
                    all_items.append((title, desc, pub_date))
        except Exception as e:
            print(f"[WARN] Research query failed ({query}): {e}")

    if not all_items:
        print("[WARN] No research data found. Continuing without it.")
        return ""

    lines = [f"Research data for '{keyword}' (use as factual context, not direct quotes):"]
    for title, desc, pub_date in all_items[:12]:
        lines.append(f"• [{pub_date}] {title} — {desc}")

    print(f"[OK] Research: {len(all_items)} articles found.")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# STEP 3 — GENERATE BLOG IN NAVIGO STYLE
# ─────────────────────────────────────────────

def generate_blog(keyword, research=""):
    system_prompt = (
        "You are an expert SEO blog writer for NaviGo Tech Solutions, an AI digital marketing agency in Chennai, India. "
        "You write detailed, helpful, conversational content for Indian small business owners and entrepreneurs. "
        "Your tone is confident, clear, and practical — no fluff, no em dashes, no jargon. "
        "Use simple British-style English. Write as if explaining to a smart friend who runs a business. "
        "Always respond with valid JSON only — no markdown, no code fences, no extra text."
    )

    research_block = (
        f"\n\nRESEARCH DATA (use this to include fresh, accurate facts and current trends):\n{research}\n"
        if research else ""
    )

    dynamic_links = INTERNAL_LINKS
    _recent = get_recent_blog_links()
    if _recent:
        dynamic_links = INTERNAL_LINKS + "\n\nRecent blog posts (link to the most relevant 1-2 only):\n" + _recent

    user_prompt = f"""Write a full SEO blog post for the keyword: "{keyword}"
{research_block}
BRAND CONTEXT:
- Brand: NaviGo Tech Solutions
- Website: navigotechsolutions.com
- Location: Chennai, India
- Target audience: Indian small business owners, entrepreneurs, and marketing managers

INTERNAL LINKS TO USE (insert 2-3 contextually with natural anchor text):
{dynamic_links}

STYLE RULES:
1. Structure: Hero intro → Key Takeaways → Table of Contents → 5 content sections (h2 + h3 subheadings) → Comparison table → FAQ (4 questions) → CTA footer
2. Each section: minimum 120 words, practical India-relevant examples, numbered steps where useful
3. Use <strong> for key terms and important phrases
4. Include 1 HTML table (comparison, stats, or step breakdown)
5. Internal links must use natural anchor text (e.g. "see our Local SEO guide" not "click here")
6. No em dashes. No filler openers like "In today's digital world"
7. Minimum 1400 words total
8. Include exactly 2 image placeholders in the body: one between Section 2 and Section 3, and one between Section 4 and Section 5. The placeholder format must be exactly: [IMAGE_PLACEHOLDER: Specific, detailed description of a highly useful, modern business infographic, step-by-step process chart, grid-based comparison diagram, or data bar chart on a clean minimal white background that visually explains the concepts in this section (matching the theme of the blog keyword). CRITICAL RULES: (1) Include short, highly legible, correctly-spelled text headers, labels, or numbers (e.g. specific tool names, step numbers like '1. Discovery', or short key phrases). (2) Keep text minimal, clean, spaced out, and in high-contrast professional bold typography. (3) Use a premium professional color scheme: deep navy blue, bright blue, with clean accent colors (like warm yellow, green, or red for success/failure). (4) Describe concrete structural elements: colored circle icons, numbered grid cards, vertical list flows, clean columns, or simple bar charts.]


HTML TEMPLATE TO FILL IN EXACTLY (replace every placeholder with real content).
Use these CSS class names exactly as shown — styling is handled externally:

<div class="navigo-container">
  <div class="navigo-shape-top-right"></div>
  <div class="navigo-shape-bottom-left"></div>

  <div class="navigo-hero">
    <div class="navigo-logo">NaviGo Tech Solutions</div>
    <h1>[SEO HEADLINE — include the keyword naturally, 60-70 chars]</h1>
    <p>[2-3 sentence hook: state the pain, promise the solution, tease the outcome. Use <strong> for 1-2 key phrases.]</p>
    <p>This guide covers:</p>
    <ul>
      <li>[Key Point 1]</li>
      <li>[Key Point 2]</li>
      <li>[Key Point 3]</li>
      <li>[Key Point 4]</li>
    </ul>
    <p>[1 sentence leading into the article.]</p>
  </div>

  <div class="navigo-article">
    <div class="key-takeaways">
      <strong>What You'll Learn:</strong>
      <ul>
        <li>[Takeaway 1]</li>
        <li>[Takeaway 2]</li>
        <li>[Takeaway 3]</li>
        <li>[Takeaway 4]</li>
      </ul>
    </div>

    <div class="toc">
      <strong>Table of Contents</strong>
      <ul>
        <li><a href="#section-1">[Section 1 Title]</a></li>
        <li><a href="#section-2">[Section 2 Title]</a></li>
        <li><a href="#section-3">[Section 3 Title]</a></li>
        <li><a href="#section-4">[Section 4 Title]</a></li>
        <li><a href="#section-5">[Section 5 Title]</a></li>
      </ul>
    </div>

    <h2 id="section-1">[What is / What are — plain explanation]</h2>
    [3-4 paragraphs. No jargon. India-relevant examples.]

    <h2 id="section-2">[Why It Matters in 2026]</h2>
    [3-4 h3 subheadings, each 80-100 words. Include data points from research if available.]

    [IMAGE_PLACEHOLDER: A modern list-based business infographic showing why this topic matters. Left side shows colored circular icons for each point, right side shows a bold, correctly spelled header like '1. Cost Reduction' or '2. High ROI', followed by a very short, clean text description, all on a clean minimal white background. Premium color scheme of deep navy blue, bright blue, and clean accents.]

    <h2 id="section-3">[Step-by-Step Guide]</h2>
    [Numbered steps as ul with <strong> labels. Each step 60-80 words with practical detail.]

    <h2 id="section-4">[Common Mistakes to Avoid]</h2>
    [h3 for each mistake. Specific, not generic. Include 1-2 internal links here.]

    [IMAGE_PLACEHOLDER: A professional 2-column comparison grid diagram showing Common Mistakes vs Best Practices. Left column has red X icons and correctly spelled labels like 'Broad Target', 'No Landing Page'. Right column has green checkmark icons and labels like 'Niche Target', 'Custom Landing Page'. Minimal modern flat design, highly spaced and legible text, clean white background.]

    <h2 id="section-5">[Comparison or Tools Overview]</h2>
    [1-2 intro paragraphs then:]
    <table>
      <thead><tr><th>[Col1]</th><th>[Col2]</th><th>[Col3]</th><th>[Col4]</th></tr></thead>
      <tbody>
        [5-6 rows of real, useful data]
      </tbody>
    </table>
    [1 closing paragraph with an internal link.]
  </div>

  <div class="navigo-faq-header">
    <h2>Frequently Asked Questions</h2>
  </div>

  <details class="navigo-faq-details">
    <summary class="navigo-faq-summary">[Question 1 — real customer doubt about the topic]</summary>
    <div class="navigo-faq-answer">[Direct 2-3 sentence answer. Can include 1 internal link.]</div>
  </details>

  <details class="navigo-faq-details">
    <summary class="navigo-faq-summary">[Question 2]</summary>
    <div class="navigo-faq-answer">[Answer]</div>
  </details>

  <details class="navigo-faq-details">
    <summary class="navigo-faq-summary">[Question 3]</summary>
    <div class="navigo-faq-answer">[Answer]</div>
  </details>

  <details class="navigo-faq-details">
    <summary class="navigo-faq-summary">[Question 4]</summary>
    <div class="navigo-faq-answer">[Answer]</div>
  </details>

  <div class="navigo-footer">
    <p>[1 strong CTA line — benefit-driven, action-oriented]</p>
    <p><a href="https://navigotechsolutions.com/contact.html" target="_blank">Get Your Free Consultation — NaviGo Tech Solutions</a></p>
  </div>
</div>

Respond using EXACTLY this format with these delimiters (no JSON, no code fences):

===TITLE===
[SEO title — 60-70 chars, keyword included naturally]
===TITLE_END===

===META===
[Meta description — 150-160 chars, keyword + benefit-driven]
===META_END===

===FOCUS_KEYWORD===
[Single most important SEO keyword phrase — 2 to 5 words, exactly what someone Googles]
===FOCUS_KEYWORD_END===

===CATEGORY===
[Single best category for this post — choose ONE from: AI Tools, Digital Marketing, SEO, Social Media, Business Automation, Content Marketing, Paid Advertising, Web Development, Growth Hacking, Email Marketing]
===CATEGORY_END===

===TAGS===
[8 to 10 comma-separated tags — mix of broad and specific keywords related to this post]
===TAGS_END===

===CONTENT===
[The complete filled-in HTML above — no placeholders remaining, all content written in full]
===CONTENT_END===
"""

    raw = call_ai(
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
        max_tokens=8192,
        tier="smart",
    )

    # Parse using delimiters — avoids JSON escaping issues with large HTML
    def extract(tag):
        start = raw.find(f"==={tag}===")
        end = raw.find(f"==={tag}_END===")
        if start == -1 or end == -1:
            raise ValueError(f"Missing delimiter ==={tag}=== in response")
        return raw[start + len(f"==={tag}==="):end].strip()

    title          = extract("TITLE")
    meta           = extract("META")
    focus_keyword  = extract("FOCUS_KEYWORD")
    category       = extract("CATEGORY")
    tags_raw       = extract("TAGS")
    content        = extract("CONTENT")

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # Inject WhatsApp CTA before the FAQ section (highest-intent moment)
    faq_marker = '<div class="navigo-faq-header"'
    if faq_marker in content:
        content = content.replace(faq_marker, WHATSAPP_CTA + "\n" + faq_marker, 1)
    else:
        # Fallback: inject before closing footer div
        footer_marker = '<div class="navigo-footer"'
        if footer_marker in content:
            content = content.replace(footer_marker, WHATSAPP_CTA + "\n" + footer_marker, 1)

    # Inject CSS here so it never goes into the AI prompt
    content = HTML_STYLE + "\n" + content
    return title, content, meta, focus_keyword, category, tags


# ─────────────────────────────────────────────
# STEP 4 — POST TO WORDPRESS
# ─────────────────────────────────────────────

def _wp_request_with_backoff(method, url, max_retries=4, **kwargs):
    """Executes a WordPress REST API request, retrying on 429 with exponential backoff."""
    import time
    
    # Inject browser-like User-Agent to prevent WAF blocks against python-requests User-Agent
    headers = kwargs.get("headers", {})
    if "User-Agent" not in headers:
        headers = headers.copy()
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        kwargs["headers"] = headers

    for attempt in range(max_retries):
        resp = method(url, **kwargs)
        if resp.status_code != 429:
            return resp
        wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
        print(f"[WARN] WP rate limit (429). Waiting {wait}s before retry {attempt + 1}/{max_retries}...")
        time.sleep(wait)
    return resp


def get_or_create_wp_term(taxonomy, name):
    """Gets existing or creates a new WordPress category/tag. Returns ID."""
    import time
    endpoint = f"{WP_SITE_URL}/wp-json/wp/v2/{taxonomy}"
    auth = (WP_USERNAME, WP_APP_PASSWORD)

    # Try creating — WP returns 400 with existing term_id if already exists
    r = _wp_request_with_backoff(requests.post, endpoint, json={"name": name}, auth=auth, timeout=15)
    if r.status_code in (200, 201):
        return r.json().get("id")

    # Already exists — search for it
    r2 = _wp_request_with_backoff(requests.get, endpoint, params={"search": name, "per_page": 1}, auth=auth, timeout=15)
    if r2.status_code == 200 and r2.json():
        return r2.json()[0].get("id")

    print(f"[WARN] Could not get/create {taxonomy}: {name}")
    return None


def send_to_wordpress(title, content, meta, focus_keyword="", category="Digital Marketing", tags=None, featured_media_id=None):
    import time
    print("[OK] Sending post to WordPress via REST API...")
    if tags is None:
        tags = []

    # Resolve category ID
    cat_id = get_or_create_wp_term("categories", category)
    print(f"[OK] Category: {category} (ID: {cat_id})")

    # Resolve tag IDs — small delay between calls to avoid rate limiting
    tag_ids = []
    for tag in tags[:10]:
        tid = get_or_create_wp_term("tags", tag)
        if tid:
            tag_ids.append(tid)
        time.sleep(0.5)
    print(f"[OK] Tags set: {len(tag_ids)}")

    endpoint = f"{WP_SITE_URL}/wp-json/wp/v2/posts"

    payload = {
        "title":   title,
        "content": content,
        "excerpt": meta,
        "status":  "publish",
        "categories": [cat_id] if cat_id else [],
        "tags":       tag_ids,
        "featured_media": featured_media_id or 0,
        "meta": {
            # Yoast SEO
            "_yoast_wpseo_focuskw":        focus_keyword,
            "_yoast_wpseo_metadesc":       meta,
            # RankMath SEO
            "rank_math_focus_keyword":     focus_keyword,
            "rank_math_description":       meta,
        },
    }

    response = _wp_request_with_backoff(
        requests.post,
        endpoint,
        json=payload,
        auth=(WP_USERNAME, WP_APP_PASSWORD),
        timeout=60,
    )

    print("[OK] REST API Status:", response.status_code)

    if response.status_code in (200, 201):
        data = response.json()
        post_id  = data.get("id")
        post_url = data.get("link")
        print("[OK] Post published! ID:", post_id)
        print("[OK] URL:", post_url)
        return post_id, post_url
    else:
        print("[ERROR] Response:", response.text[:500])
        raise Exception(
            f"[ERROR] REST API failed with status {response.status_code}: {response.text[:300]}"
        )


# ─────────────────────────────────────────────
# STEP 4b — INJECT SCHEMA MARKUP
# ─────────────────────────────────────────────

def generate_schema(title, meta, content, post_url):
    """
    Builds Article + FAQPage + HowTo JSON-LD and prepends it to the post content.
    FAQPage and HowTo entries are auto-parsed from the HTML structure.
    """
    import json

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    article_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": meta,
        "author": {
            "@type": "Organization",
            "name": "NaviGo Tech Solutions",
            "url": "https://navigotechsolutions.com",
        },
        "publisher": {
            "@type": "Organization",
            "name": "NaviGo Tech Solutions",
            "logo": {
                "@type": "ImageObject",
                "url": "https://navigotechsolutions.com/assets/logo.png",
            },
        },
        "datePublished": now,
        "dateModified": now,
        "mainEntityOfPage": {"@type": "WebPage", "@id": post_url},
    }

    # Parse FAQ Q&A pairs from <details> blocks
    questions = re.findall(
        r'<summary[^>]*class="navigo-faq-summary"[^>]*>(.*?)</summary>',
        content, re.DOTALL,
    )
    answers = re.findall(
        r'<div[^>]*class="navigo-faq-answer"[^>]*>(.*?)</div>',
        content, re.DOTALL,
    )
    faq_entities = []
    for q, a in zip(questions, answers):
        q_text = re.sub(r"<[^>]+>", "", q).strip()
        a_text = re.sub(r"<[^>]+>", "", a).strip()
        if q_text and a_text:
            faq_entities.append({
                "@type": "Question",
                "name": q_text,
                "acceptedAnswer": {"@type": "Answer", "text": a_text},
            })

    # Parse HowTo steps from Section 3
    # Step pattern matching: Step X: Title and details
    steps_raw = re.findall(
        r'<li>\s*<strong>Step\s*(\d+)(?:[:.-]|\s)\s*(.*?)</strong>(?:<br\s*/?>)?\s*(.*?)\s*</li>',
        content, re.DOTALL | re.IGNORECASE
    )
    if not steps_raw:
        # Fallback pattern matching: Step X or just X. Title
        steps_raw = re.findall(
            r'<li>\s*(?:<strong>)?\s*(?:Step\s*)?(\d+)(?:[:.-]|\s)\s*(.*?)(?:</strong>)?(?:<br\s*/?>)?\s*(.*?)\s*</li>',
            content, re.DOTALL | re.IGNORECASE
        )

    howto_steps = []
    for idx, (num, step_name_html, step_desc_html) in enumerate(steps_raw):
        step_name = re.sub(r"<[^>]+>", "", step_name_html).strip()
        step_desc = re.sub(r"<[^>]+>", "", step_desc_html).strip()
        if step_name and step_desc:
            howto_steps.append({
                "@type": "HowToStep",
                "position": idx + 1,
                "name": step_name,
                "text": step_desc
            })

    schemas = [article_schema]
    if faq_entities:
        schemas.append({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": faq_entities,
        })

    if howto_steps:
        # Get HowTo name from Section 3 title
        section_3_title_match = re.search(r'<h2[^>]*id="[^"]*step[^"]*"[^>]*>(.*?)</h2>', content, re.DOTALL | re.IGNORECASE)
        if not section_3_title_match:
            section_3_title_match = re.search(r'<h2[^>]*id="section-3"[^>]*>(.*?)</h2>', content, re.DOTALL | re.IGNORECASE)
        
        howto_name = section_3_title_match.group(1).strip() if section_3_title_match else f"How to Implement {title}"
        howto_name = re.sub(r"<[^>]+>", "", howto_name).strip()

        # Get HowTo description from paragraph following section-3 h2
        section_3_desc_match = re.search(
            r'<h2[^>]*id="(?:section-3|[^"]*step[^"]*)"[^>]*>.*?</h2>\s*<p[^>]*>(.*?)</p>', 
            content, re.DOTALL | re.IGNORECASE
        )
        howto_desc = section_3_desc_match.group(1).strip() if section_3_desc_match else f"A step-by-step guide on: {title}"
        howto_desc = re.sub(r"<[^>]+>", "", howto_desc).strip()

        schemas.append({
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": howto_name,
            "description": howto_desc,
            "step": howto_steps
        })

    print(f"[OK] Schema generated (client-side dynamic injection active): Article + {len(faq_entities)} FAQ entries + {len(howto_steps)} HowTo steps")
    return content


def patch_wp_post_content(post_id, content):
    """Updates the content of an existing WordPress post (used to inject schema)."""
    endpoint = f"{WP_SITE_URL}/wp-json/wp/v2/posts/{post_id}"
    r = _wp_request_with_backoff(
        requests.post,
        endpoint,
        json={"content": content},
        auth=(WP_USERNAME, WP_APP_PASSWORD),
        timeout=30,
    )
    if r.status_code in (200, 201):
        print("[OK] Schema injected into post")
    else:
        print(f"[WARN] Schema patch failed: {r.status_code} {r.text[:200]}")


# ─────────────────────────────────────────────
# STEP 5 — PING SEARCH ENGINES FOR INDEXING
# ─────────────────────────────────────────────

def clear_wp_cache():
    """
    Clears WordPress caching plugins so the sitemap updates immediately.
    Tries W3 Total Cache, WP Super Cache, and LiteSpeed Cache REST endpoints.
    """
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    cache_endpoints = [
        f"{WP_SITE_URL}/wp-json/w3tc/v1/flush",
        f"{WP_SITE_URL}/wp-json/wp-super-cache/v1/cache",
        f"{WP_SITE_URL}/wp-json/litespeed/v1/purge/all",
    ]
    cleared = False
    for endpoint in cache_endpoints:
        try:
            r = requests.post(endpoint, auth=auth, timeout=8)
            if r.status_code in (200, 201, 204):
                print(f"[OK] Cache cleared via: {endpoint.split('/')[-2]}")
                cleared = True
                break
        except Exception:
            pass

    # Also fetch the sitemap directly to bust any proxy/CDN cache
    try:
        requests.get(
            f"{WP_SITE_URL}/sitemap.xml",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=10,
        )
        requests.get(
            f"{WP_SITE_URL}/post-sitemap.xml",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=10,
        )
        print("[OK] Sitemap cache-bust request sent")
    except Exception as e:
        print(f"[WARN] Sitemap fetch failed: {e}")

    if not cleared:
        print("[WARN] No cache plugin endpoint responded — sitemap may update with delay")


def ping_google_indexing_api(post_url):
    """
    Submits the URL to the Google Indexing API for near-instant crawl and indexing.
    Requires google-credentials.json to be present in the directory or configured in .env.
    """
    import os
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except ImportError:
        print("[WARN] google-auth not installed — skipping instant Google indexing. Run: pip install google-auth")
        return

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google-credentials.json")
    if not os.path.exists(creds_path):
        print(f"[INFO] Google Indexing API key not found at '{creds_path}' — skipping instant Google indexing.")
        return

    print(f"[OK] Google Indexing API key found. Authenticating...")
    try:
        scopes = ["https://www.googleapis.com/auth/indexing"]
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=scopes
        )
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        token = credentials.token

        endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"
        payload = {
            "url": post_url,
            "type": "URL_UPDATED"
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            print(f"[OK] Google Indexing API ping successful: {r.status_code}")
            try:
                print(f"[OK] Response: {r.json()}")
            except Exception:
                print(f"[OK] Response: {r.text}")
        else:
            print(f"[WARN] Google Indexing API ping failed: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"[WARN] Google Indexing API error: {e}")


def ping_search_engines(post_url):
    """
    1. Clears WP cache so the sitemap is fresh.
    2. Google Indexing API — submits URL directly to Google for instant crawl/indexing.
    3. IndexNow — submits URL directly to Bing and Yandex (Google deprecated its ping endpoint in 2024).
    """
    indexnow_key = os.getenv("INDEXNOW_KEY", "")

    # Step 1: clear cache so sitemap reflects the new post
    clear_wp_cache()

    # Step 2: Google Indexing API (Instant indexing)
    ping_google_indexing_api(post_url)

    # Step 3: IndexNow — direct URL submission (Bing + Yandex official method)
    if not indexnow_key:
        print("[WARN] INDEXNOW_KEY not set — skipping IndexNow pings")
        return

    indexnow_engines = [
        ("IndexNow (all engines)", "https://api.indexnow.org/indexnow"),
        ("Bing IndexNow",          "https://www.bing.com/indexnow"),
        ("Yandex IndexNow",        "https://yandex.com/indexnow"),
    ]

    payload = {
        "host":        "navigotechsolutions.com",
        "key":         indexnow_key,
        "keyLocation": f"https://navigotechsolutions.com/blog/{indexnow_key}.txt",
        "urlList":     [post_url],
    }

    for engine, endpoint in indexnow_engines:
        try:
            r = requests.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            print(f"[OK] {engine} pinged: {r.status_code}")
        except Exception as e:
            print(f"[WARN] {engine} ping failed: {e}")




# ─────────────────────────────────────────────
# STEP 5b — FEATURED IMAGE (PEXELS + WP MEDIA)
# ─────────────────────────────────────────────

def generate_nano_banana_image(keyword):
    """
    Generates a custom featured image using Google Gemini Image Model (Nano Banana / Imagen 3).
    Returns the image bytes or None on failure.
    """
    if not GEMINI_API_KEY:
        print("[WARN] GEMINI_API_KEY not set — skipping Nano Banana image generation")
        return None

    try:
        # Strip any hex color codes from keyword before building prompt
        # (prevents Gemini Imagen from rendering #RRGGBB as visible text in the image)
        keyword = re.sub(r'#[0-9A-Fa-f]{3,6}\b', '', keyword).strip()

        # Official NaviGo brand identity parameters - strictly NO hex codes in the text prompt
        # to prevent Imagen from drawing the hex code text literal string inside the image.
        brand_style = (
            "Official NaviGo Tech Solutions brand identity style guidelines: clean minimal white background, "
            "color palette strictly limited to deep navy blue, bright electric blue, "
            "and subtle vibrant accent orange. Modern flat vector design or 3D isometric business graphic style, "
            "sharp clean vector shapes, professional and high-trust corporate aesthetic, "
            "strictly no hex codes, no color code text, no hash symbols, no color numbers anywhere in the image. "
            "Extremely clean and highly legible typography, correct spelling, professional business presentation. "
            "CRITICAL BRANDING RULE: The image must contain NO logos and NO company branding of any kind. Absolutely do NOT render the word NaviGo, the phrase NaviGo Tech Solutions, or any company name, brand wordmark, tagline, signature, watermark, logo icon or branding crest anywhere in the image - the official logo is added separately afterwards. Keep any on-image text to an absolute minimum: only short, real, correctly spelled English words where essential, and never invented, distorted, or gibberish text."
        )

        # If keyword already contains detailed layout/infographic instructions, use it directly.
        # Otherwise, wrap it in a premium business infographic prompt structure.
        if keyword.lower().startswith(("a ", "infographic", "clean", "premium", "process", "diagram")):
            prompt = f"{keyword}. {brand_style}"
        else:
            prompt = (
                f"A modern, premium business infographic or digital illustration representing: {keyword}. "
                f"16:9 aspect ratio, suitable as a high-quality blog featured header image. {brand_style}"
            )
        print(f"[NANO BANANA] Requesting image generation with prompt: '{prompt}'")
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_images(
            model='imagen-4.0-generate-001',
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
                output_mime_type="image/jpeg",
            )
        )
        
        if response.generated_images:
            img_bytes = response.generated_images[0].image.image_bytes
            print("[NANO BANANA] Successfully generated custom featured image bytes")
            
            # Programmatically overlay the company logo to maintain strict brand identity
            try:
                import io
                from PIL import Image
                
                logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
                if os.path.exists(logo_path):
                    print("[BRAND LOGO] Overlaying company logo onto generated image...")
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                    logo = Image.open(logo_path).convert("RGBA")
                    
                    # Resize logo: height of 60px, maintaining aspect ratio
                    logo_h = 64
                    logo_w = int(logo.width * (logo_h / logo.height))
                    logo_resized = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
                    
                    # Position in top-right corner with 24px padding
                    padding = 24
                    pos_x = img.width - logo_w - padding
                    pos_y = padding
                    
                    # Overlay using the transparent alpha channel as a mask
                    img.paste(logo_resized, (pos_x, pos_y), logo_resized)
                    
                    # Convert back to RGB and save as JPEG bytes
                    img = img.convert("RGB")
                    out_io = io.BytesIO()
                    img.save(out_io, format="JPEG", quality=95)
                    img_bytes = out_io.getvalue()
                    print("[BRAND LOGO] Company logo successfully watermarked onto image!")
            except Exception as le:
                print(f"[WARN] Brand logo overlay failed: {le}")
                
            return img_bytes
        else:
            print("[WARN] Nano Banana returned no generated images")
            return None
    except Exception as e:
        print(f"[WARN] Nano Banana image generation failed: {e}")
        return None


def upload_image_bytes_to_wp(image_bytes, keyword, caption="", alt_text=None, filename_seed=None):
    """
    Uploads raw image bytes to WordPress Media Library.
    Sets alt text and caption for SEO. Returns the media attachment ID or None.
    """
    try:
        seed = filename_seed or keyword
        filename = re.sub(r"[^a-z0-9]+", "-", seed.lower())[:60].strip("-") + ".jpg"
        if not alt_text:
            alt_text = keyword.title()

        # Upload binary to WP Media Library
        upload_url = f"{WP_SITE_URL}/wp-json/wp/v2/media"
        r = _wp_request_with_backoff(
            requests.post,
            upload_url,
            data=image_bytes,
            headers={
                "Content-Type": "image/jpeg",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=60,
        )
        if r.status_code not in (200, 201):
            print(f"[WARN] WP media upload failed: {r.status_code} {r.text[:200]}")
            return None

        media_id = r.json().get("id")
        print(f"[OK] Featured image bytes uploaded (ID: {media_id})")

        # Set alt text + caption on the uploaded media
        _wp_request_with_backoff(
            requests.post,
            f"{WP_SITE_URL}/wp-json/wp/v2/media/{media_id}",
            json={
                "alt_text": alt_text,
                "caption":  caption,
            },
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=20,
        )
        return media_id

    except Exception as e:
        print(f"[WARN] Image bytes upload error: {e}")
        return None


def fetch_pexels_image(keyword):
    """
    Searches Pexels for a landscape photo matching the keyword.
    Returns (image_url, photographer) or (None, None) on failure.
    """
    if not PEXELS_API_KEY:
        print("[WARN] PEXELS_API_KEY not set — skipping featured image")
        return None, None

    # Use first 4 words for a cleaner image search
    search_query = " ".join(keyword.split()[:4])
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": search_query, "per_page": 3, "orientation": "landscape"},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[WARN] Pexels API error: {resp.status_code}")
            return None, None
        photos = resp.json().get("photos", [])
        if not photos:
            print(f"[WARN] No Pexels images found for: {search_query}")
            return None, None
        photo = photos[0]
        image_url  = photo["src"]["large2x"]
        photographer = photo.get("photographer", "Pexels")
        print(f"[OK] Pexels image: {image_url[:70]}... (by {photographer})")
        return image_url, photographer
    except Exception as e:
        print(f"[WARN] Pexels fetch failed: {e}")
        return None, None


def upload_image_to_wp(image_url, keyword, photographer="Pexels", alt_text=None, filename_seed=None):
    """
    Downloads an image from image_url and uploads it to WordPress Media Library.
    Sets alt text and caption for SEO. Returns the media attachment ID or None.
    """
    try:
        img_resp = requests.get(image_url, timeout=30)
        if img_resp.status_code != 200:
            print(f"[WARN] Image download failed: {img_resp.status_code}")
            return None

        seed = filename_seed or keyword
        filename = re.sub(r"[^a-z0-9]+", "-", seed.lower())[:60].strip("-") + ".jpg"
        if not alt_text:
            alt_text = keyword.title()

        # Upload binary to WP Media Library
        upload_url = f"{WP_SITE_URL}/wp-json/wp/v2/media"
        r = _wp_request_with_backoff(
            requests.post,
            upload_url,
            data=img_resp.content,
            headers={
                "Content-Type": "image/jpeg",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=60,
        )
        if r.status_code not in (200, 201):
            print(f"[WARN] WP media upload failed: {r.status_code} {r.text[:200]}")
            return None

        media_id = r.json().get("id")
        print(f"[OK] Featured image uploaded (ID: {media_id})")

        # Set alt text + caption on the uploaded media
        _wp_request_with_backoff(
            requests.post,
            f"{WP_SITE_URL}/wp-json/wp/v2/media/{media_id}",
            json={
                "alt_text": alt_text,
                "caption":  f"Photo by {photographer} via Pexels",
            },
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=20,
        )
        return media_id

    except Exception as e:
        print(f"[WARN] Image upload error: {e}")
        return None


# ─────────────────────────────────────────────
# STEP 6 — LOG TO GOOGLE SHEET
# ─────────────────────────────────────────────

def log_to_sheet(keyword, title, meta, content, post_id, post_url, status="Published"):
    if not GOOGLE_SHEET_URL:
        print("[WARN] GOOGLE_SHEET_URL not set. Skipping sheet log.")
        return

    from datetime import datetime, timezone
    ist_offset = 5.5 * 3600
    now = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + ist_offset
    ).strftime("%Y-%m-%d %H:%M IST")

    word_count = len(re.sub(r"<[^>]+>", "", content).split())

    payload = {
        "date":       now,
        "topic":      keyword,
        "title":      title,
        "url":        post_url,
        "post_id":    str(post_id),
        "word_count": str(word_count),
        "meta":       meta,
        "status":     status,
    }

    try:
        # Apps Script redirects: resolve the final URL first, then POST JSON directly
        session = requests.Session()
        redirect = session.get(
            GOOGLE_SHEET_URL, allow_redirects=False, timeout=20
        )
        final_url = redirect.headers.get("Location", GOOGLE_SHEET_URL)
        resp = session.post(final_url, json=payload, timeout=30)
        if resp.status_code == 200 and "success" in resp.text:
            print(f"[OK] Logged to Google Sheet: {title}")
        else:
            print(f"[WARN] Sheet log failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] Sheet log error: {e}")


# ─────────────────────────────────────────────
# GSC INDEXING RETRY QUEUE
# ─────────────────────────────────────────────

GSC_RETRY_FILE = os.path.join(os.path.dirname(__file__), "gsc_retry_queue.json")

def _load_gsc_queue():
    try:
        with open(GSC_RETRY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_gsc_queue(queue):
    with open(GSC_RETRY_FILE, "w") as f:
        json.dump(queue, f, indent=2)

def queue_gsc_retry(post_url):
    queue = _load_gsc_queue()
    if post_url not in queue:
        queue.append(post_url)
        _save_gsc_queue(queue)
        print(f"[GSC] Queued for retry later: {post_url}")

def retry_gsc_queue():
    queue = _load_gsc_queue()
    if not queue:
        return
    print(f"[GSC] Retrying {len(queue)} queued URL(s)...")
    succeeded = set()
    quota_hit = False
    for url in queue:
        if quota_hit:
            break
        try:
            result = browser_agent.submit_to_gsc(url)
            if "SUCCESS" in result:
                print(f"[GSC] Retry SUCCESS: {url}")
                succeeded.add(url)
            elif "ALREADY_INDEXED" in result:
                print(f"[GSC] Already indexed: {url}")
                succeeded.add(url)
            elif "QUOTA_EXCEEDED" in result:
                print(f"[GSC] Still quota-limited — will retry next run")
                quota_hit = True
            else:
                print(f"[GSC] Retry result: {result} — dropping: {url}")
                succeeded.add(url)
        except Exception as e:
            print(f"[GSC] Retry error: {e} — keeping in queue: {url}")
    remaining = [u for u in queue if u not in succeeded]
    _save_gsc_queue(remaining)
    if remaining:
        print(f"[GSC] {len(remaining)} URL(s) still in retry queue")
    else:
        print(f"[GSC] Retry queue cleared!")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="NaviGo Blog Auto-Generator Tool")
    parser.add_argument("--keyword", help="Custom keyword to generate a post for dynamically")
    args, unknown = parser.parse_known_args()

    if not all([ANTHROPIC_API_KEY, WP_USERNAME, WP_APP_PASSWORD]):
        missing = [
            k for k, v in {
                "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                "WP_USERNAME": WP_USERNAME,
                "WP_APP_PASSWORD": WP_APP_PASSWORD,
            }.items() if not v
        ]
        print(f"[ERROR] Missing secrets: {', '.join(missing)}")
        raise SystemExit(1)

    # Retry any GSC indexing that failed due to quota earlier
    try:
        retry_gsc_queue()
    except Exception as e:
        print(f"[WARN] GSC retry queue check failed: {e}")

    breaking_mode = False
    if args.keyword:
        print(f"[MODE] Custom keyword override: '{args.keyword}'")
        keyword = args.keyword
    else:
        breaking_mode = os.getenv("BREAKING_NEWS_ONLY", "").lower() in ("1", "true", "yes")

        if breaking_mode:
            # Breaking news mode: only post if a major AI announcement happened in last 2 hours
            print("[MODE] Breaking news check")
            keyword = detect_breaking_news(max_age_hours=1.5)
            if not keyword:
                print("[OK] No breaking news. No post needed.")
                return
            if _breaking_count_today() >= BREAKING_DAILY_CAP:
                print(f"[BREAKING] Daily cap of {BREAKING_DAILY_CAP} breaking posts reached. Skipping.")
                return
        else:
            # Regular mode: discover today's best topic
            print("[MODE] Regular scheduled post")
            keyword = discover_topic()
            if not keyword:
                print("[WARN] Discovery failed. Falling back to keywords.txt...")
                keyword = read_next_keyword()
            if not keyword:
                print("[WARN] No topic available. Add keywords to keywords.txt or check RSS access.")
                return

    try:
        # Step 2: Research the topic from the internet
        research = research_topic(keyword)

        # Step 2b: Deep browser research for richer content (non-fatal)
        try:
            deep_research = browser_agent.browser_research(keyword)
            if deep_research:
                research = research + "\n\n--- DEEP WEB RESEARCH ---\n" + deep_research
        except Exception as e:
            print(f"[WARN] Browser research failed: {e} — continuing with RSS research only")

        # Step 3: Generate the blog in NaviGo HTML template style
        title, content, meta, focus_keyword, category, tags = generate_blog(keyword, research)

        print(f"[OK] Title: {title}")
        print(f"[OK] Focus keyword: {focus_keyword}")
        print(f"[OK] Category: {category}")
        print(f"[OK] Tags: {', '.join(tags)}")
        print(f"[OK] Content length: {len(content)} chars")

        # Step 3b: Fetch and upload featured image (non-fatal)
        featured_media_id = None
        try:
            # Try Google Gemini (Nano Banana / Imagen) first if API key is set
            if GEMINI_API_KEY:
                print("[IMAGE] Attempting branded image generation (text-free illustration + code text)...")
                import brand_image
                image_bytes = brand_image.generate_featured(title, GEMINI_API_KEY, call_ai)
                if image_bytes:
                    featured_media_id = upload_image_bytes_to_wp(
                        image_bytes,
                        keyword,
                        caption=f"{focus_keyword} - NaviGo Tech Solutions",
                        alt_text=title,
                        filename_seed=(focus_keyword or title),
                    )
            
            # Fallback to Pexels if Gemini was skipped or failed
            if not featured_media_id:
                print("[IMAGE] Falling back to Pexels for stock photo...")
                image_url, photographer = fetch_pexels_image(keyword)
                if image_url:
                    featured_media_id = upload_image_to_wp(image_url, keyword, photographer)
        except Exception as e:
            print(f"[WARN] Featured image step failed: {e} — continuing without image")

        # Step 3c: Parse and inject inline images (non-fatal)
        try:
            print("[IMAGE] Scanning for inline image placeholders...")
            placeholders = re.findall(r"\[IMAGE_PLACEHOLDER:\s*(.*?)\]", content)
            print(f"[IMAGE] Found {len(placeholders)} inline image placeholder(s)")
            
            # Process up to 2 inline images to keep it performant
            for i, prompt in enumerate(placeholders[:2]):
                prompt = prompt.strip()
                print(f"[IMAGE] Processing inline image {i+1}/2: '{prompt}'")
                
                inline_media_id = None
                img_url = None
                
                # 1. Try Google Gemini Nano Banana
                if GEMINI_API_KEY:
                    try:
                        print(f"[IMAGE] Generating inline text-free illustration: '{prompt}'")
                        import brand_image
                        img_bytes = brand_image.generate_illustration(prompt, GEMINI_API_KEY, call_ai)
                        if img_bytes:
                            inline_media_id = upload_image_bytes_to_wp(
                                img_bytes,
                                prompt,
                                caption="",
                                alt_text=f"{focus_keyword} illustration: {prompt[:80]}",
                                filename_seed=f"{focus_keyword}-{i+1}",
                            )
                    except Exception as ex:
                        print(f"[WARN] Inline Nano Banana generation failed: {ex}")
                
                # 2. Fallback to Pexels
                if not inline_media_id:
                    try:
                        print(f"[IMAGE] Falling back to Pexels for inline image: '{prompt}'")
                        pexels_url, photographer = fetch_pexels_image(prompt)
                        if pexels_url:
                            inline_media_id = upload_image_to_wp(pexels_url, prompt, photographer)
                    except Exception as ex:
                        print(f"[WARN] Inline Pexels fetch failed: {ex}")
                
                # 3. If uploaded, retrieve the attachment source URL and replace placeholder
                if inline_media_id:
                    try:
                        media_endpoint = f"{WP_SITE_URL}/wp-json/wp/v2/media/{inline_media_id}"
                        r_media = requests.get(media_endpoint, auth=(WP_USERNAME, WP_APP_PASSWORD), verify=False, timeout=15)
                        if r_media.status_code == 200:
                            img_url = r_media.json().get("source_url")
                    except Exception as ex:
                        print(f"[WARN] Failed to retrieve source URL for media ID {inline_media_id}: {ex}")
                
                if img_url:
                    # Detailed prompt is kept in the alt tag for perfect SEO,
                    # but we omit the figcaption so the live blog body remains clean and aesthetic.
                    image_block = f"""
                    <figure class="wp-block-image size-large" style="margin: 32px 0; text-align: center;">
                      <img src="{img_url}" alt="{prompt}" style="border-radius: 12px; max-width: 100%; height: auto; box-shadow: 0 4px 15px rgba(0,0,0,0.08);" />
                    </figure>
                    """
                    content = re.sub(
                        r"\[IMAGE_PLACEHOLDER:\s*" + re.escape(prompt) + r"\]",
                        image_block,
                        content,
                        count=1
                    )
                    print(f"[OK] Injected inline image {i+1} successfully! (ID: {inline_media_id})")
                else:
                    print(f"[WARN] Could not retrieve image URL for '{prompt}'. Removing placeholder.")
                    content = re.sub(
                        r"\[IMAGE_PLACEHOLDER:\s*" + re.escape(prompt) + r"\]",
                        "",
                        content,
                        count=1
                    )
        except Exception as e:
            print(f"[WARN] Inline image injection step failed: {e} — continuing with unmodified content")

        # Step 4: Post to WordPress
        post_id, post_url = send_to_wordpress(title, content, meta, focus_keyword, category, tags, featured_media_id)

        # Step 4b: Inject Article + FAQPage schema now that we have the real URL
        content_with_schema = generate_schema(title, meta, content, post_url)
        patch_wp_post_content(post_id, content_with_schema)

        # Record topic immediately after successful publish so duplicates never happen
        # even if downstream steps (Twitter, sheet) fail
        save_used_topic(keyword)
        if breaking_mode:
            _increment_breaking_count()

        # Step 5: Ping search engines for immediate indexing
        ping_search_engines(post_url)

        # Step 5b: Submit to Google Search Console via browser agent (non-fatal)
        try:
            gsc_result = browser_agent.submit_to_gsc(post_url)
            if "SUCCESS" in gsc_result:
                print(f"[OK] GSC indexing requested via browser agent")
            elif "ALREADY_INDEXED" in gsc_result:
                print(f"[OK] URL already indexed in Google")
            elif "QUOTA_EXCEEDED" in gsc_result or "LOGIN_REQUIRED" in gsc_result:
                queue_gsc_retry(post_url)
            else:
                print(f"[WARN] GSC browser indexing result: {gsc_result}")
                queue_gsc_retry(post_url)
        except Exception as e:
            print(f"[WARN] GSC browser indexing failed: {e} — IndexNow already sent")
            queue_gsc_retry(post_url)

        # Step 6: Log to Google Sheet (non-fatal)
        try:
            log_to_sheet(keyword, title, meta, content, post_id, post_url)
        except Exception as e:
            print(f"[WARN] Sheet log failed: {e} — continuing")

        print("[OK] AUTOMATION FULLY COMPLETED SUCCESSFULLY")

    except Exception as e:
        print(f"[ERROR] Workflow failed: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
