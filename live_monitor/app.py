from __future__ import annotations

import datetime as dt
import html
import json
import re
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
OIL_CACHE: dict[str, Any] = {"value": None, "monotonic": 0.0}
OIL_LOCK = threading.Lock()
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


@dataclass
class FetchResult:
    ok: bool
    status: str
    items: list[dict[str, Any]]
    fetched_at: str


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "br", "li", "h1", "h2", "h3", "time"}:
            self.parts.append("\n")
        if tag == "a":
            attrs_dict = dict(attrs)
            self._href = attrs_dict.get("href")
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._href:
            text = clean_text(" ".join(self._link_text))
            if text:
                self.links.append({"text": text, "href": self._href})
            self._href = None
            self._link_text = []
        if tag in {"p", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._href is not None:
            self._link_text.append(data)
        self.parts.append(data)

    def text(self) -> str:
        return clean_text("\n".join(self.parts), keep_newlines=True)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_text(value: str, keep_newlines: bool = False) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    if keep_newlines:
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n\s+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()
    return re.sub(r"\s+", " ", value).strip()


def clamp_text(value: str, limit: int = 900) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def parse_float(value: str) -> float:
    return float(value.replace(",", "").replace("%", "").strip())


def fetch_url(url: str, accept: str = "*/*", timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def keyword_hit(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def parse_truthsocial(source: dict[str, Any], keywords: list[str]) -> FetchResult:
    raw = fetch_url(source["url"], accept="application/json")
    statuses = json.loads(raw.decode("utf-8"))
    items = []
    limit = int(source.get("limit", 4))
    for status in statuses:
        content = clean_text(status.get("content", ""))
        if keywords and not keyword_hit(content, keywords):
            continue
        account = status.get("account") or {}
        items.append(
            {
                "source": source["label"],
                "title": f"@{account.get('acct', 'realDonaldTrump')}",
                "body": content,
                "published": status.get("created_at"),
                "url": status.get("url") or status.get("uri") or "https://truthsocial.com/@realDonaldTrump",
            }
        )
    return FetchResult(True, f"{len(items)} matching posts", items[:limit], utc_now())


def parse_rss(source: dict[str, Any], keywords: list[str]) -> FetchResult:
    raw = fetch_url(source["url"], accept="application/rss+xml, application/xml, text/xml")
    root = ET.fromstring(raw)
    items = []
    limit = int(source.get("limit", 4))
    for node in root.findall(".//item"):
        title = clean_text(node.findtext("title") or "")
        desc = clean_text(node.findtext("description") or "")
        link = clean_text(node.findtext("link") or "")
        published = clean_text(node.findtext("pubDate") or "")
        text = f"{title} {desc}"
        if keywords and not keyword_hit(text, keywords):
            continue
        items.append(
            {
                "source": source["label"],
                "title": title,
                "body": desc,
                "published": published,
                "url": link,
            }
        )
    return FetchResult(True, f"{len(items)} keyword matches in RSS", items[:limit], utc_now())


def parse_rss_liveblog(source: dict[str, Any], keywords: list[str]) -> FetchResult:
    raw = fetch_url(source["url"], accept="application/rss+xml, application/xml, text/xml")
    root = ET.fromstring(raw)
    title_patterns = source.get("title_patterns") or [source.get("title_pattern", "")]
    title_patterns = [pattern.lower() for pattern in title_patterns if pattern]
    url_contains = source.get("url_contains", "")
    chosen_title = ""
    chosen_url = ""
    for node in root.findall(".//item"):
        title = clean_text(node.findtext("title") or "")
        link = clean_text(node.findtext("link") or "")
        title_ok = any(pattern in title.lower() for pattern in title_patterns)
        url_ok = not url_contains or url_contains in link
        if title_ok and url_ok:
            chosen_title = title
            chosen_url = link
            break
    if not chosen_url:
        raise ValueError(f"No RSS item matched title patterns {title_patterns!r}")

    live_source = dict(source)
    live_source["url"] = chosen_url
    result = parse_liveblog(live_source, keywords)
    if "matching links" in result.status:
        limit = int(source.get("limit", 4))
        fallback_items = []
        for node in root.findall(".//item"):
            title = clean_text(node.findtext("title") or "")
            desc = clean_text(node.findtext("description") or "")
            link = clean_text(node.findtext("link") or "")
            published = clean_text(node.findtext("pubDate") or "")
            haystack = f"{title} {desc} {link}".lower()
            if not any(pattern in haystack for pattern in title_patterns):
                continue
            fallback_items.append(
                {
                    "source": source["label"],
                    "title": title,
                    "body": desc,
                    "published": published,
                    "url": link,
                }
            )
        return FetchResult(
            True,
            f"No timestamped liveblog entries found; showing latest Al Jazeera Iran RSS items after selecting {chosen_title}",
            fallback_items[:limit],
            utc_now(),
        )
    result.status = f"{result.status} from {chosen_title}"
    return result


def parse_html_links(source: dict[str, Any], keywords: list[str]) -> FetchResult:
    raw = fetch_url(source["url"], accept="text/html")
    parser = TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    base = source["url"]
    seen: set[str] = set()
    items = []
    limit = int(source.get("limit", 4))
    for link in parser.links:
        text = link["text"]
        href = urllib.parse.urljoin(base, link["href"])
        if href in seen or not href.startswith(("http://", "https://")):
            continue
        if keywords and not keyword_hit(f"{text} {href}", keywords):
            continue
        seen.add(href)
        items.append(
            {
                "source": source["label"],
                "title": text,
                "body": "",
                "published": "",
                "url": href,
            }
        )
    return FetchResult(True, f"{len(items)} matching links", items[:limit], utc_now())


def parse_liveblog(source: dict[str, Any], keywords: list[str]) -> FetchResult:
    raw = fetch_url(source["url"], accept="text/html")
    parser = TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    lines = [line.strip() for line in parser.text().splitlines() if line.strip()]
    date_re = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}", re.I)
    entries: list[dict[str, Any]] = []
    limit = int(source.get("limit", 4))
    index = 0
    while index < len(lines):
        if not date_re.match(lines[index]):
            index += 1
            continue
        published = lines[index]
        title = lines[index + 1] if index + 1 < len(lines) else "Live update"
        body_parts = []
        index += 2
        while index < len(lines) and not date_re.match(lines[index]):
            if lines[index] not in {"Load More Updates", "Summary", "LIVE"}:
                body_parts.append(lines[index])
            index += 1
        body = clamp_text(" ".join(body_parts))
        combined = f"{title} {body}"
        if not keywords or keyword_hit(combined, keywords):
            entries.append(
                {
                    "source": source["label"],
                    "title": title,
                    "body": body,
                    "published": published,
                    "url": source["url"],
                }
            )
    if not entries:
        return parse_html_links(source, keywords)
    return FetchResult(True, f"{len(entries)} liveblog entries", entries[:limit], utc_now())


def fetch_investing_oil(config: dict[str, Any]) -> dict[str, Any]:
    oil = config["oil"]
    raw = fetch_url(oil["investing_url"], accept="text/html")
    parser = TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    lines = [line.strip() for line in parser.text().splitlines() if line.strip()]
    symbol = oil["symbol"]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "Brent Oil" in line and f"({symbol})" in line
        ),
        -1,
    )
    if header_index < 0:
        raise ValueError(f"Could not find {symbol} on Investing.com page")

    window = lines[header_index : header_index + 90]
    price_index = next(
        (
            index
            for index, line in enumerate(window)
            if re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", line)
        ),
        -1,
    )
    if price_index < 0:
        raise ValueError(f"Could not find {symbol} price on Investing.com page")

    price = parse_float(window[price_index])
    change = None
    change_percent = None
    change_index = next(
        (
            index
            for index, line in enumerate(window[price_index + 1 : price_index + 10], start=price_index + 1)
            if "%" in line
        ),
        -1,
    )
    if change_index >= 0:
        change_line = window[change_index]
        previous_line = window[change_index - 1] if change_index - 1 >= 0 else ""
        pct_match = re.search(r"([-+]?\d+(?:\.\d+)?)%", change_line)
        change_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*\(", change_line) or re.search(
            r"[-+]?\d+(?:\.\d+)?", previous_line
        )
        if pct_match:
            change_percent = parse_float(pct_match.group(1))
        if change_match:
            change = parse_float(change_match.group(1) if change_match.lastindex else change_match.group(0))

    time_line = next((line for line in window if "Real-time Data" in line or "Delayed" in line), "")
    month = ""
    month_index = next((index for index, line in enumerate(lines) if line == "Month"), -1)
    if month_index >= 0 and month_index + 1 < len(lines):
        month = lines[month_index + 1]

    return {
        "ok": True,
        "label": oil["label"],
        "symbol": symbol,
        "price": price,
        "currency": "USD",
        "exchange": "Investing.com derived",
        "change": change,
        "change_percent": change_percent,
        "market_state": time_line or "Investing.com",
        "contract_month": month,
        "as_of": utc_now(),
        "source_url": oil["investing_url"],
    }


def fetch_yahoo_oil(config: dict[str, Any]) -> dict[str, Any]:
    yahoo_symbol = config["oil"].get("fallback_yahoo_symbol", "BZ=F")
    symbol = urllib.parse.quote(yahoo_symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
    raw = fetch_url(url, accept="application/json")
    payload = json.loads(raw.decode("utf-8"))
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    quote = result["indicators"]["quote"][0]
    closes = [value for value in quote.get("close", []) if value is not None]
    timestamps = result.get("timestamp") or []
    last_price = closes[-1] if closes else meta.get("regularMarketPrice")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = None if previous in (None, 0) else last_price - previous
    pct = None if change is None else (change / previous) * 100
    last_ts = timestamps[-1] if timestamps else meta.get("regularMarketTime")
    last_time = (
        dt.datetime.fromtimestamp(last_ts, dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        if last_ts
        else utc_now()
    )
    return {
        "ok": True,
        "label": config["oil"]["label"],
        "symbol": yahoo_symbol,
        "price": last_price,
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName", ""),
        "change": change,
        "change_percent": pct,
        "market_state": meta.get("marketState", ""),
        "as_of": last_time,
        "source_url": f"https://finance.yahoo.com/quote/{urllib.parse.quote(yahoo_symbol, safe='')}",
    }


def fetch_oil(config: dict[str, Any]) -> dict[str, Any]:
    try:
        return fetch_investing_oil(config)
    except Exception as investing_exc:
        fallback = fetch_yahoo_oil(config)
        fallback["symbol"] = config["oil"].get("symbol", fallback["symbol"])
        fallback["status"] = f"Investing.com failed, using Yahoo fallback: {type(investing_exc).__name__}: {investing_exc}"
        return fallback


def oil_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    refresh_seconds = max(float(config.get("oil_refresh_seconds", 1)), 0.5)
    now = time.monotonic()
    cached = OIL_CACHE["value"]
    if cached and now - OIL_CACHE["monotonic"] < refresh_seconds:
        return dict(cached, cache_hit=True)

    with OIL_LOCK:
        now = time.monotonic()
        cached = OIL_CACHE["value"]
        if cached and now - OIL_CACHE["monotonic"] < refresh_seconds:
            return dict(cached, cache_hit=True)
        try:
            oil = fetch_oil(config)
        except Exception as exc:
            oil = {
                "ok": False,
                "label": config["oil"]["label"],
                "symbol": config["oil"].get("symbol", config["oil"].get("fallback_yahoo_symbol", "")),
                "status": f"{type(exc).__name__}: {exc}",
                "as_of": utc_now(),
            }
        oil["cache_hit"] = False
        OIL_CACHE["value"] = oil
        OIL_CACHE["monotonic"] = time.monotonic()
        return oil


def fetch_source(source: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        parser = {
            "truthsocial": parse_truthsocial,
            "rss": parse_rss,
            "rss_liveblog": parse_rss_liveblog,
            "html_links": parse_html_links,
            "liveblog": parse_liveblog,
        }[source["type"]]
        result = parser(source, keywords)
        return {
            "id": source["id"],
            "label": source["label"],
            "type": source["type"],
            "url": source["url"],
            "ok": result.ok,
            "status": result.status,
            "items": result.items,
            "fetched_at": result.fetched_at,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "id": source["id"],
            "label": source["label"],
            "type": source.get("type", ""),
            "url": source.get("url", ""),
            "ok": False,
            "status": f"{type(exc).__name__}: {exc}",
            "items": [],
            "fetched_at": utc_now(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }


def snapshot() -> dict[str, Any]:
    config = load_config()
    item_limit = int(config.get("item_limit", 4))
    sources = [
        fetch_source({**source, "limit": source.get("limit", item_limit)}, config.get("keywords", []))
        for source in config["sources"]
    ]
    return {
        "generated_at": utc_now(),
        "refresh_seconds": config.get("refresh_seconds", 30),
        "oil_refresh_seconds": config.get("oil_refresh_seconds", 1),
        "item_limit": item_limit,
        "keywords": config.get("keywords", []),
        "oil": oil_snapshot(config),
        "sources": sources,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(APP_DIR / "static"), **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith("/api/oil"):
            config = load_config()
            self.send_json(
                {
                    "generated_at": utc_now(),
                    "oil_refresh_seconds": config.get("oil_refresh_seconds", 1),
                    "oil": oil_snapshot(config),
                }
            )
            return
        if self.path.startswith("/api/snapshot"):
            self.send_json(snapshot())
            return
        if self.path == "/health":
            self.send_json({"ok": True, "time": utc_now()})
            return
        super().do_GET()

    def send_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as server:
        print(f"Live monitor running at http://127.0.0.1:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
