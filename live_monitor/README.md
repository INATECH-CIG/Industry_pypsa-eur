# Live Monitor

A small local dashboard for live Brent crude, Donald Trump's Truth Social posts, and Iran-war updates from selected news sources.

Run it with:

```powershell
python .\live_monitor\app.py
```

Then open:

```text
http://127.0.0.1:8765
```

The dashboard refreshes Brent oil every 1 second and the news/social sources every 30 seconds by default. Each source card shows the latest 4 matching items. Edit `live_monitor/config.json` to change polling intervals, item limits, keywords, or source URLs.

Notes:

- Brent uses Investing.com's Brent Oil page first and displays contract symbol `LCOQ6`. If Investing.com blocks the request, the backend falls back to Yahoo Finance's public chart endpoint for `BZ=F` and marks that fallback in the oil status.
- Truth Social uses the public Mastodon-compatible statuses endpoint for Donald Trump's account id. If Truth Social blocks the request, the source card will show the error.
- Al Jazeera finds the latest RSS item whose title contains `Iran war day`, then parses that daily page. If you find a specific Al Jazeera liveblog URL, replace that source with `"type": "liveblog"` and the exact URL.
- Reuters blocks the simple direct page fetcher with `401` in this environment, so the default connector uses Google News RSS constrained to `site:reuters.com Iran war`. The items still link through to Reuters coverage when Google includes Reuters results. If you have a specific Reuters live URL that is accessible from your machine, use `"type": "liveblog"` with that URL.
