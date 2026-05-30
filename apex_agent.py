#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║   Apex Management Group — 24/7 Lead Agent                   ║
║   Läuft auf Railway.app (kostenlos) auch ohne MacBook       ║
║   Telegram-Benachrichtigung bei jedem neuen Lead            ║
╚══════════════════════════════════════════════════════════════╝

SETUP:
  1. pip install requests
  2. Telegram Bot erstellen → @BotFather → /newbot
  3. Chat-ID holen → @userinfobot (schreib /start)
  4. Env-Variablen setzen (lokal oder auf Railway):
       TELEGRAM_BOT_TOKEN=xxx
       TELEGRAM_CHAT_ID=xxx
  5. Starten: python3 apex_agent.py

CLOUD DEPLOYMENT (Railway.app — kostenlos):
  1. github.com → neues Repo → Dateien hochladen
  2. railway.app → New Project → Deploy from GitHub
  3. Variables → TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID eintragen
  4. Deploy → läuft 24/7
"""

import os
import json
import time
import random
import requests
from datetime import datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# KONFIGURATION
# ══════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

INTERVAL_HOURS  = int(os.getenv("INTERVAL_HOURS", "2"))
MAX_PER_RUN     = int(os.getenv("MAX_PER_RUN", "3"))
MIN_SCORE       = int(os.getenv("MIN_SCORE", "20"))

SEEN_FILE = Path("seen_posts.json")

HEADERS = {
    "User-Agent": "apex-management-research/1.0 (business; contact: hello@apex-management.com)"
}

# Subreddits + Suchanfragen
SEARCHES = [
    ("onlyfansadvice",    "looking for manager"),
    ("onlyfansadvice",    "need a manager"),
    ("onlyfansadvice",    "seeking management"),
    ("onlyfansadvice",    "need help growing"),
    ("onlyfans_creators", "looking for manager"),
    ("onlyfans_creators", "need management"),
    ("onlyfans_creators", "struggling with growth"),
    ("CreatorsAdvice",    "looking for manager"),
    ("CreatorsAdvice",    "need manager"),
    ("SexWorkersOnly",    "need a manager"),
]

# Score-Keywords
HIGH_KEYWORDS = [
    "looking for manager", "need a manager", "seeking manager",
    "want a manager", "need management", "find a manager",
    "searching for manager", "need someone to manage"
]
MED_KEYWORDS = [
    "struggling", "plateau", "stuck at", "can't grow", "need help",
    "low subscribers", "increase revenue", "advice on growing",
    "how to grow", "more subscribers", "traffic help"
]
LOW_KEYWORDS = ["onlyfans", "creator", "content", "of account"]

# ══════════════════════════════════════════════════════════════
# DM-VORLAGEN — abgestimmt auf Situation
# ══════════════════════════════════════════════════════════════

DM_TEMPLATES = {
    "seeking_manager": (
        "Hey! I came across your post and wanted to reach out.\n\n"
        "I run Apex Management Group — we help OnlyFans creators with "
        "pricing strategy, fan messaging, and traffic growth.\n\n"
        "I'd love to offer you a free account audit — no commitment, just "
        "an honest look at what's holding your account back and what we'd "
        "do differently. Usually takes about 30 minutes.\n\n"
        "Would that be useful for you?"
    ),
    "growth_problems": (
        "Hey! Saw your post — that plateau stage is genuinely frustrating, "
        "and it's something I've helped a few creators work through.\n\n"
        "I run Apex Management Group. I'd like to offer you a free account "
        "audit — we look at your pricing, traffic sources, and messaging "
        "strategy together. No pitch, just real feedback.\n\n"
        "Interested?"
    ),
    "bad_experience": (
        "Hey! Sorry to hear about your experience — unfortunately bad "
        "managers are way too common in this space.\n\n"
        "I run Apex Management Group. We work on a pure revenue-share "
        "basis — I only earn when you earn, you keep all your passwords, "
        "and everything is fully transparent.\n\n"
        "Would you be open to a free account audit so you can see how "
        "we work before committing to anything?"
    ),
    "general": (
        "Hey! Noticed your post and wanted to reach out.\n\n"
        "I manage OnlyFans accounts at Apex Management Group — strategy, "
        "fan communication, and traffic growth.\n\n"
        "Would you be open to a free account audit? No commitment — just "
        "an honest look at what could be improved. Takes about 30 minutes.\n\n"
        "Let me know!"
    ),
}

# ══════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ══════════════════════════════════════════════════════════════

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(list(seen)))


def score_post(title: str, body: str) -> int:
    text = (title + " " + (body or "")).lower()
    score = 0
    for kw in HIGH_KEYWORDS:
        if kw in text:
            score += 35
    for kw in MED_KEYWORDS:
        if kw in text:
            score += 12
    for kw in LOW_KEYWORDS:
        if kw in text:
            score += 3
    return min(score, 100)


def categorize(title: str, body: str) -> str:
    text = (title + " " + (body or "")).lower()
    for kw in ["looking for manager", "need a manager", "seeking manager",
               "want a manager", "find a manager", "searching for"]:
        if kw in text:
            return "seeking_manager"
    for kw in ["bad manager", "bad experience", "scammed", "previous manager",
               "old manager", "left me", "ghosted"]:
        if kw in text:
            return "bad_experience"
    for kw in ["stuck", "plateau", "struggling", "grow", "growth", "help"]:
        if kw in text:
            return "growth_problems"
    return "general"


# ══════════════════════════════════════════════════════════════
# REDDIT-SUCHE (ohne API-Key — öffentliches JSON)
# ══════════════════════════════════════════════════════════════

def search_reddit(subreddit: str, query: str) -> list:
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q":           query,
        "sort":        "new",
        "t":           "week",
        "restrict_sr": "1",
        "limit":       15,
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
        posts = []
        for child in children:
            d = child.get("data", {})
            post_id = d.get("id", "")
            if not post_id:
                continue
            posts.append({
                "id":      post_id,
                "title":   d.get("title", ""),
                "body":    d.get("selftext", ""),
                "author":  d.get("author", "[deleted]"),
                "url":     "https://reddit.com" + d.get("permalink", ""),
                "sub":     subreddit,
                "ups":     d.get("ups", 0),
                "created": d.get("created_utc", 0),
            })
        return posts
    except requests.exceptions.HTTPError as e:
        print(f"  [WARN] HTTP error ({subreddit} / {query}): {e}")
        return []
    except Exception as e:
        print(f"  [WARN] Search failed ({subreddit} / {query}): {e}")
        return []


# ══════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════

def send_telegram(text: str, silent: bool = False) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"\n[NO TELEGRAM] {text}\n")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
        "disable_notification":     silent,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("  [Telegram] ✓ Sent")
            return True
        else:
            print(f"  [Telegram] ✗ {r.status_code}: {r.text[:100]}")
            return False
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False


def format_lead(lead: dict, dm: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    short_title = lead["title"][:90] + ("…" if len(lead["title"]) > 90 else "")
    return (
        f"🎯 <b>NEUER LEAD — Apex Agent</b>\n\n"
        f"📌 r/{lead['sub']}\n"
        f"<b>{short_title}</b>\n\n"
        f"👤 u/{lead['author']}\n"
        f"⭐ Score: {lead['score']}/100\n"
        f"🔗 {lead['url']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>FERTIGE DM — KOPIEREN UND SENDEN:</b>\n\n"
        f"<code>{dm}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"→ Geh auf Reddit, schreib u/{lead['author']} an.\n"
        f"→ Trag den Lead in den Revenue Tracker ein.\n"
        f"<i>{ts}</i>"
    )


# ══════════════════════════════════════════════════════════════
# HAUPT-ZYKLUS
# ══════════════════════════════════════════════════════════════

def run_cycle(seen: set) -> tuple[set, int]:
    """Führt einen Suchzyklus durch. Gibt (seen, neue_leads_count) zurück."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[{now}] ── Neuer Suchzyklus ──")

    # Alle Subreddits durchsuchen
    raw_posts = []
    for sub, query in SEARCHES:
        posts = search_reddit(sub, query)
        print(f"  r/{sub} | \"{query}\" → {len(posts)} Posts")
        raw_posts.extend(posts)
        time.sleep(random.uniform(1.8, 3.5))  # Rate-Limit einhalten

    # Duplikate entfernen (gleiche Post-ID)
    unique: dict[str, dict] = {}
    for p in raw_posts:
        if p["id"] not in unique:
            unique[p["id"]] = p

    # Bereits gesehene herausfiltern
    new_posts = [p for pid, p in unique.items() if pid not in seen]
    print(f"  {len(new_posts)} neue Posts (nicht schon gesehen)")

    # Scorung + Filter
    for p in new_posts:
        p["score"] = score_post(p["title"], p["body"])
    qualified = [p for p in new_posts if p["score"] >= MIN_SCORE]
    qualified.sort(key=lambda x: x["score"], reverse=True)

    print(f"  {len(qualified)} qualifizierte Leads (Score ≥ {MIN_SCORE})")

    top = qualified[:MAX_PER_RUN]

    if not top:
        msg = (
            f"ℹ️ <b>Apex Agent — Zyklus abgeschlossen</b>\n"
            f"Keine neuen qualifizierten Leads gefunden.\n"
            f"Nächste Suche in {INTERVAL_HOURS}h. 💪"
        )
        send_telegram(msg, silent=True)
        print("  Keine neuen Leads.")
    else:
        print(f"  {len(top)} Lead(s) werden gesendet…")
        for lead in top:
            cat = categorize(lead["title"], lead["body"])
            dm  = DM_TEMPLATES[cat]
            msg = format_lead(lead, dm)
            send_telegram(msg)
            seen.add(lead["id"])
            time.sleep(2)

        summary = (
            f"✅ <b>Zyklus fertig: {len(top)} Lead(s) gefunden!</b>\n"
            f"Nächste Suche in {INTERVAL_HOURS}h.\n\n"
            f"<b>Denk dran:</b>\n"
            f"→ DM abschicken = nächster Schritt zum Vertrag\n"
            f"→ Lead in Revenue Tracker eintragen\n"
            f"→ Jeder Kontakt bringt dich näher an €1.500 💜"
        )
        send_telegram(summary, silent=True)

    return seen, len(top)


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   Apex Management Group — Lead Agent v1.0            ║")
    print("║   Läuft 24/7 — Ctrl+C zum Stoppen                   ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if not TELEGRAM_BOT_TOKEN:
        print("⚠️  TELEGRAM_BOT_TOKEN nicht gesetzt!")
        print("   Leads werden nur in der Konsole angezeigt.")
        print("   Für Telegram: env-Variable TELEGRAM_BOT_TOKEN setzen.\n")

    if not TELEGRAM_CHAT_ID:
        print("⚠️  TELEGRAM_CHAT_ID nicht gesetzt!\n")

    # Startbenachrichtigung
    send_telegram(
        "🚀 <b>Apex Lead Agent gestartet!</b>\n\n"
        "Ich überwache Reddit jetzt rund um die Uhr.\n"
        f"Suchlauf alle {INTERVAL_HOURS}h.\n\n"
        "Ziel: <b>€1.500 in 14 Tagen.</b>\n"
        "Ich finde die Leads — du schließt die Deals. Let's go. ✦"
    )

    seen = load_seen()
    total_leads = 0
    cycle_count = 0

    while True:
        try:
            seen, new_count = run_cycle(seen)
            save_seen(seen)
            total_leads  += new_count
            cycle_count  += 1
            print(f"  Gesamt: {total_leads} Leads in {cycle_count} Zyklen")
        except KeyboardInterrupt:
            print("\n[Gestoppt] Agent wurde manuell beendet.")
            send_telegram("⏹️ <b>Apex Agent gestoppt</b> (manuell).")
            break
        except Exception as e:
            print(f"[FEHLER] Zyklus fehlgeschlagen: {e}")
            send_telegram(f"⚠️ <b>Agent-Fehler:</b>\n<code>{e}</code>\nNeu-Versuch in 30 Min.")
            time.sleep(1800)
            continue

        sleep_secs = INTERVAL_HOURS * 3600
        print(f"\n  Schläft {INTERVAL_HOURS}h … ({sleep_secs}s)\n")
        time.sleep(sleep_secs)


if __name__ == "__main__":
    main()
