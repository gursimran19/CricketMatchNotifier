# Cricket Match Notifier

A small Python tool that watches a live cricket match on [CricketSasa](https://cricketsasa.ca) (used by the Manitoba Cricket Association) and sends a Telegram alert the moment a wicket, six, or four happens — so you don't have to keep the scoring app open on your phone.

## Why I built this

I follow local MCA matches on CricketSasa, but the app needs to stay open to see live updates, which isn't practical during the day. This project polls the match data in the background and only pings me when something worth knowing about actually happens.

It also doubles as a small data engineering exercise: pulling semi-structured data from an external source, parsing it, detecting meaningful changes (event diffing), and pushing those changes downstream — the same basic shape as a lot of real ETL/streaming pipelines, just at a much smaller scale.

## How it works

1. **Fetch** — polls a specific match's ball-by-ball commentary feed on a timer (every ~30 seconds)
2. **Parse** — the feed returns an HTML table; `BeautifulSoup` extracts each delivery (over, ball, outcome, commentary text)
3. **Diff** — keeps track of which deliveries have already been seen, so only *new* balls get processed each cycle
4. **Classify** — each new ball is tagged as a wicket, six, four, or normal delivery based on a CSS class in the response
5. **Notify** — wickets, sixes, and fours are sent to a Telegram chat via the Telegram Bot API; everything else is just logged to the console

## Tech used

- Python 3
- `requests` — HTTP polling
- `beautifulsoup4` — HTML parsing
- Telegram Bot API — notifications

## Notes

- The script disables SSL certificate verification specifically for cricketsasa.ca, since that server's certificate chain appears to be misconfigured (it loads fine in browsers, which patch this automatically, but not in raw Python). All other requests, e.g. to Telegram, use normal verification.
- Polling is intentionally rate-limited (~30s) out of respect for a small, volunteer-run site — this isn't meant to run continuously or at high frequency.

## Possible next steps

- Auto-detect the current live match ID instead of copying it manually from DevTools each time
- Track full match state (score, overs, run rate) instead of just event alerts
- Add a simple dashboard (e.g. Power BI) summarizing notified events over a season
