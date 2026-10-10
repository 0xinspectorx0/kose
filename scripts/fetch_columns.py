#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kose — Günlük Köşe Yazısı Toplayıcı
==================================
Türk gazetelerinin yazar (köşe yazarı) sayfalarından ve RSS akışlarından
günün köşe yazılarını çeker; sonuçları `data/daily.json` olarak kaydeder.

Çalışma prensibi:
  1. Her kaynak için yazarın sayfa arşivini (listing) indirir.
  2. Arşivden makale bağlantılarını ayıklar (siteye özel regex ile).
  3. Her makale sayfasını indirip başlık / yazar / tarih / gövde metnini çıkarır.
  4. RSS kaynakları (Blogger / WordPress) için akışı ayrıştırır.
  5. Her şeyi tek bir JSON'da birleştirir: data/daily.json

GitHub Actions (.github/workflows/fetch-columns.yml) tarafından her gün
sabah 07:00 (TSİ) otomatik çalıştırılır; elle de tetiklenebilir:

    python scripts/fetch_columns.py
    python scripts/fetch_columns.py --out /tmp/test.json --max-per-source 1

Not: Siteler çok az sayıda sayfa isteği alır (kaynak başına günde birkaç sayfa,
istekler arası gecikme ile). Yazar haklarına saygı çerçevesinde, içerik
yalnızca bu kişisel okuma uygulamasının gösterimi için derlenir.
"""

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

TR_TZ = timezone(timedelta(hours=3))  # Türkiye saati (UTC+3)
USER_AGENT = "kose-kosebot/1.0 (+https://github.com/0xinspectorx0/kose; gunluk kose yazisi toplayici)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,*;q=0.8",
}
TIMEOUT = 25
REQUEST_DELAY = 1.2  # istekler arası nazik gecikme (saniye)
MIN_TITLE_LEN = 3  # çok kısa başlıklar (örn. "Esra") geçerlidir; kalite kontrolü gövde+link deseniyle sağlanır

TURKISH_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

# Gürültü: sayfa gövdesindeki, yazıya ait olmayan kısa kırıntılar (filtrelenir)
NOISE_FRAGMENTS = [
    "Yazarın Tüm Yazıları",
    "Tüm yazıları için tıklayın",
    "Tüm Yazıları için tıklayın",
    "Köşe Yazarları",
    "Yorum Yaz",
    "İlgili Haberler",
    "Abone Ol",
    "Bizi Takip Edin",
    "Bizi takibe alın",
    "Diğer Yazıları",
    "Önceki Yazı",
    "Sonraki Yazı",
    "Haberi Paylaş",
    "Linki kopyala",
]

# ---------------------------------------------------------------------------
# Kaynak tanımları (düzenlemesi kolay — yeni gazete/yazar eklemek için buraya)
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "key": "hurriyet",
        "source": "Hürriyet",
        "author": "Ahmet Hakan",
        "category": "Gündem",
        "listing": "https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/",
        "link_pattern": r"hurriyet\.com\.tr/yazarlar/ahmet-hakan/[a-z0-9-]+-\d+/?$",
    },
    {
        "key": "hurriyet",
        "source": "Hürriyet",
        "author": "Ertuğrul Özkök",
        "category": "Kültür-Sanat",
        "listing": "https://www.hurriyet.com.tr/yazarlar/ertugrul-ozkok/",
        "link_pattern": r"hurriyet\.com\.tr/yazarlar/ertugrul-ozkok/[a-z0-9-]+-\d+/?$",
    },
    {
        "key": "sozcu",
        "source": "Sözcü",
        "author": "Yılmaz Özdil",
        "category": "Gündem",
        "listing": "https://www.sozcu.com.tr/yazarlar/yilmaz-ozdil/",
        "link_pattern": r"sozcu\.com\.tr/.+-[p]?\d{6,7}/?$",
    },
    {
        "key": "altayli",
        "source": "Fatih Altaylı",
        "author": "Fatih Altaylı",
        "category": "Gündem",
        "listing": "https://fatihaltayli.com.tr/yazilar/fatih-altayli",
        "link_pattern": r"fatihaltayli\.com\.tr/yazarlar/fatih-altayli/\d{4}-\d{2}-\d{2}/.+",
    },
    {
        "key": "livaneli",
        "source": "Livaneli.gen.tr",
        "author": "Zülfü Livaneli",
        "category": "Kültür-Sanat",
        "listing": "https://www.livaneli.gen.tr/category/kose-yazilari/",
        "link_pattern": r"livaneli\.gen\.tr/\d{4}/\d{2}/.+/?$",
    },
]

FEED_SOURCES = [
    {
        "key": "mahfiegilmez",
        "source": "Kendime Yazılar",
        "author": "Mahfi Eğilmez",
        "category": "Ekonomi",
        "feed": "https://www.mahfiegilmez.com/feeds/posts/default?max-results=5",
    },
    {
        "key": "yetkinreport",
        "source": "YetkinReport",
        "author": "Murat Yetkin",
        "category": "Gündem",
        "feed": "https://yetkinreport.com/author/muratmyetkin/feed/",
    },
]

# Makale gövdesi için aday konteyner seçiciler (öncelik sırasıyla)
BODY_SELECTORS = [
    "article",
    "[itemprop=articleBody]",
    ".article-body",
    ".articleBody",
    ".entry-content",
    ".post-content",
    ".content-body",
    ".haber-metni",
    ".haberDetay",
    ".haber-detay",
    "#article-body",
    ".yazi",
    ".yazi-icerigi",
    ".column-content",
    "main",
    "[role=main]",
]


def log(msg):
    print(f"[kose] {msg}", flush=True)


_session = requests.Session()


def fetch(url):
    """GET isteği atar; içerik döndürür, hata olursa None."""
    try:
        time.sleep(REQUEST_DELAY)
        r = _session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            log(f"    ! HTTP {r.status_code} <- {url}")
            return None
        if r.encoding is None or r.encoding.lower() in ("iso-8859-1",):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:  # ağ hatası, zaman aşımı vb.
        log(f"    ! {type(e).__name__}: {e} <- {url}")
        return None


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def clean_title(t):
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    t = t.split(" | ")[0].strip()
    t = re.sub(
        r"\s+[\-–]\s+(Hürriyet|Sözcü|Sözcü Gazetesi|Gazete|Haberler|Son Dakika|"
        r"Milliyet|Sabah|Cumhuriyet|Vatan|Yeni Şafak|Oksijen|YetkinReport|"
        r"Fatih Altaylı|Livaneli\.gen\.tr|kose)\s*$",
        "",
        t,
    )
    return t


def is_noise(text):
    return any(n in text for n in NOISE_FRAGMENTS)


def format_date_tr(d):
    """datetime -> 'Bugün 08:30' / 'Dün 21:15' / '10 Ekim 2026'"""
    now = datetime.now(TR_TZ)
    if d.date() == now.date():
        return f"Bugün {d.strftime('%H:%M')}"
    if d.date() == (now - timedelta(days=1)).date():
        return f"Dün {d.strftime('%H:%M')}"
    return f"{d.day} {TURKISH_MONTHS[d.month - 1]} {d.year}"


def parse_date_any(value):
    """ISO / RFC822 tarih dizgisini TR saatine çevirir."""
    if not value:
        return None
    value = value.strip()
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=TR_TZ)
        return d.astimezone(TR_TZ)
    except Exception:
        pass
    try:
        d = parsedate_to_datetime(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=TR_TZ)
        return d.astimezone(TR_TZ)
    except Exception:
        pass
    m = re.search(
        r"(\d{1,2})\s+(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|"
        r"Eylül|Ekim|Kasım|Aralık)\s+(\d{4})",
        value,
    )
    if m:
        return datetime(
            int(m.group(3)), TURKISH_MONTHS.index(m.group(2)) + 1, int(m.group(1)),
            tzinfo=TR_TZ,
        )
    return None


def extract_blocks(soup):
    """Sayfadaki makale gövdesini (p + h2/h3) blok listesi olarak çıkarır."""
    candidates = []
    for sel in BODY_SELECTORS:
        for el in soup.select(sel):
            if el not in candidates:
                candidates.append(el)
    if not candidates and soup.body is not None:
        candidates = [soup.body]

    best, best_score = None, -1
    for el in candidates:
        score = sum(len(p.get_text(strip=True)) for p in el.find_all("p"))
        if score > best_score:
            best, best_score = el, score
    if best is None:
        return []

    blocks = []
    for child in best.find_all(["p", "h2", "h3"]):
        if child.find_parent("p") is not None:
            continue
        text = re.sub(r"\s+", " ", child.get_text(" ", strip=True))
        if len(text) < 30 or is_noise(text):
            continue
        tag = "h3" if child.name in ("h2", "h3") else "p"
        blocks.append((tag, text))
    return blocks


def extract_date_from_soup(soup, fallback_text=""):
    for sel in (
        'time[datetime]',
        'meta[property="article:published_time"]',
        'meta[name="date"]',
        'meta[name="publishdate"]',
        'meta[itemprop="datePublished"]',
    ):
        el = soup.select_one(sel)
        if el is None:
            continue
        value = el.get("datetime") or el.get("content")
        d = parse_date_any(value)
        if d:
            return d
    d = parse_date_any(fallback_text)
    return d or datetime.now(TR_TZ)


def extract_article_links(html, listing_url, pattern, limit):
    """Arşiv sayfasından makale URL'lerini ayıklar (sırayı korur, tekilleştirir)."""
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(pattern)
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(listing_url, a["href"].strip())
        if not rx.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
        if len(links) >= limit:
            break
    return links


def build_record(cfg, title, url, blocks, date_dt, author=None):
    """Uygulamanın beklediği makale kaydını üretir."""
    texts = [t for _, t in blocks]
    plain = " ".join(texts)
    words = len(plain.split())
    read_time = max(1, round(words / 200))
    snippet = (plain[:180].rstrip() + "…") if len(plain) > 180 else plain

    parts = []
    for tag, text in blocks:
        safe = html_lib.escape(text, quote=False)
        if tag == "h3":
            parts.append(
                f'<h3 class="font-serif font-semibold text-lg text-ink-900 pt-1">{safe}</h3>'
            )
        else:
            parts.append(f"<p>{safe}</p>")

    author_name = (author or cfg["author"]).strip()
    return {
        "id": f"{cfg['key']}-{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}",
        "author": author_name,
        "source": cfg["source"],
        "title": title,
        "url": url,
        "date": format_date_tr(date_dt),
        "category": cfg["category"],
        "readTime": f"{read_time} dk",
        "snippet": snippet,
        "fullContent": "\n".join(parts),
        "avatar": (
            "https://ui-avatars.com/api/?name="
            + quote(author_name)
            + "&background=2E384D&color=fff&size=128&bold=true"
        ),
        "isLive": True,
    }


# ---------------------------------------------------------------------------
# HTML makale sayfasından çekim
# ---------------------------------------------------------------------------
def parse_html_article(url, cfg):
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    # Başlık adayları (öncelik sırasıyla); en az 8 karakterli ilk aday seçilir
    candidates = []
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        candidates.append(og["content"])
    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text(" ", strip=True))
    if soup.title:
        candidates.append(soup.title.get_text(" ", strip=True))
    author = cfg["author"]
    am = soup.select_one('meta[name="author"]')
    if am and am.get("content") and am["content"].strip():
        author = am["content"].strip()

    title = ""
    for cand in candidates:
        cand = clean_title(cand)
        # "Başlık - Yazar Adı" kalıbındaki başlık sonundan yazar adını at
        cand = re.sub(r"\s+-\s+" + re.escape(author) + r"\s*$", "", cand).strip()
        if len(cand) >= MIN_TITLE_LEN:
            title = cand
            break
    if not title:
        log(f"    ! başlık bulunamadı <- {url}")
        return None

    blocks = extract_blocks(soup)
    if len(blocks) < 2:
        log(f"    ! gövde bulunamadı <- {url}")
        return None

    date_dt = extract_date_from_soup(soup)
    return build_record(cfg, title, url, blocks, date_dt, author)


# ---------------------------------------------------------------------------
# RSS / Atom akışından çekim
# ---------------------------------------------------------------------------
def _local_name(tag):
    return tag.split("}")[-1]


def _child_text(item, *names):
    for c in item:
        if _local_name(c.tag) in names:
            return (c.text or "").strip()
    return ""


def _child_link(item):
    for c in item:
        if _local_name(c.tag) == "link":
            if c.get("href"):  # Atom
                return c.get("href").strip()
            return (c.text or "").strip()  # RSS
    return ""


def html_to_blocks(content_html):
    """RSS içeriğindeki HTML'den blok listesi üretir."""
    soup = BeautifulSoup(content_html or "", "html.parser")
    blocks = []
    for p in soup.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(text) >= 30 and not is_noise(text):
            blocks.append(("p", text))
    if not blocks:
        for chunk in re.split(r"\n\s*\n", (soup.get_text("\n", strip=True) or "")):
            text = re.sub(r"\s+", " ", chunk).strip()
            if len(text) >= 30 and not is_noise(text):
                blocks.append(("p", text))
    return blocks


def parse_feed(cfg, limit):
    xml = fetch(cfg["feed"])
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        log(f"    ! RSS ayrıştırma hatası: {e}")
        return []

    records = []
    for item in root.iter():
        if _local_name(item.tag) not in ("item", "entry"):
            continue
        title = clean_title(_child_text(item, "title"))
        url = _child_link(item)
        if len(title) < MIN_TITLE_LEN or not url:
            continue
        content = _child_text(item, "encoded", "content", "description", "summary")
        blocks = html_to_blocks(content)
        if not blocks:
            continue
        date_dt = (
            parse_date_any(_child_text(item, "pubDate", "published", "updated", "date"))
            or datetime.now(TR_TZ)
        )
        records.append(build_record(cfg, title, url, blocks, date_dt))
        if len(records) >= limit:
            break
    return records


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Günlük köşe yazısı toplayıcı")
    ap.add_argument("--out", default="data/daily.json", help="Çıktı JSON dosyası")
    ap.add_argument("--max-per-source", type=int, default=2, help="Kaynak başına makale")
    args = ap.parse_args()

    records = []

    for cfg in SOURCES:
        log(f">> {cfg['source']} — {cfg['author']}")
        listing_html = fetch(cfg["listing"])
        if not listing_html:
            continue
        links = extract_article_links(
            listing_html, cfg["listing"], cfg["link_pattern"], args.max_per_source
        )
        log(f"   {len(links)} yazı bulundu")
        for url in links:
            rec = parse_html_article(url, cfg)
            if rec:
                log(f"   + {rec['title'][:60]}")
                records.append(rec)

    for cfg in FEED_SOURCES:
        log(f">> {cfg['source']} — {cfg['author']} (RSS)")
        feed_records = parse_feed(cfg, args.max_per_source)
        log(f"   {len(feed_records)} yazı bulundu")
        for rec in feed_records:
            log(f"   + {rec['title'][:60]}")
            records.append(rec)

    # Başlığa göre tekilleştir (ilk görülen kazanır)
    seen, uniq = set(), []
    for r in records:
        key = r["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    if not uniq:
        log("UYARI: Hiç yazı bulunamadı — mevcut daily.json korunuyor.")
        return 0

    now = datetime.now(TR_TZ)
    payload = {
        "fetchedAt": now.astimezone(timezone.utc).isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "count": len(uniq),
        "articles": uniq,
    }
    outdir = os.path.dirname(args.out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"OK: {len(uniq)} yazı yazıldı -> {args.out} ({now.strftime('%Y-%m-%d %H:%M')} TSİ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
