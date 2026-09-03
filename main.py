import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests
import trafilatura
from deep_translator import GoogleTranslator
from googlenewsdecoder import gnewsdecoder

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
PLAYER_FEEDS_DIR = DOCS_DIR / "players"
DB_FILE = DATA_DIR / "articles.json"


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_articles():
    try:
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_articles(articles):
    DATA_DIR.mkdir(exist_ok=True)
    DB_FILE.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")


def deaccent(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c))


def normalize(text):
    return re.sub(r"\s+", " ", deaccent(text).lower()).strip()


def aliases(name):
    values = {name.strip(), deaccent(name).strip()}
    if normalize(name) == "alex padilla":
        values.add("Álex Padilla")
    return sorted(x for x in values if x)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")


def player_query(name):
    quoted = [f'"{x}"' for x in aliases(name)]
    return quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")"


def clean_url(url):
    try:
        parts = urlsplit(url)
        params = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            key_l = key.lower()
            if key_l.startswith("utm_") or key_l in {"fbclid", "gclid", "mc_cid", "mc_eid"}:
                continue
            params.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
    except Exception:
        return url


def domain(url):
    try:
        host = urlsplit(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def article_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def cdata(text):
    return "<![CDATA[" + str(text).replace("]]>", "]]]]><![CDATA[>") + "]]>"


def parse_gdelt_date(value):
    if not value:
        return datetime.now(timezone.utc)
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def feed_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(parsed.tm_year, parsed.tm_mon, parsed.tm_mday, parsed.tm_hour, parsed.tm_min, parsed.tm_sec, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def discover_gdelt(player, config):
    if not config["settings"].get("use_gdelt", True):
        return []
    params = {
        "query": player_query(player["name"]),
        "mode": "artlist",
        "maxrecords": config["settings"]["gdelt_results_per_player"],
        "timespan": f'{config["settings"]["max_age_hours"]}h',
        "sort": "datedesc",
        "format": "json",
    }
    try:
        response = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=30, headers={"User-Agent": "MexicanosEnEuropa/1.0"})
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print("  GDELT error:", exc)
        return []
    out = []
    for item in payload.get("articles", []):
        url = clean_url(item.get("url", ""))
        if url:
            out.append({
                "url": url,
                "title": item.get("title", "") or "",
                "source": item.get("domain", "") or domain(url),
                "published": parse_gdelt_date(item.get("seendate")),
                "language": item.get("language", "") or "",
                "country": item.get("sourcecountry", "") or "",
                "via": "GDELT",
            })
    return out


def google_feed_url(query, edition):
    return "https://news.google.com/rss/search?" + f"q={quote_plus(query)}&hl={quote_plus(edition['hl'])}&gl={quote_plus(edition['gl'])}&ceid={quote_plus(edition['ceid'])}"


def decode_google_url(url):
    if "news.google.com" not in url:
        return clean_url(url)
    try:
        result = gnewsdecoder(url, interval=1)
        if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
            return clean_url(result["decoded_url"])
    except Exception:
        pass
    return None


def discover_google(player, config):
    if not config["settings"].get("use_google_news", True):
        return []
    out = []
    query = player_query(player["name"])
    limit = config["settings"]["google_results_per_edition"]
    for edition in config["google_news_editions"]:
        feed = feedparser.parse(google_feed_url(query, edition))
        for entry in list(getattr(feed, "entries", []))[:limit]:
            url = decode_google_url(getattr(entry, "link", ""))
            if not url:
                continue
            source = ""
            try:
                if getattr(entry, "source", None):
                    source = entry.source.get("title", "") or ""
            except Exception:
                pass
            out.append({
                "url": url,
                "title": getattr(entry, "title", "") or "",
                "source": source or domain(url),
                "published": feed_date(entry),
                "language": "",
                "country": edition["label"],
                "via": "Google News",
            })
    return out


def extract_article(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        extracted = trafilatura.extract(downloaded, url=url, output_format="json", with_metadata=True, include_comments=False, include_tables=True, favor_precision=True)
        if not extracted:
            return None
        data = json.loads(extracted)
        body = (data.get("text") or "").strip()
        if not body:
            return None
        return {"title": (data.get("title") or "").strip(), "author": (data.get("author") or "").strip(), "body": body}
    except Exception as exc:
        print("    Extract error:", exc)
        return None


def mentions(text, name):
    text_n = normalize(text)
    return any(normalize(alias) in text_n for alias in aliases(name))


def detected_players(text, players):
    return [{"name": p["name"], "club": p["club"], "group": p["group"]} for p in players if mentions(text, p["name"])]


def merge_existing(article, player, candidate):
    names = {x.get("name") for x in article.setdefault("tracked_players", [])}
    if player["name"] not in names:
        article["tracked_players"].append({"name": player["name"], "club": player["club"], "group": player["group"]})
    if candidate["via"] not in article.setdefault("discovery_sources", []):
        article["discovery_sources"].append(candidate["via"])
    if candidate.get("language") and candidate["language"] not in article.setdefault("source_languages", []):
        article["source_languages"].append(candidate["language"])
    if candidate.get("country") and candidate["country"] not in article.setdefault("source_countries", []):
        article["source_countries"].append(candidate["country"])


def split_chunks(text, max_chars=4000):
    text = str(text or "").strip()
    if not text:
        return []
    chunks, current = [], ""
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = []
        while len(paragraph) > max_chars:
            cut = paragraph.rfind(". ", 0, max_chars)
            if cut < max_chars // 2:
                cut = paragraph.rfind(" ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if paragraph:
            pieces.append(paragraph)
        for piece in pieces:
            addition = piece if not current else "\n\n" + piece
            if len(current) + len(addition) <= max_chars:
                current += addition
            else:
                if current:
                    chunks.append(current.strip())
                current = piece
    if current:
        chunks.append(current.strip())
    return chunks


def translate_text(text, target="es", chunk_size=4000):
    text = str(text or "").strip()
    if not text:
        return text, True
    try:
        translator = GoogleTranslator(source="auto", target=target)
        translated = []
        for chunk in split_chunks(text, chunk_size):
            translated.append(translator.translate(chunk) or chunk)
            time.sleep(0.15)
        return "\n\n".join(translated).strip() or text, True
    except Exception as exc:
        print("    Translation warning:", exc)
        return text, False


def ensure_translations(articles, config):
    settings = config.get("translation", {})
    if not settings.get("enabled", False):
        for article in articles:
            article["rss_title"] = article.get("title", "")
            article["rss_body"] = article.get("body", "")
            article["translation_status"] = "disabled"
        return
    target = settings.get("target_language", "es")
    chunk_size = int(settings.get("chunk_size", 4000))
    for article in articles:
        if article.get("translated_to") == target and article.get("rss_title") and article.get("rss_body") and article.get("translation_status") == "translated":
            continue
        print("  Translating:", (article.get("title") or "")[:80])
        original_title = article.get("original_title") or article.get("title", "")
        original_body = article.get("original_body") or article.get("body", "")
        rss_title, title_ok = translate_text(original_title, target, chunk_size)
        rss_body, body_ok = translate_text(original_body, target, chunk_size)
        article["original_title"] = original_title
        article["original_body"] = original_body
        article["rss_title"] = rss_title
        article["rss_body"] = rss_body
        article["translated_to"] = target
        article["translation_status"] = "translated" if title_ok and body_ok else "fallback_original"


DEDUP_STOPWORDS = {"ante", "bajo", "como", "con", "contra", "desde", "durante", "entre", "hasta", "para", "pero", "por", "que", "sin", "sobre", "tras", "una", "uno", "los", "las", "del", "esta", "este", "sus", "muy", "más"}


def dedupe_tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", normalize(text)) if len(w) > 2 and w not in DEDUP_STOPWORDS}


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def token_overlap(a, b):
    left, right = dedupe_tokens(a), dedupe_tokens(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def article_datetime(article):
    try:
        return datetime.fromisoformat(article.get("published_iso", "")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def tracked_names(article):
    return {normalize(p.get("name", "")) for p in article.get("tracked_players", []) if p.get("name")}


def are_duplicates(a, b, settings):
    if not (tracked_names(a) & tracked_names(b)):
        return False
    hours = abs((article_datetime(a) - article_datetime(b)).total_seconds()) / 3600
    if hours > float(settings.get("max_hours_apart", 48)):
        return False
    title_a = a.get("rss_title") or a.get("title", "")
    title_b = b.get("rss_title") or b.get("title", "")
    body_a = a.get("rss_body") or a.get("body", "")
    body_b = b.get("rss_body") or b.get("body", "")
    title_sim = similarity(title_a, title_b)
    title_words = token_overlap(title_a, title_b)
    lead_chars = int(settings.get("body_lead_characters", 1600))
    body_sim = similarity(body_a[:lead_chars], body_b[:lead_chars])
    return (
        title_sim >= float(settings.get("title_similarity_threshold", 0.72))
        or title_words >= float(settings.get("title_token_overlap_threshold", 0.58))
        or (title_sim >= 0.50 and body_sim >= float(settings.get("body_lead_similarity_threshold", 0.66)))
        or body_sim >= 0.82
    )


def completeness_score(article):
    body = article.get("rss_body") or article.get("body", "")
    title = article.get("rss_title") or article.get("title", "")
    return (
        min(len(body), 25000)
        + min(len(title), 180) * 2
        + (500 if article.get("author") else 0)
        + (250 if article.get("source") else 0)
        + (200 if article.get("published_iso") else 0)
        + (100 if article.get("source_languages") else 0)
        + (150 if article.get("translation_status") == "translated" else 0)
    )


def merge_duplicate_metadata(winner, loser):
    for key in ("discovery_sources", "source_languages", "source_countries"):
        existing = winner.setdefault(key, [])
        for value in loser.get(key, []):
            if value and value not in existing:
                existing.append(value)
    names = {p.get("name") for p in winner.get("tracked_players", [])}
    for player in loser.get("tracked_players", []):
        if player.get("name") not in names:
            winner.setdefault("tracked_players", []).append(player)
            names.add(player.get("name"))
    alternatives = winner.setdefault("alternate_sources", [])
    alt = {"title": loser.get("title", ""), "source": loser.get("source", ""), "url": loser.get("url", ""), "published_iso": loser.get("published_iso", ""), "body_characters": len(loser.get("rss_body") or loser.get("body", ""))}
    if alt["url"] and not any(x.get("url") == alt["url"] for x in alternatives):
        alternatives.append(alt)
    for other in loser.get("alternate_sources", []):
        if other.get("url") and not any(x.get("url") == other.get("url") for x in alternatives):
            alternatives.append(other)
    winner["duplicate_versions_removed"] = len(alternatives)


def smart_dedupe(articles, config):
    settings = config.get("deduplication", {})
    if not settings.get("enabled", True):
        return articles
    kept, removed = [], 0
    for article in sorted(articles, key=lambda x: x.get("published_iso", ""), reverse=True):
        match_index = None
        for index, existing in enumerate(kept):
            if are_duplicates(article, existing, settings):
                match_index = index
                break
        if match_index is None:
            kept.append(article)
            continue
        existing = kept[match_index]
        if completeness_score(article) > completeness_score(existing):
            merge_duplicate_metadata(article, existing)
            kept[match_index] = article
            winner = article
        else:
            merge_duplicate_metadata(existing, article)
            winner = existing
        removed += 1
        print("  Duplicate removed; keeping:", (winner.get("rss_title") or winner.get("title", ""))[:90])
    print(f"Smart duplicate removal: {removed} repeated versions removed.")
    return sorted(kept, key=lambda x: x.get("published_iso", ""), reverse=True)


def rss_xml(items, title, description, site_url, max_items):
    rows = []
    for article in sorted(items, key=lambda x: x.get("published_iso", ""), reverse=True)[:max_items]:
        body = article.get("rss_body") or article.get("body", "")
        base_title = article.get("rss_title") or article.get("title", "")
        source_label = (article.get("source") or source_from_url(article.get("url", "")) or "Fuente desconocida").strip()
        title_text = f"[{source_label}] {base_title}"
        body_html = "<p>" + html.escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        preview = body[:500] + ("…" if len(body) > 500 else "")
        categories = "\n".join(f"      <category>{html.escape(p['name'])}</category>" for p in article.get("tracked_players", []))
        creator = f"      <dc:creator>{cdata(article['author'])}</dc:creator>\n" if article.get("author") else ""
        rows.append(f'''    <item>
      <title>{cdata(title_text)}</title>
      <link>{html.escape(article.get('url',''))}</link>
      <guid isPermaLink="false">{article.get('id','')}</guid>
      <pubDate>{article.get('published_rfc2822','')}</pubDate>
      <source>{cdata(article.get('source',''))}</source>
{creator}      <description>{cdata(preview)}</description>
      <content:encoded>{cdata(body_html)}</content:encoded>
{categories}
    </item>''')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>{cdata(title)}</title>
    <link>{html.escape(site_url)}</link>
    <description>{cdata(description)}</description>
    <lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>
{chr(10).join(rows)}
  </channel>
</rss>'''


def generate_outputs(articles, config):
    DOCS_DIR.mkdir(exist_ok=True)
    PLAYER_FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    max_items = config["settings"]["max_feed_items"]
    site = config["feed"]["site_url"]
    (DOCS_DIR / "feed.xml").write_text(rss_xml(articles, config["feed"]["title"], config["feed"]["description"], site, max_items), encoding="utf-8")
    for player in config["players"]:
        player_articles = [a for a in articles if any(p.get("name") == player["name"] for p in a.get("tracked_players", []))]
        (PLAYER_FEEDS_DIR / f'{slug(player["name"])}.xml').write_text(rss_xml(player_articles, f'{player["name"]} — Mexicanos en Europa', f'Noticias traducidas al español que mencionan a {player["name"]} ({player["club"]}).', site, max_items), encoding="utf-8")
    cards = []
    for article in articles[:200]:
        names = ", ".join(p["name"] for p in article.get("tracked_players", []))
        duplicate_note = f' · {article["duplicate_versions_removed"]} versión(es) repetida(s) descartada(s)' if article.get("duplicate_versions_removed") else ""
        cards.append(f'<article><h2><a href="{html.escape(article.get("url", ""))}" target="_blank">{html.escape(f'[{(article.get("source") or source_from_url(article.get("url", "")) or "Fuente desconocida").strip()}] {article.get("rss_title") or article.get("title", "")}')}</a></h2><p><strong>{html.escape(names)}</strong></p><p>{html.escape(article.get("source", ""))} · {html.escape(article.get("published_display", ""))}{html.escape(duplicate_note)}</p></article>')
    links = "".join(f'<li><a href="players/{slug(p["name"])}.xml">{html.escape(p["name"])}</a> — {html.escape(p["club"])}</li>' for p in config["players"])
    page = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mexicanos en Europa</title></head><body><h1>Mexicanos en Europa</h1><p>Noticias internacionales traducidas automáticamente al español. Las historias repetidas se consolidan y se conserva la versión más completa.</p><p>RSS general: <a href="feed.xml">feed.xml</a></p><h2>Feeds por jugador</h2><ul>' + links + '</ul><h2>Noticias recientes</h2>' + (''.join(cards) if cards else '<p>Aún no hay artículos.</p>') + '</body></html>'
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")


def main():
    config = load_config()
    articles = load_articles()
    existing = {a.get("url"): a for a in articles if a.get("url")}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config["settings"]["max_age_hours"])
    new_count = 0
    print("MEXICANOS EN EUROPA")
    print("Players:", len(config["players"]))
    for player in config["players"]:
        print(f'\nPLAYER: {player["name"]} — {player["club"]}')
        candidates = discover_gdelt(player, config) + discover_google(player, config)
        unique = {}
        for candidate in candidates:
            if candidate["published"] >= cutoff and candidate["url"] not in unique:
                unique[candidate["url"]] = candidate
        print("  Unique recent candidates:", len(unique))
        for candidate in unique.values():
            url = candidate["url"]
            if url in existing:
                merge_existing(existing[url], player, candidate)
                continue
            print("  Fetching:", candidate.get("title", "")[:90])
            extracted = extract_article(url)
            if not extracted or len(extracted["body"]) < config["settings"]["minimum_body_characters"]:
                print("    Skipped: body unavailable/too short")
                time.sleep(config["settings"]["delay_between_articles_seconds"])
                continue
            combined = (extracted.get("title") or "") + "\n" + extracted["body"]
            if not mentions(combined, player["name"]):
                print("    Skipped: player name not in extracted page")
                time.sleep(config["settings"]["delay_between_articles_seconds"])
                continue
            tracked = detected_players(combined, config["players"]) or [{"name": player["name"], "club": player["club"], "group": player["group"]}]
            pub = candidate["published"]
            article = {
                "id": article_id(url), "title": extracted.get("title") or candidate.get("title") or url,
                "source": candidate.get("source") or domain(url), "author": extracted.get("author", ""), "url": url,
                "published_iso": pub.isoformat(), "published_rfc2822": format_datetime(pub), "published_display": pub.strftime("%Y-%m-%d %H:%M UTC"),
                "body": extracted["body"], "tracked_players": tracked,
                "source_languages": [candidate["language"]] if candidate.get("language") else [],
                "source_countries": [candidate["country"]] if candidate.get("country") else [],
                "discovery_sources": [candidate["via"]], "collected_iso": datetime.now(timezone.utc).isoformat(),
            }
            articles.append(article)
            existing[url] = article
            new_count += 1
            time.sleep(config["settings"]["delay_between_articles_seconds"])
    articles = sorted(articles, key=lambda a: a.get("published_iso", ""), reverse=True)
    ensure_translations(articles, config)
    articles = smart_dedupe(articles, config)
    articles = articles[:config["settings"]["max_stored_articles"]]
    save_articles(articles)
    generate_outputs(articles, config)
    print("\nDONE")
    print("New articles found:", new_count)
    print("Unique stories stored:", len(articles))
    print("RSS: docs/feed.xml")


if __name__ == "__main__":
    main()
