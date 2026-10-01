"""
CricketSasa Live Match Notifier
================================

Watches a live cricket match on CricketSasa (used by the Manitoba Cricket
Association) and sends a Telegram alert whenever a wicket, six, or four
happens -- so you don't have to keep the scoring app open to follow along.

How it works
------------
CricketSasa's live scorecard page loads its ball-by-ball commentary via a
background request to comm_4_res.php rather than baking it into the page.
We poll that same endpoint on a timer, diff each response against what
we've already seen, and classify any new deliveries by what actually
happened on the ball.

Setup
-----
1. pip install requests beautifulsoup4
2. Create a Telegram bot via @BotFather and put the token + chat ID(s)
   in config.py (kept out of version control -- see .gitignore)
3. Fill in MATCH CONFIG below. These values come from the browser's
   DevTools Network tab: open the live match's Commentary tab, find the
   request to comm_4_res.php, and copy its query parameters.
4. Run: python cricket_notifier.py
5. Stop with Ctrl+C once the match ends.

A note on etiquette
-------------------
This is a small, volunteer-run site, not a commercial API. POLL_SECONDS
is deliberately conservative -- please don't drop it below 20-30 seconds,
and only run this while a match you actually care about is live.
"""

import re
import time

import requests
import urllib3
from bs4 import BeautifulSoup

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_CHAT_ID_2


# -----------------------------------------------------------------------
# cricketsasa.ca's server has an incomplete SSL certificate chain. It
# loads fine in a browser, which silently fetches the missing intermediate
# certificate on its own -- Python's ssl library doesn't do that. Since
# we're only ever reading public match data from this one trusted site,
# we disable verification here and suppress the warning it would
# otherwise print on every single request.
# -----------------------------------------------------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =========================================================================
# CONFIGURATION
# =========================================================================

# When True, on startup we immediately send a Telegram alert for every
# wicket/six/four already in the match's history (not just new ones from
# this point forward), then fall through into normal live polling.
#
# Handy for catching up after fixing a bug, or for getting the full
# picture of a match that's already well underway. Set to False if you
# only want alerts for events that happen *after* you start the script.
BACKFILL_ON_START = True

# How often to poll, in seconds. Keep this at 20-30s minimum -- see the
# etiquette note above.
POLL_SECONDS = 30

# --- Match identifiers -------------------------------------------------
# These four values pin the script to one specific match and innings.
# Grab them from the Network tab while the match is live (see Setup above).
#
# Current match: Gladiators 2 vs Bengal Tigers 2, MCA Division-2 2026
# (Bridgewater, WPG). Gladiators 2 are currently batting.
BASE_URL = "https://cricketsasa.ca/cricket/comm_4_res.php"
MATCH_ID = "196"
YEAR = "2026"
BATTING_TEAM_ID = "190"    # Gladiators 2 -- currently batting
BOWLING_TEAM_ID = "130"    # Bengal Tigers 2 -- currently bowling
TOTAL_OVERS = "50"         # deliberately generous so the feed always returns everything available
COMM_OPTION = "1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal cricket-alert script; contact: you@example.com)"
}


# =========================================================================
# FETCHING
# =========================================================================

def fetch_commentary():
    """Pull the raw ball-by-ball commentary HTML for the configured match."""
    params = {
        "match_id": MATCH_ID,
        "year": YEAR,
        "batting_team_id": BATTING_TEAM_ID,
        "bowling_team_id": BOWLING_TEAM_ID,
        "total_overs": TOTAL_OVERS,
        "comm_option": COMM_OPTION,
    }
    response = requests.get(
        BASE_URL, params=params, headers=HEADERS, timeout=15, verify=False
    )
    response.raise_for_status()
    return response.text


# =========================================================================
# PARSING
# =========================================================================

def parse_balls(html):
    """
    Turn the raw commentary HTML into a list of structured ball events.

    Returns events newest-first (matching the site's own order), where
    each event is a dict:

        {
            "key": "9.5",                 # over.ball, used to detect duplicates
            "kind": "wicket" | "six" | "four" | "wide" | "normal",
            "text": "JEYUL PATEL to Jas Gill : Out! Caught Behind",
            "new_batsman": "Narayan Singh" or None,
        }

    Two quirks of the feed worth knowing about:

    1. Classification is fragile if you trust the markup too literally.
       The <span> wrapping each ball's result has a CSS class name AND a
       short text label (e.g. "4", "Wkt"), but the site uses several
       different class names / flavor-text templates for what is
       functionally the same event (we found this out the hard way when
       a four went unclassified). The one thing that's always consistent
       is the plain-English commentary sentence itself -- it reliably
       ends in a phrase like "Four Runs" or "Out!" -- so we match on that
       first and only fall back to the span as a backstop.

    2. "New batsman" rows have no over/ball number of their own, so they
       aren't events in the usual sense. But the site always places one
       directly above (i.e. more recent than) the wicket that caused it,
       in this newest-first ordering. We remember the incoming batter's
       name as we walk through the rows and attach it to the very next
       wicket we find.
    """
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # Tracks the name of a batter who just walked in, until we reach the
    # wicket event that brought them to the crease (see point 2 above).
    pending_new_batsman = None

    for row in soup.find_all("tr"):
        over_tag = row.find("comover")
        ball_tag = row.find("comball")

        # Rows without both of these aren't individual deliveries -- they're
        # end-of-over summaries, or "new batsman"/"new bowler" announcements.
        if not over_tag or not ball_tag:
            is_new_batsman_row = row.find("img", src=re.compile(r"bat\.png"))
            if is_new_batsman_row:
                batsman_tag = row.find("bc")
                if batsman_tag:
                    pending_new_batsman = batsman_tag.get_text(strip=True)
            continue

        key = f"{over_tag.get_text(strip=True)}{ball_tag.get_text(strip=True)}"

        result_span = row.find("span")
        span_text = result_span.get_text(strip=True) if result_span else ""

        # The commentary sentence is always in the last <td> of the row.
        table_cells = row.find_all("td")
        commentary = table_cells[-1].get_text(" ", strip=True) if table_cells else span_text

        kind = classify_delivery(commentary, span_text)

        events.append({
            "key": key,
            "kind": kind,
            "text": commentary,
            "new_batsman": pending_new_batsman if kind == "wicket" else None,
        })

        # Whatever we were holding only ever applies to the single row
        # immediately following it -- reset regardless of whether it got used.
        pending_new_batsman = None

    return events


def classify_delivery(commentary, span_text):
    """
    Work out what actually happened on a delivery.

    Prefers the plain-English commentary sentence (reliable across all
    the flavor-text variants the site uses) and falls back to the short
    span label only if the sentence doesn't match anything expected.
    """
    if "Out!" in commentary:
        return "wicket"
    if "Six Runs" in commentary:
        return "six"
    if "Four Runs" in commentary:
        return "four"
    if "Wide Ball" in commentary:
        return "wide"

    # Backstop, in case a future flavor-text variant doesn't include the
    # phrases above for some reason.
    return {
        "Wkt": "wicket",
        "6": "six",
        "4": "four",
        "Wd": "wide",
    }.get(span_text, "normal")


# =========================================================================
# NOTIFYING
# =========================================================================

def send_telegram(message):
    """Send a message to every configured Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_CHAT_ID_2):
        try:
            requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
        except requests.RequestException as error:
            print(f"[warn] failed to send Telegram message to {chat_id}: {error}")


def format_event_message(event):
    """Turn a parsed event into a human-readable Telegram message."""
    icon = {"wicket": "🔴 WICKET", "six": "🚀 SIX", "four": "🔥 FOUR"}[event["kind"]]
    message = f"{icon} ({event['key']})\n{event['text']}"

    if event.get("new_batsman"):
        message += f"\n🏏 New batsman: {event['new_batsman']}"

    return message


# =========================================================================
# BACKFILL
# =========================================================================

def run_backfill(events):
    """
    Send a Telegram alert for every wicket/six/four already in the match's
    history. Used on startup when BACKFILL_ON_START is True, so a script
    started mid-match (or restarted after a fix) doesn't miss anything
    that already happened.
    """
    highlights = [e for e in events if e["kind"] in ("wicket", "six", "four")]

    if not highlights:
        print("[backfill] no wickets/sixes/fours found in this match's data yet.")
        return

    # Events arrive newest-first; reverse so the alerts land in the order
    # they actually happened.
    highlights.reverse()

    print(f"[backfill] sending {len(highlights)} existing alert(s) to Telegram...")
    for event in highlights:
        message = format_event_message(event)
        print(message)
        send_telegram(message)
        time.sleep(2)  # small gap so messages arrive as distinct, readable notifications

    print("[backfill] done catching up. Now watching for new events...")


# =========================================================================
# MAIN LOOP
# =========================================================================

def main():
    print("Starting cricket notifier... (Ctrl+C to stop)")

    seen_keys = set()
    is_first_poll = True

    while True:
        try:
            html = fetch_commentary()
            events = parse_balls(html)

            if is_first_poll:
                seen_keys = {event["key"] for event in events}
                is_first_poll = False
                print(f"[init] loaded {len(seen_keys)} existing balls, watching for new ones...")

                if BACKFILL_ON_START:
                    run_backfill(events)
                    # Deliberately no return here -- we fall through into
                    # the normal polling loop below instead of exiting.
            else:
                new_events = [e for e in events if e["key"] not in seen_keys]

                # new_events is newest-first; reverse so we announce them
                # in the order they actually happened.
                for event in reversed(new_events):
                    seen_keys.add(event["key"])

                    if event["kind"] in ("wicket", "six", "four"):
                        message = format_event_message(event)
                        print(message)
                        send_telegram(message)
                    else:
                        print(f"[ball {event['key']}] {event['text']}")

        except requests.RequestException as error:
            print(f"[error] request failed: {error}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()