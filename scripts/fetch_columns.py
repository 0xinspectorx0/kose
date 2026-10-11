#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kose — Günlük Köşe Yazısı Toplayıcı (v2: tüm aktif gazeteler)
=============================================================
Piyasada aktif Türk gazetelerinin köşe yazarlarını OTOMATİK keşfeder ve
günün köşe yazılarını çeker:

  1. Keşif (discovery): Her gazetenin yazarlar dizininden TÜM aktif köşe
     yazarları çıkarılır -> data/writers.json
  2. Günlük çekim: Her gazetenin "bugünün yazıları" sayfasından makale
     bağlantıları alınır, her makale sayfasından tam metin çekilir
     -> data/daily.json
  3. RSS kişisel kaynaklar (Blogger / WordPress) eklenir.

Çalışma:
    python scripts/fetch_columns.py                 # her şeyi çek
    python scripts/fetch_columns.py --discover-only # sadece yazar listesi
    python scripts/fetch_columns.py --max-per-paper 10

GitHub Actions (.github/workflows/fetch-columns.yml) her gün 07:00 TSİ'de
otomatik çalıştırır. İstekler nazik tempodadır (aralarda gecikme vardır).
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
from urllib.parse import quote, urljoin, urlparse

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
MIN_TITLE_LEN = 3  # çok kısa başlıklar (örn. "Esra") geçerlidir

TURKISH_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

# Sayfa gövdesindeki, yazıya ait olmayan kısa kırıntılar (filtrelenir)
NOISE_FRAGMENTS = [
    "Yazarın Tüm Yazıları", "Tüm Yazıları", "Tüm yazıları için tıklayın",
    "TÜM YAZILARI", "Köşe Yazarları", "Yorum Yaz", "İlgili Haberler",
    "Abone Ol", "Bizi Takip Edin", "Bizi takibe alın", "Diğer Yazıları",
    "Önceki Yazı", "Sonraki Yazı", "Haberi Paylaş", "Linki kopyala",
    "Son Dakika", "Tüm Yazarlar", "Yazarlar",
]

# Makale gövdesi için aday konteynerler (bs4 find_all kwargs; öncelik sırasıyla)
# Not: CSS select() kullanılmaz — soupsieve sürüm uyumsuzluklarına karşı
# bs4'in native find/find_all eşleşmesi tercih edilir.
BODY_SELECTORS = [
    {"name": "article"},
    {"attrs": {"itemprop": "articleBody"}},
    {"class_": "article-body"},
    {"class_": "articleBody"},
    {"class_": "entry-content"},
    {"class_": "post-content"},
    {"class_": "content-body"},
    {"class_": "haber-metni"},
    {"class_": "haberDetay"},
    {"class_": "haber-detay"},
    {"attrs": {"id": "article-body"}},
    {"class_": "yazi"},
    {"class_": "yazi-icerigi"},
    {"class_": "column-content"},
    {"name": "main"},
    {"attrs": {"role": "main"}},
]

# Yazar adı için meta attribute eşleşmeleri, itemprop ve class isimleri
AUTHOR_META_KEYS = ("author", "article:author")
AUTHOR_ITEMPROP = "author"
AUTHOR_CLASS_NAMES = [
    "author", "yazar", "yazar-adi", "yazarAdi",
    "article-author", "byline", "author-name",
]

# ---------------------------------------------------------------------------
# Aktif gazeteler (piyasadaki tüm büyük ulusal gazeteler + güçlü dijital)
# Her gazete için: bugünün yazıları dizini, tüm yazarlar dizini (opsiyonel),
# makale bağlantı deseni, yazar bağlantı deseni.
# Desenler URL'lere regex ile uygulanır; eşleşmeyenler zarifçe atlanır.
# ---------------------------------------------------------------------------
NEWSPAPERS = [
    {
        "key": "hurriyet", "name": "Hürriyet", "category": "Gündem", "mode": "today",
        "today": "https://www.hurriyet.com.tr/yazarlar/",
        "roster": "https://www.hurriyet.com.tr/yazarlar/tum-yazarlar/",
        "article_pattern": r"hurriyet\.com\.tr/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+/?$",
        "author_pattern": r"hurriyet\.com\.tr/yazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["tum-yazarlar", "internet-yazilari", "bugun-yazanlar", "gazete", "spor", "arsiv", "konuk-yazarlar"],
    },
    {
        "key": "sozcu", "name": "Sözcü", "category": "Gündem", "mode": "today",
        "today": "https://www.sozcu.com.tr/yazarlar/",
        "roster": None,
        "article_pattern": r"sozcu\.com\.tr/(?:[a-z0-9-]+-p\d+|\d{4}/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+)/?$",
        "author_pattern": None,
    },
    {
        "key": "milliyet", "name": "Milliyet", "category": "Gündem", "mode": "today",
        "today": "https://www.milliyet.com.tr/yazarlar/",
        "roster": "https://www.milliyet.com.tr/yazarlar/gazete-yazarlari/",
        "article_pattern": r"milliyet\.com\.tr/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+/?$",
        "author_pattern": r"milliyet\.com\.tr/yazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["gazete-yazarlari", "spor-yazarlari", "ege-yazarlari", "cumartesi-yazarlari", "pazar-yazarlari", "yazarlar"],
    },
    {
        "key": "sabah", "name": "Sabah", "category": "Gündem", "mode": "today",
        "today": "https://www.sabah.com.tr/yazarlar",
        "roster": None,
        "article_pattern": r"sabah\.com\.tr/yazarlar/[a-z0-9-]+/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/?$",
        "author_pattern": r"sabah\.com\.tr/yazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["perspektif", "spor", "gunluk-yazarlar", "arsiv", "pazaryazarlar"],
    },
    {
        "key": "cumhuriyet", "name": "Cumhuriyet", "category": "Gündem", "mode": "today",
        "today": "https://www.cumhuriyet.com.tr/gunun-kose-yazilari",
        "roster": "https://www.cumhuriyet.com.tr/yazarlar",
        "article_pattern": r"cumhuriyet\.com\.tr/(?:yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+|koseyazisi/\d+)",
        "author_pattern": r"cumhuriyet\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "yenisafak", "name": "Yeni Şafak", "category": "Gündem", "mode": "today",
        "today": "https://www.yenisafak.com/yazarlar/bugun-yazanlar",
        "roster": "https://www.yenisafak.com/yazarlar/tum-yazarlar",
        "article_pattern": r"yenisafak\.com/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+",
        "author_pattern": r"yenisafak\.com/yazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["bugun-yazanlar", "tum-yazarlar", "gazete", "spor", "arsiv"],
    },
    {
        "key": "karar", "name": "Karar", "category": "Gündem", "mode": "today",
        "today": "https://www.karar.com/yazarlar",
        "roster": None,
        "article_pattern": r"karar\.com/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+",
        "author_pattern": r"karar\.com/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "birgun", "name": "BirGün", "category": "Gündem", "mode": "today",
        "today": "https://www.birgun.net/yazarlar",
        "roster": None,
        "article_pattern": r"birgun\.net/makale/[a-z0-9-]+-\d+",
        "author_pattern": r"birgun\.net/profil/[a-z0-9-]+-\d+",
    },
    {
        "key": "haberturk", "name": "Habertürk", "category": "Gündem", "mode": "today",
        "today": "https://www.haberturk.com/htyazarlar",
        "roster": "https://www.haberturk.com/htyazarlar/arsiv",
        "article_pattern": r"haberturk\.com/ozel-icerikler/[a-z0-9-]+/\d+-[a-z0-9-]+/?$",
        "author_pattern": r"haberturk\.com/htyazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["arsiv"],
    },
    {
        "key": "aksam", "name": "Akşam", "category": "Gündem", "mode": "today",
        "today": "https://www.aksam.com.tr/yazarlar/",
        "roster": None,
        "article_pattern": r"aksam\.com\.tr/yazarlar/[a-z0-9-]+/[a-z0-9-]+/haber-\d+",
        "author_pattern": r"aksam\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "takvim", "name": "Takvim", "category": "Gündem", "mode": "today",
        "today": "https://www.takvim.com.tr/yazarlar",
        "roster": None,
        "article_pattern": r"takvim\.com\.tr/yazarlar/[a-z0-9-]+/(?:\d{4}/\d{2}/\d{2}/[a-z0-9-]+|[a-z0-9-]+-\d+)",
        "author_pattern": r"takvim\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "posta", "name": "Posta", "category": "Gündem", "mode": "today",
        "today": "https://www.posta.com.tr/yazarlar/",
        "roster": "https://www.posta.com.tr/arsiv-yazarlari/",
        "article_pattern": r"posta\.com\.tr/yazarlar/[a-z0-9-]+/[a-z0-9-]+-\d+",
        "author_pattern": r"posta\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "yeniasir", "name": "Yeni Asır", "category": "Gündem", "mode": "today",
        "today": "https://www.yeniasir.com.tr/yazarlar",
        "roster": "https://www.yeniasir.com.tr/yazarlar/arsiv",
        "article_pattern": r"yeniasir\.com\.tr/yazarlar/[a-z0-9_-]+/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/?$",
        "author_pattern": r"yeniasir\.com\.tr/yazar-tum-yazilar/[a-z0-9_-]+/?$",
    },
    {
        "key": "star", "name": "Star", "category": "Gündem", "mode": "today",
        "today": "https://www.star.com.tr/yazarlar/",
        "roster": None,
        "article_pattern": r"star\.com\.tr/yazar/[a-z0-9-]+-yazi-\d+/?$",
        "author_pattern": r"star\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "turkiye", "name": "Türkiye Gazetesi", "category": "Gündem", "mode": "today",
        "today": "https://www.turkiyegazetesi.com.tr/yazarlar",
        "roster": None,
        "article_pattern": r"turkiyegazetesi\.com\.tr/kose-yazilari/[a-z0-9-]+/[a-z0-9-]+-\d+",
        "author_pattern": r"turkiyegazetesi\.com\.tr/yazarlar/[a-z0-9-]+/?$",
    },
    {
        "key": "yenicag", "name": "Yeniçağ", "category": "Gündem", "mode": "today",
        "today": "https://www.yenicaggazetesi.com.tr/yazarlar",
        "roster": None,
        "article_pattern": r"yenicagazetesi\.com\.tr/[a-z0-9-]+-\d+y\.htm",
        "author_pattern": r"yenicagazetesi\.com\.tr/[a-z0-9-]+-\d+y\.htm",
    },
    {
        "key": "milligazete", "name": "Milli Gazete", "category": "Gündem", "mode": "authors",
        "today": "https://www.milligazete.com.tr/yazarlar",
        "roster": None,
        # yazar sayfaları kökte kısa slug: /abdulaziz-kiransal
        "author_pattern": r"milligazete\.com\.tr/[a-z0-9-]+/?$",
        "author_denylist": ["yazarlar", "kunye", "gizlilik-sozlesmesi", "iletisim", "reklam", "haberler", "etiket", "kategori", "sayfa", "arama", "ara", "yazar-dinle"],
        # yazar sayfasındaki makale bağlantıları: kökte uzun slug
        "article_pattern": r"milligazete\.com\.tr/[a-z0-9-]{10,}/?$",
        "article_denylist": ["yazarlar", "kunye", "gizlilik-sozlesmesi", "iletisim", "reklam", "haberler", "etiket", "kategori", "sayfa", "arama", "ara", "yazar-dinle"],
    },
    {
        "key": "t24", "name": "T24", "category": "Gündem", "mode": "authors",
        "today": "https://t24.com.tr/son-yazilar",
        "roster": "https://t24.com.tr/yazar/arsiv-yazarlari",
        "author_pattern": r"t24\.com\.tr/yazarlar/[a-z0-9-]+/?$",
        "author_denylist": ["arsiv-yazarlari", "gorus"],
        "article_pattern": r"t24\.com\.tr/(?:yazar|konuk-yazar)/[a-z0-9-]+/[a-z0-9-]+/?$",
    },
    {
        "key": "duvar", "name": "Gazete Duvar", "category": "Gündem", "mode": "today",
        "today": "https://www.gazeteduvar.com.tr/yazarlar",
        "roster": None,
        "article_pattern": r"gazeteduvar\.com\.tr/[a-z0-9-]{10,}/?$",
        "article_denylist": ["yazarlar", "kunye-sayfasi", "sayfa", "reklam", "hakkimizda", "iletisim", "arsiv", "etiket", "kategori", "arama"],
        "author_pattern": r"gazeteduvar\.com\.tr/yazar/[a-z0-9-]+/?$",
    },
    {
        "key": "diken", "name": "Diken", "category": "Gündem", "mode": "today",
        "today": "https://www.diken.com.tr/kategori/agora/",
        "roster": None,
        "article_pattern": r"diken\.com\.tr/[a-z0-9-]{10,}/?$",
        "article_denylist": ["kategori", "etiket", "sayfa", "kunye", "arsiv", "yazarlar", "arama", "iletisim"],
        "author_pattern": r"diken\.com\.tr/yazar/[a-z0-9-]+/?$",
    },
]

# Kişisel köşe siteleri (yazar belli, sayfa yapısı sabit)
PERSONAL_SOURCES = [
    {
        "key": "altayli", "name": "Fatih Altaylı", "category": "Gündem",
        "author": "Fatih Altaylı",
        "listing": "https://fatihaltayli.com.tr/yazilar/fatih-altayli",
        "article_pattern": r"fatihaltayli\.com\.tr/yazarlar/fatih-altayli/\d{4}-\d{2}-\d{2}/.+",
    },
    {
        "key": "livaneli", "name": "Livaneli.gen.tr", "category": "Kültür-Sanat",
        "author": "Zülfü Livaneli",
        "listing": "https://www.livaneli.gen.tr/category/kose-yazilari/",
        "article_pattern": r"livaneli\.gen\.tr/\d{4}/\d{2}/.+/?$",
    },
]

# RSS kaynakları (Blogger / WordPress)
FEED_SOURCES = [
    {
        "key": "mahfiegilmez", "name": "Kendime Yazılar", "category": "Ekonomi",
        "author": "Mahfi Eğilmez",
        "feed": "https://www.mahfiegilmez.com/feeds/posts/default?max-results=5",
    },
    {
        "key": "yetkinreport", "name": "YetkinReport", "category": "Gündem",
        "author": "Murat Yetkin",
        "feed": "https://yetkinreport.com/author/muratmyetkin/feed/",
    },
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
    except Exception as e:
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
        r"Fatih Altaylı|Livaneli\.gen\.tr|kose|T24|Star|Akşam|Takvim|Posta)\s*$",
        "",
        t,
    )
    return t


def clean_author_name(t):
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(Tüm Yazıları|TÜM YAZILARI|Tüm yazıları)\s*", "", t).strip()
    t = t.rstrip("›»").strip()
    return t


def is_noise(text):
    return any(n in text for n in NOISE_FRAGMENTS)


def format_date_tr(d):
    now = datetime.now(TR_TZ)
    if d.date() == now.date():
        return f"Bugün {d.strftime('%H:%M')}"
    if d.date() == (now - timedelta(days=1)).date():
        return f"Dün {d.strftime('%H:%M')}"
    return f"{d.day} {TURKISH_MONTHS[d.month - 1]} {d.year}"


def parse_date_any(value):
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


def _path_of(url):
    return urlparse(url).path.strip("/").lower()


def _in_denylist(url, denylist):
    path = _path_of(url)
    if not denylist:
        return False
    first = path.split("/")[0] if path else ""
    return first in denylist or path in denylist


def extract_links(html, base_url, pattern, denylist=None, limit=None):
    """Sayfadaki bağlantıları desene göre ayıklar (sırayı korur, tekilleştirir)."""
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(pattern)
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if not rx.search(href):
            continue
        if href in seen or _in_denylist(href, denylist):
            continue
        seen.add(href)
        links.append(href)
        if limit and len(links) >= limit:
            break
    return links


def extract_named_links(html, base_url, pattern, denylist=None, limit=None):
    """Desene uyan bağlantılardan (isim, url) çiftleri çıkarır."""
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(pattern)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if not rx.search(href):
            continue
        if href in seen or _in_denylist(href, denylist):
            continue
        name = clean_author_name(a.get_text(" ", strip=True))
        if not name and a.get("title"):
            name = clean_author_name(a["title"])
        if not name:
            img = a.find("img")
            if img and img.get("alt"):
                name = clean_author_name(img["alt"])
        if len(name) < 2 or len(name) > 40 or not re.search(r"[a-zA-ZçÇğĞıİöÖşŞüÜ]", name):
            continue
        if is_noise(name):
            continue
        seen.add(href)
        out.append({"name": name, "url": href})
        if limit and len(out) >= limit:
            break
    return out


def extract_blocks(soup):
    """Sayfadaki makale gövdesini (p + h2/h3) blok listesi olarak çıkarır."""
    candidates = []
    for spec in BODY_SELECTORS:
        for el in soup.find_all(**spec):
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


def extract_date_from_soup(soup):
    for el in soup.find_all("meta"):
        key = (el.get("name") or el.get("property") or el.get("itemprop") or "").lower()
        if key in ("date", "publishdate", "article:published_time", "datepublished"):
            d = parse_date_any(el.get("content") or el.get("datetime"))
            if d:
                return d
    for el in soup.find_all("time"):
        d = parse_date_any(el.get("datetime"))
        if d:
            return d
    return datetime.now(TR_TZ)


def extract_author_from_soup(soup):
    for el in soup.find_all("meta"):
        key = (el.get("name") or el.get("property") or "").lower()
        if key in AUTHOR_META_KEYS:
            val = el.get("content")
            if val and 2 <= len(val) <= 60:
                return clean_author_name(val)
    el = soup.find(attrs={"itemprop": AUTHOR_ITEMPROP})
    if el is not None:
        val = el.get("content") or el.get_text(" ", strip=True)
        if val and 2 <= len(val) <= 60:
            return clean_author_name(val)
    for cls in AUTHOR_CLASS_NAMES:
        el = soup.find(class_=cls)
        if el is not None:
            val = el.get_text(" ", strip=True)
            if val and 2 <= len(val) <= 60:
                return clean_author_name(val)
    return ""


def build_record(key, source_name, category, author, title, url, blocks, date_dt):
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

    author_name = (author or "").strip()
    return {
        "id": f"{key}-{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}",
        "author": author_name or "Köşe Yazarı",
        "source": source_name,
        "title": title,
        "url": url,
        "date": format_date_tr(date_dt),
        "category": category,
        "readTime": f"{read_time} dk",
        "snippet": snippet,
        "fullContent": "\n".join(parts),
        "avatar": (
            "https://ui-avatars.com/api/?name="
            + quote(author_name or "Yazar")
            + "&background=2E384D&color=fff&size=128&bold=true"
        ),
        "isLive": True,
    }


# ---------------------------------------------------------------------------
# Makale sayfasından çekim
# ---------------------------------------------------------------------------
def parse_html_article(url, paper):
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    candidates = []
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        candidates.append(og["content"])
    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text(" ", strip=True))
    if soup.title:
        candidates.append(soup.title.get_text(" ", strip=True))
    title = ""
    for cand in candidates:
        cand = clean_title(cand)
        if paper.get("author"):
            cand = re.sub(r"\s+-\s+" + re.escape(paper["author"]) + r"\s*$", "", cand).strip()
        if len(cand) >= MIN_TITLE_LEN:
            title = cand
            break
    if not title:
        log(f"    ! başlık bulunamadı <- {url}")
        return None

    author = extract_author_from_soup(soup) or paper.get("author", "")

    blocks = extract_blocks(soup)
    if len(blocks) < 2:
        log(f"    ! gövde bulunamadı <- {url}")
        return None

    date_dt = extract_date_from_soup(soup)
    return build_record(
        paper["key"], paper["name"], paper.get("category", "Gündem"),
        author, title, url, blocks, date_dt,
    )


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
            if c.get("href"):
                return c.get("href").strip()
            return (c.text or "").strip()
    return ""


def html_to_blocks(content_html):
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


def parse_feed(feed_cfg, limit):
    xml = fetch(feed_cfg["feed"])
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
        records.append(build_record(
            feed_cfg["key"], feed_cfg["name"], feed_cfg.get("category", "Gündem"),
            feed_cfg.get("author", ""), title, url, blocks, date_dt,
        ))
        if len(records) >= limit:
            break
    return records


# ---------------------------------------------------------------------------
# Yazar keşfi (tüm aktif köşe yazarları)
# ---------------------------------------------------------------------------
def discover_writers(max_authors_per_paper):
    """Her gazetenin yazarlar dizininden tüm köşe yazarlarını çıkarır."""
    papers_out = []
    total = 0
    for paper in NEWSPAPERS:
        roster_url = paper.get("roster") or paper["today"]
        pattern = paper.get("author_pattern")
        writers = []
        if pattern:
            html = fetch(roster_url)
            if html:
                writers = extract_named_links(
                    html, roster_url, pattern,
                    denylist=paper.get("author_denylist"),
                    limit=max_authors_per_paper,
                )
        # yinelenen isimleri temizle (url bazlı)
        seen, uniq = set(), []
        for w in writers:
            k = w["url"].rstrip("/")
            if k in seen:
                continue
            seen.add(k)
            uniq.append(w)
        papers_out.append({
            "key": paper["key"],
            "name": paper["name"],
            "count": len(uniq),
            "writers": uniq,
        })
        total += len(uniq)
        log(f"  {paper['name']}: {len(uniq)} yazar")
    return {"papers": papers_out, "total": total}


def merge_article_authors(writers_data, records):
    """Makale sayfalarından bulunan yazar adlarını keşif listesine ekler."""
    by_key = {p["key"]: p for p in writers_data["papers"]}
    for rec in records:
        paper = next((p for p in NEWSPAPERS if p["name"] == rec["source"]), None)
        if not paper:
            continue
        entry = by_key.get(paper["key"])
        if not entry:
            continue
        names = {w["name"].lower() for w in entry["writers"]}
        if rec["author"] and rec["author"] != "Köşe Yazarı" and rec["author"].lower() not in names:
            entry["writers"].append({"name": rec["author"], "url": ""})
            entry["count"] += 1
            writers_data["total"] += 1
            names.add(rec["author"].lower())


def save_writers(writers_data, out_path):
    now = datetime.now(TR_TZ)
    payload = {
        "fetchedAt": now.astimezone(timezone.utc).isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "total": writers_data["total"],
        "papers": writers_data["papers"],
    }
    outdir = os.path.dirname(out_path)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"OK: {writers_data['total']} yazar ({len(writers_data['papers'])} gazete) yazıldı -> {out_path}")


# ---------------------------------------------------------------------------
# Günlük makale çekimi
# ---------------------------------------------------------------------------
def fetch_paper_articles(paper, max_per_paper):
    records = []
    mode = paper.get("mode", "today")

    if mode == "today":
        html = fetch(paper["today"])
        if not html:
            return records
        urls = extract_links(
            html, paper["today"], paper["article_pattern"],
            denylist=paper.get("article_denylist"), limit=max_per_paper,
        )
        log(f"  {paper['name']}: dizinden {len(urls)} makale bulundu")
        for url in urls:
            rec = parse_html_article(url, paper)
            if rec:
                records.append(rec)
                log(f"    + [{rec['author']}] {rec['title'][:55]}")

    elif mode == "authors":
        html = fetch(paper["today"])
        if not html:
            return records
        author_urls = extract_links(
            html, paper["today"], paper["author_pattern"],
            denylist=paper.get("author_denylist"), limit=max_per_paper,
        )
        log(f"  {paper['name']}: dizinden {len(author_urls)} yazar bulundu")
        for author_url in author_urls:
            ahtml = fetch(author_url)
            if not ahtml:
                continue
            # yazar adını yazar sayfasının başlığından al
            asoub = BeautifulSoup(ahtml, "html.parser")
            author_name = ""
            h1 = asoub.find("h1")
            if h1:
                author_name = clean_author_name(h1.get_text(" ", strip=True))
            urls = extract_links(
                ahtml, author_url, paper["article_pattern"],
                denylist=paper.get("article_denylist"), limit=1,
            )
            if not urls:
                continue
            sub = dict(paper)
            if author_name:
                sub["author"] = author_name
            rec = parse_html_article(urls[0], sub)
            if rec:
                records.append(rec)
                log(f"    + [{rec['author']}] {rec['title'][:55]}")
    return records


def fetch_personal_articles(src, max_per_source):
    records = []
    html = fetch(src["listing"])
    if not html:
        return records
    urls = extract_links(html, src["listing"], src["article_pattern"], limit=max_per_source)
    for url in urls:
        paper = {"key": src["key"], "name": src["name"], "category": src["category"], "author": src["author"]}
        rec = parse_html_article(url, paper)
        if rec:
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Günlük köşe yazısı toplayıcı (tüm aktif gazeteler)")
    ap.add_argument("--out", default="data/daily.json", help="Günlük makale JSON çıktısı")
    ap.add_argument("--writers-out", default="data/writers.json", help="Yazar listesi JSON çıktısı")
    ap.add_argument("--max-per-paper", type=int, default=25, help="Gazete başına en fazla makale")
    ap.add_argument("--max-authors-per-paper", type=int, default=200, help="Gazete başına en fazla keşfedilen yazar")
    ap.add_argument("--max-per-source", type=int, default=2, help="Kişisel/RSS kaynak başına makale")
    ap.add_argument("--discover-only", action="store_true", help="Sadece yazar listesini üret")
    args = ap.parse_args()

    # --- Yazar keşfi ---
    log(">> Yazar keşfi (aktif köşe yazarları)")
    writers_data = discover_writers(args.max_authors_per_paper)

    if args.discover_only:
        save_writers(writers_data, args.writers_out)
        return 0

    # --- Günlük makale çekimi ---
    records = []
    papers_with_articles = set()

    for paper in NEWSPAPERS:
        log(f">> {paper['name']} ({paper['today']})")
        paper_records = fetch_paper_articles(paper, args.max_per_paper)
        if paper_records:
            papers_with_articles.add(paper["name"])
        records.extend(paper_records)

    for src in PERSONAL_SOURCES:
        log(f">> {src['name']} (kişisel site)")
        records.extend(fetch_personal_articles(src, args.max_per_source))

    for cfg in FEED_SOURCES:
        log(f">> {cfg['name']} (RSS)")
        records.extend(parse_feed(cfg, args.max_per_source))

    # makale sayfalarındaki yazar adlarını keşif listesine işle
    merge_article_authors(writers_data, records)
    save_writers(writers_data, args.writers_out)

    # başlığa göre tekilleştir
    seen, uniq = set(), []
    for r in records:
        key = r["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    if not uniq:
        log("UYARI: Hiç makale bulunamadı — mevcut daily.json korunuyor.")
        return 0

    now = datetime.now(TR_TZ)
    payload = {
        "fetchedAt": now.astimezone(timezone.utc).isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "count": len(uniq),
        "papers": len(papers_with_articles) or len(NEWSPAPERS),
        "writers": writers_data["total"],
        "articles": uniq,
    }
    outdir = os.path.dirname(args.out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"OK: {len(uniq)} makale ({len(papers_with_articles)} gazete) yazıldı -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
