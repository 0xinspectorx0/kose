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
    python scripts/fetch_columns.py --min-interval-hours 0   # tazelik kısayolunu atla

GitHub Actions (.github/workflows/fetch-columns.yml) yarım saatte bir yoklar;
çekimin gerekip gerekmediğine scripts/freshness.py karar verir (veri bugünün
değilse; 05:00-12:00 TSİ arası 1 saatten, diğer saatlerde 3 saatten eskiyse;
seyrekse). Veri zaten tazeyse betik de çekimi atlar (bkz. --min-interval-hours /
--min-articles). İstekler nazik tempodadır (aralarda gecikme vardır).

Çıkış kodları:
    0  bugünün verisi üretildi (ya da zaten tazeydi, çekim atlandı)
    2  bugünün verisi üretilemedi (ağ hatası, boş dizin, çok erken saat…) —
       mevcut daily.json korunur; CI bu kodda bir kez daha dener
"""

import argparse
import copy
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

# Tazelik politikası tek yerde: CI'ın bağımlılıksız "kontrol" işi de aynı modülü
# kullanır (scripts/ dizini, betik doğrudan çalıştırıldığında sys.path'tedir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freshness  # noqa: E402
import kaynak_kurallari  # noqa: E402  (yönetici kaynak kuralları: pasif kaynak/yazar, eklenen akışlar)

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

# Yazar fotoğrafı için ipuçları: class/id/src içinde bu kelimeler geçen <img>
# etiketleri yazar portresi sayılır. Logo/reklam/ikon görselleri elenir.
AUTHOR_PHOTO_HINTS = (
    "author", "yazar", "writer", "avatar", "profile", "portrait", "columnist",
)
# Not: "ads" gibi kısa parçalar düz alt dizi olarak aranmaz; "uploads" gibi
# meşru yolları elememek için desen yol ayracıyla birlikte aranır.
AUTHOR_PHOTO_DENY_RX = re.compile(
    r"logo|icon|sprite|banner|reklam|advert|placeholder|1x1|blank|loading|"
    r"share|social|(^|[^a-z])ads?([^a-z]|$)",
    re.I,
)
AUTHOR_PHOTO_MIN_SIZE = 40

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
    {
        # Evrensel'deki yazar arşivi (güncel adres: /yazi/NNNNN/slug).
        "key": "tastekin", "name": "Evrensel", "category": "Gündem",
        "author": "Fehim Taştekin",
        "listing": "https://www.evrensel.net/yazar/137/fehim-tastekin",
        "article_pattern": r"evrensel\.net/yazi/\d+/[^/?#]+/?$",
    },
    {
        # Habertürk yazar arşivi; köşe bağlantıları iki biçimde gelebiliyor:
        # /yazarlar/oray-egin/NNN-... (arşiv) ve /ozel-icerikler/oray-egin/NNN-... (güncel).
        "key": "egin", "name": "Oray Eğin", "category": "Kültür-Sanat",
        "author": "Oray Eğin",
        "listing": "https://www.haberturk.com/htyazar/oray-egin",
        "article_pattern": r"haberturk\.com/(?:yazarlar|ozel-icerikler)/oray-egin/\d+-[a-z0-9-]+/?$",
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
    {
        # Sözcü'den ayrıldı (Nis 2026); bağımsız YouTube kanalında yayımlıyor.
        # Kanal: youtube.com/@yilmaz_ozdil — Atom akışı video açıklamasından
        # özet/okuma süresi üretilir.
        "key": "yilmazozdil", "name": "Yılmaz Özdil", "category": "Gündem",
        "author": "Yılmaz Özdil",
        "feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCQmDWRUf_X8BSrrDOSZA-NA",
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
        r"Milliyet|Sabah|Cumhuriyet|Vatan|Yeni Şafak|Oksijen|YetkinReport|Evrensel|"
        r"Fatih Altaylı|Livaneli\.gen\.tr|kose|T24|Star|Akşam|Takvim|Posta|Yılmaz Özdil)\s*$",
        "",
        t,
    )
    return t


CORPORATE_TAIL_RX = re.compile(r"gazete|gazetecilik|medya|yay\u0131n|haber|ajans|a\.?\u015f", re.I)


def is_valid_author_name(name):
    """Yazar adı olamayacak değerleri (URL, kurumsal ad) eler."""
    if not name or len(name) < 3 or len(name) > 60:
        return False
    if re.match(r"^\d", name):  # "15. İstanbul Bienali" gibi kişi olmayan kayıtlar
        return False
    if re.fullmatch(r"[0-9a-fA-F]{12,}", name):  # sayfa kimliği / hash görünümlü ad
        return False
    if re.search(r"https?://|www\.|\.(com|net|org|tr)\b|@", name, re.I):
        return False
    if re.search(r"\b(gazetecilik|gazetesi|yay\u0131nc\u0131l\u0131k|medya|ajans\u0131|holding)\b", name, re.I):
        return False
    if re.search(r"\ba\.?\u015f\.?$", name, re.I):
        return False
    return True


def clean_author_name(t):
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(Tüm Yazıları|TÜM YAZILARI|Tüm yazıları)\s*", "", t).strip()
    t = t.rstrip("›»").strip()
    # "Adnan Ekinci | Hukuk Ombudsmanı" -> "Adnan Ekinci" (köşe adı adı değil)
    if "|" in t:
        t = t.split("|")[0].strip()
    # "İlke Gürsoy 15 Yazı", "Abdüllatif Uyan 9297 Adet Yazı" -> sayaç ekini at
    t = re.sub(r"\s+\d+\s+(?:adet\s+)?yaz[ıi]\s*$", "", t, flags=re.I).strip()
    # "Resul TOSUN, Star Gazetesi" -> "Resul TOSUN"
    if "," in t:
        head, _, tail = t.partition(",")
        if CORPORATE_TAIL_RX.search(tail):
            t = head.strip()
    if not is_valid_author_name(t):
        return ""
    return t


def is_noise(text):
    return any(n in text for n in NOISE_FRAGMENTS)


def format_date_tr(d):
    now = datetime.now(TR_TZ)
    if not d:  # tarih hiç okunamadıysa çekim zamanı kullanılır (koşu çökmesin)
        d = now
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
        photo = ""
        img = a.find("img")
        if img is not None:
            src = _abs_img_src(img, base_url)
            if src and not _is_denied_photo(src) and _img_size_ok(img):
                photo = src
        seen.add(href)
        out.append({"name": name, "url": href, "photo": photo})
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
                name = clean_author_name(val)
                if name:
                    return name
    el = soup.find(attrs={"itemprop": AUTHOR_ITEMPROP})
    if el is not None:
        val = el.get("content") or el.get_text(" ", strip=True)
        if val and 2 <= len(val) <= 60:
            name = clean_author_name(val)
            if name:
                return name
    for cls in AUTHOR_CLASS_NAMES:
        el = soup.find(class_=cls)
        if el is not None:
            val = el.get_text(" ", strip=True)
            if val and 2 <= len(val) <= 60:
                name = clean_author_name(val)
                if name:
                    return name
    return ""


def avatar_url(name):
    """Fotoğraf bulunamadığında kullanılan baş harf avatarı."""
    return (
        "https://ui-avatars.com/api/?name="
        + quote(name or "Yazar")
        + "&background=2E384D&color=fff&size=128&bold=true"
    )


def _norm_name(value):
    value = (value or "").strip().lower()
    for ch in ".,;:!?'’“\"()[]*|-":
        value = value.replace(ch, " ")
    return re.sub(r"\s+", " ", value).strip()


def _abs_img_src(img, base_url):
    if img is None:
        return ""
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "srcset"):
        val = img.get(attr)
        if not val:
            continue
        if attr == "srcset":
            val = val.split(",")[0].split(" ")[0]
        val = val.strip()
        if val and not val.startswith("data:"):
            return urljoin(base_url, val)
    return ""


def _img_size_ok(img):
    for attr in ("width", "height"):
        m = re.search(r"\d+", str(img.get(attr) or ""))
        if m and int(m.group()) < AUTHOR_PHOTO_MIN_SIZE:
            return False
    return True


def _has_photo_hint(text):
    return any(h in text for h in AUTHOR_PHOTO_HINTS)


def _is_denied_photo(src):
    return bool(AUTHOR_PHOTO_DENY_RX.search(src or ""))


def _photo_from_jsonld(node):
    """JSON-LD ağacında yalnızca author.image alanını arar (yayıncı logosu değil)."""
    if isinstance(node, list):
        for item in node:
            found = _photo_from_jsonld(item)
            if found:
                return found
        return ""
    if not isinstance(node, dict):
        return ""
    if node.get("@graph"):
        found = _photo_from_jsonld(node["@graph"])
        if found:
            return found
    author = node.get("author")
    for cand in (author if isinstance(author, list) else [author] if author else []):
        if not isinstance(cand, dict):
            continue
        for key in ("image", "photo", "thumbnailUrl"):
            val = cand.get(key)
            if isinstance(val, dict):
                val = val.get("url")
            if isinstance(val, str) and val.startswith("http"):
                return val
    return ""


def author_from_img_alts(soup):
    """Künyede adı metin olarak değil, yazar görselinin alt metninde geçen
    yazarı bulur (Posta: author-placeholder.svg alt="Mehmet Coşundeniz",
    Takvim: class="authors-head-image" alt="Ekrem Kızıltaş" gibi)."""
    for img in soup.find_all("img"):
        alt = clean_author_name(img.get("alt") or "")
        if not alt or len(alt.split()) > 5:
            continue
        parent = img.find_parent()
        pattrs = ""
        if parent is not None and getattr(parent, "get", None):
            pattrs = " ".join([" ".join(parent.get("class") or []), parent.get("id") or ""])
        hay = " ".join([
            " ".join(img.get("class") or []), img.get("id") or "",
            img.get("src") or "", pattrs,
        ]).lower()
        if _has_photo_hint(hay):
            return alt
    return ""


def split_author_prefix(title):
    """"ERHAN AFYONCU - Truva'nın intikamı" -> ("ERHAN AFYONCU", "Truva'nın...").

    Yalnızca baş harfleri büyük (künye biçiminde) ve en az iki kelimelik
    önekler yazar adı sayılır; "Fenerbahçe oyunu - hız sorunu" gibi normal
    başlıklara dokunulmaz.
    """
    m = re.match(r"^\s*([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ .'\-]{2,38})\s+[-–—]\s+(.{5,})$", title or "")
    if not m:
        return "", ""
    name = m.group(1).strip(" .-")
    rest = m.group(2).strip()
    if not is_valid_author_name(name) or len(name.split()) < 2:
        return "", ""
    letters = [c for c in name if c.isalpha()]
    if not letters or sum(1 for c in letters if c.isupper()) / len(letters) < 0.8:
        return "", ""
    return clean_author_name(name), rest


def extract_author_photo(soup, author, base_url):
    """Makale sayfasındaki yazar portresini bulur; bulamazsa boş string döner.

    Sıra: JSON-LD author.image -> alt metni yazar adıyla aynı olan görsel ->
    class/id/src içinde yazar ipucu geçen görsel (üç üst öğeye kadar bakılır).
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except Exception:
            continue
        photo = _photo_from_jsonld(data)
        if photo and not _is_denied_photo(photo):
            return urljoin(base_url, photo)

    target = _norm_name(author)
    imgs = soup.find_all("img")

    if target:
        for img in imgs:
            if _norm_name(img.get("alt")) != target or not _img_size_ok(img):
                continue
            src = _abs_img_src(img, base_url)
            if src and not _is_denied_photo(src):
                return src

    # 3) yazar adını içeren metnin yakınındaki görsel (künye bloğu, site-bağımsız)
    if target:
        for text in soup.find_all(string=True):
            parent = text.parent
            if parent is not None and parent.name in ("script", "style"):
                continue
            if _norm_name(text) != target:
                continue
            node = parent
            for _ in range(3):
                if node is None or not getattr(node, "find", None):
                    break
                img = node.find("img")
                if img is not None and _img_size_ok(img):
                    src = _abs_img_src(img, base_url)
                    if src and not _is_denied_photo(src):
                        return src
                node = node.find_parent()

    # 4) class/id/src içinde yazar ipucu geçen görsel
    for img in imgs:
        if not _img_size_ok(img):
            continue
        src = _abs_img_src(img, base_url)
        if not src or _is_denied_photo(src):
            continue
        hay = " ".join([
            " ".join(img.get("class") or []), img.get("id") or "", src,
        ]).lower()
        if _has_photo_hint(hay):
            return src
        parent = img.find_parent()
        for _ in range(3):
            if parent is None or not getattr(parent, "get", None):
                break
            attrs = " ".join([
                " ".join(parent.get("class") or []), parent.get("id") or "",
            ]).lower()
            if _has_photo_hint(attrs):
                return src
            parent = parent.find_parent()
    return ""


def build_record(key, source_name, category, author, title, url, blocks, date_dt,
                 photo=""):
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
    photo = (photo or "").strip()
    # Makinenin okuyabildiği yayım zamanı (UTC ISO-8601): yaş filtresi ve
    # ileride "en yeni önce" sıralaması için. "date" alanı insan okumasına
    # yönelik Türkçe etiket olarak kalır.
    published_at = ""
    if date_dt:
        try:
            published_at = date_dt.astimezone(timezone.utc).isoformat()
        except Exception:
            published_at = ""
    return {
        "id": f"{key}-{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}",
        "sourceKey": key,
        "author": author_name or "Köşe Yazarı",
        "source": source_name,
        "title": title,
        "url": url,
        "date": format_date_tr(date_dt),
        "publishedAt": published_at,
        "category": category,
        "readTime": f"{read_time} dk",
        "snippet": snippet,
        "fullContent": "\n".join(parts),
        "photo": photo,
        "avatar": photo or avatar_url(author_name),
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

    # Yazar adı ve portresi çoğu sitede <header>/<aside> içinde durur; bu
    # yüzden künye bilgisi, bu etiketler silinmeden ÖNCE çıkarılır.
    # Sıra: sayfadaki künye -> künye görselinin alt metni -> yapılandırılmış
    # yazar (kişisel blog/RSS kaynaklarında gazete adı ile yazar adı aynıdır,
    # o yüzden yapılandırılmış değer en sona bırakılır).
    author = ""
    page_author = extract_author_from_soup(soup)
    if is_valid_author_name(page_author) and page_author.lower() != paper["name"].lower():
        author = page_author
    if not author:
        author = author_from_img_alts(soup)
    if not author:
        author = paper.get("author", "")
    try:
        photo_soup = copy.copy(soup)
    except Exception:
        photo_soup = BeautifulSoup(html, "html.parser")

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

    # tmgrup gazeteleri (Sabah/Takvim/Yeni Asır) yazarı başlığa gömer
    if not author:
        name, rest = split_author_prefix(title)
        if name:
            author, title = name, rest

    photo = extract_author_photo(photo_soup, author, url)

    blocks = extract_blocks(soup)
    if len(blocks) < 2:
        log(f"    ! gövde bulunamadı <- {url}")
        return None

    date_dt = extract_date_from_soup(soup)
    return build_record(
        paper["key"], paper["name"], paper.get("category", "Gündem"),
        author, title, url, blocks, date_dt, photo=photo,
    )


def safe_parse_article(url, paper):
    """parse_html_article'ı tek makale ölçeğinde korur.

    Bir sayfanın şablonu beklenmedik biçimde değişirse yalnızca o makale
    atlanır; gazetenin (ve günün) geri kalanı kurtarılır.
    """
    try:
        return parse_html_article(url, paper)
    except Exception as e:
        log(f"    ! makale çözümlenemedi ({type(e).__name__}: {e}) <- {url}")
        return None


# ---------------------------------------------------------------------------
# RSS / Atom akışından çekim
# ---------------------------------------------------------------------------
def _local_name(tag):
    return tag.split("}")[-1]


def _child_text(item, *names):
    for c in item:
        if _local_name(c.tag) in names:
            return (c.text or "").strip()
    # YouTube Atom: <media:description> doğrudan entry altında değil,
    # <media:group> içinde durur — torunlarda da ara.
    for c in item.iter():
        if c is item:
            continue
        if _local_name(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
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


def parse_feed(feed_cfg, limit, xml_text=None):
    xml = xml_text if xml_text is not None else fetch(feed_cfg["feed"])
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
# Yöneticinin eklediği kaynaklar: yazılan adres -> okunabilir akış
# ---------------------------------------------------------------------------
YOUTUBE_CHANNEL_RX = re.compile(
    r'"(?:channelId|externalId)"\s*:\s*"(UC[\w-]{22})"|channel_id=(UC[\w-]{22})|/channel/(UC[\w-]{22})'
)


def looks_like_feed(text):
    """Metin RSS/Atom/RDF akışı mı (HTML sayfa değil)?"""
    head = (text or "").lstrip("\ufeff \t\r\n")[:1500].lower()
    if head.startswith("<rss") or head.startswith("<feed") or head.startswith("<rdf"):
        return True
    return head.startswith("<?xml") and any(t in head for t in ("<rss", "<feed", "<rdf:rdf"))


def resolve_feed(url, cached=None):
    """Yöneticinin yazdığı adresi okunabilir bir akışa çevirir.

    Dönüş: (akış_adresi, akış_metni, durum) — durum: 'ok' | 'akis-yok' | 'erisilemedi'.
      * Önceki çekimde çözülen akış (cached) varsa önce o denenir (tek istek).
      * Adres zaten RSS/Atom ise olduğu gibi kullanılır.
      * YouTube kanal sayfası (@ad, /c/, /user/, /channel/) -> kanalın Atom akışı.
      * Düz site/blog sayfası -> <link rel="alternate" type="application/rss+xml">
        (otomatik keşif); bulunamazsa WordPress/Blogger'ın alışıldık akış yolları.
    İstek sayısı sınırlıdır (en çok ~4): 40 eklenen kaynak bile çekimi uzatmaz.
    """
    if cached and cached != url:
        xml = fetch(cached)
        if xml and looks_like_feed(xml):
            return cached, xml, "ok"
    text = fetch(url)
    if text is None:
        return None, None, "erisilemedi"
    if looks_like_feed(text):
        return url, text, "ok"
    host = (urlparse(url).hostname or "").lower()
    if host == "youtu.be" or host.endswith("youtube.com"):
        m = YOUTUBE_CHANNEL_RX.search(text)
        if m:
            cid = next(g for g in m.groups() if g)
            feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            xml = fetch(feed)
            if xml and looks_like_feed(xml):
                return feed, xml, "ok"
        return None, None, "akis-yok"
    candidates = []
    try:
        soup = BeautifulSoup(text, "html.parser")
        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            typ = (link.get("type") or "").lower()
            if "alternate" in rel and any(t in typ for t in ("rss", "atom", "feed+xml")):
                candidates.append(urljoin(url, link["href"]))
    except Exception:
        pass
    base = url if url.endswith("/") else url + "/"
    candidates += [urljoin(base, "feed/"), urljoin(base, "feeds/posts/default")]
    tried = set()
    for cand in candidates:
        if len(tried) >= 3:
            break
        if cand in tried or cand == url or kaynak_kurallari.ozel_adres_mi(urlparse(cand).hostname):
            continue
        tried.add(cand)
        xml = fetch(cand)
        if xml and looks_like_feed(xml):
            return cand, xml, "ok"
    return None, None, "akis-yok"


def katalog_girdisi(src, tur, pasif, sayac):
    """data/kaynaklar.json'daki tek kaynak satırı (Yönetim paneli listeler)."""
    girdi = {
        "key": src["key"],
        "name": src["name"],
        "tur": tur,
        "category": src.get("category", ""),
        "aktif": src["key"] not in pasif,
        "yazi": sayac.get(src["key"], 0),
    }
    if src.get("author"):
        girdi["author"] = src["author"]
    return girdi


# ---------------------------------------------------------------------------
# Yazar keşfi (tüm aktif köşe yazarları)
# ---------------------------------------------------------------------------
def discover_writers(max_authors_per_paper, papers=None):
    """Her gazetenin yazarlar dizininden tüm köşe yazarlarını çıkarır.

    papers verilirse yalnızca o gazeteler taranır (yöneticinin çekimden
    çıkardığı gazeteler atlanır)."""
    papers_out = []
    total = 0
    for paper in (NEWSPAPERS if papers is None else papers):
        roster_url = paper.get("roster") or paper["today"]
        pattern = paper.get("author_pattern")
        writers = []
        if pattern:
            # Tek bir gazetenin dizini patlarsa bütün keşif (ve dolayısıyla
            # günün verisi) kaybolmasın: hata kaynağa özgü kalır.
            try:
                html = fetch(roster_url)
                if html:
                    writers = extract_named_links(
                        html, roster_url, pattern,
                        denylist=paper.get("author_denylist"),
                        limit=max_authors_per_paper,
                    )
            except Exception as e:
                log(f"    ! {paper['name']} yazar dizini okunamadı: {type(e).__name__}: {e}")
                writers = []
        # adları temizle; yinelenenleri (url ve ad bazlı) ele
        seen, seen_names, uniq = set(), set(), []
        for w in writers:
            name = clean_author_name(w.get("name", ""))
            if not name:
                continue
            k = w["url"].rstrip("/")
            nk = name.casefold()
            if k in seen or nk in seen_names:
                continue
            seen.add(k)
            seen_names.add(nk)
            uniq.append({**w, "name": name})
        papers_out.append({
            "key": paper["key"],
            "name": paper["name"],
            "count": len(uniq),
            "writers": uniq,
        })
        total += len(uniq)
        log(f"  {paper['name']}: {len(uniq)} yazar")
    return {"papers": papers_out, "total": total}


def fill_missing_authors(records, writers_data):
    """Makale sayfasından yazarı okunamayan kayıtları, gazetenin keşfedilen
    yazar listesindeki profil bağlantısıyla eşleştirerek tamamlar.

    Örnek: https://www.cumhuriyet.com.tr/yazarlar/emre-kongar/odadaki-fil-2545467
    adresi, roster'daki https://www.cumhuriyet.com.tr/yazarlar/emre-kongar
    profilinin altında kaldığı için yazar adı "Emre Kongar" olarak atanır.
    İsim üretilmez/tahmin edilmez; yalnızca roster'da gerçekten var olan
    eşleşmeler kullanılır.
    """
    by_source = {}
    for paper in writers_data.get("papers", []):
        pairs = [
            (w["url"].rstrip("/"), w["name"])
            for w in paper.get("writers", [])
            if w.get("url")
        ]
        if pairs:
            # uzun profil adresi önce denensin (iç içe eşleşme riskine karşı)
            by_source[paper["name"]] = sorted(pairs, key=lambda t: -len(t[0]))

    fixed = 0
    for rec in records:
        if rec.get("author") and rec["author"] != "Köşe Yazarı":
            continue
        url = (rec.get("url") or "").rstrip("/")
        if not url:
            continue
        for prof_url, name in by_source.get(rec.get("source"), []):
            if url.startswith(prof_url):
                rec["author"] = name
                rec["avatar"] = rec.get("photo") or avatar_url(name)
                fixed += 1
                break
    if fixed:
        log(f">> Yazar adı roster'dan tamamlandı: {fixed} kayıt")
    return records


def fill_missing_photos(records, writers_data):
    """Makale sayfasında fotoğrafı bulunamayan kayıtlara, aynı gazetenin yazar
    listesindeki profil fotoğrafını atar. Bulunamazsa baş harf avatarı kalır."""
    by_source = {}
    for paper in writers_data.get("papers", []):
        photos = {
            _norm_name(w["name"]): w["photo"]
            for w in paper.get("writers", [])
            if w.get("photo") and _norm_name(w.get("name"))
        }
        if photos:
            by_source[paper["name"]] = photos

    fixed = 0
    for rec in records:
        if rec.get("photo"):
            continue
        photo = by_source.get(rec.get("source"), {}).get(_norm_name(rec.get("author")))
        if photo:
            rec["photo"] = photo
            rec["avatar"] = photo
            fixed += 1
    if fixed:
        log(f">> Yazar fotoğrafı roster'dan tamamlandı: {fixed} kayıt")
    return records


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
            entry["writers"].append(
                {"name": rec["author"], "url": "", "photo": rec.get("photo", "")}
            )
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
            rec = safe_parse_article(url, paper)
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
            rec = safe_parse_article(urls[0], sub)
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
        rec = safe_parse_article(url, paper)
        if rec:
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Tazelik kısayolu ve yaş filtresi
# ---------------------------------------------------------------------------
def load_payload(path):
    """JSON dosyasını okur; yoksa/bozuksa None döner (eski veri bozulmuş olabilir)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def data_is_fresh(path, min_interval_hours=None, min_articles=freshness.DEFAULT_MIN_ARTICLES):
    """Mevcut daily.json bugünün verisiyse, yeterince yeniyse ve doluysa True.

    Karar scripts/freshness.py'de (CI'ın hafif kontrol işiyle aynı politika):
      * min_interval_hours None -> günün saatine göre eşik (05-12 TSİ: 1 sa, diğer: 3 sa)
      * min_interval_hours <= 0 -> kısayol kapalı, her zaman çek
      * min_interval_hours > 0  -> sabit eşik
    Sabahın erken saatlerindeki seyrek çekim (ör. 60 yazı) "dolu" sayılmaz —
    saatte bir yeniden denenir ki günün ilerleyen koşusu tüm köşeleri toplasın.
    """
    needs_fetch, reason = freshness.decide_file(
        path, min_interval_hours=min_interval_hours, min_articles=min_articles)
    log(f">> {reason[:1].upper()}{reason[1:]}")
    return not needs_fetch


def drop_stale_records(records, max_age_days):
    """Yayım tarihi max_age_days günden eski yazıları eler (varsayılan: bugün + dün).

    Gazetelerin "bugünün yazıları" dizinleri ara sıra eski yazıları da
    listeliyor — canlı koşuda 2023 Mayıs'ından iki yazı bile düştü. Bu da
    akışın günlerdir güncellenmediği izlenimi veriyor.
    Tarih hiç okunamamışsa kayıt korunur (şüphe yazarın lehine).
    """
    if not max_age_days or max_age_days <= 0:
        return records
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept, dropped = [], []
    for rec in records:
        dt = parse_date_any(rec.get("publishedAt") or "")
        if dt and dt < cutoff:
            dropped.append(rec)
            continue
        kept.append(rec)
    for rec in dropped[:10]:
        log(f"    - eski yazı elendi ({rec.get('date')}): [{rec.get('author')}] {rec.get('title', '')[:50]}")
    if len(dropped) > 10:
        log(f"    - …ve {len(dropped) - 10} eski yazı daha")
    if dropped:
        log(f">> {max_age_days} günden eski {len(dropped)} yazı elendi")
    return kept


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
    ap.add_argument("--min-interval-hours", type=float, default=None,
                    help="Mevcut veri bugünün verisiyse ve bu kadar saatten yeniyse çekimi atla. "
                         "Verilmezse günün saatine göre politika (05-12 TSİ: 1 sa, diğer: 3 sa); 0 = her zaman çek")
    ap.add_argument("--min-articles", type=int, default=freshness.DEFAULT_MIN_ARTICLES,
                    help="Tazelik kısayolunun 'dolu' sayması için gereken en az makale sayısı")
    ap.add_argument("--max-age-days", type=int, default=2,
                    help="Yayım tarihi bu kadar günden eski yazıları çıktıya alma, yani bugün+dün kalır (0 = filtre yok)")
    ap.add_argument("--require-articles", type=int, default=20,
                    help="Bugünün verisi bu sayının altında kalırsa çıkış kodu 2 döndür (CI yeniden dener; 0 = kapat)")
    ap.add_argument("--kurallar-url", default=None,
                    help="Yönetici kaynak kuralları ucu (varsayılan: KAYNAK_KURALLARI_URL ortam değişkeni, "
                         "o da yoksa murekkep.vercel.app; 'yok' = kural uygulama)")
    ap.add_argument("--kaynaklar-out", default="data/kaynaklar.json",
                    help="Kaynak kataloğu + uygulanan kurallar (uygulamadaki Yönetim paneli okur)")
    args = ap.parse_args()
    kurallar_url = (args.kurallar_url if args.kurallar_url is not None
                    else (os.environ.get("KAYNAK_KURALLARI_URL") or kaynak_kurallari.VARSAYILAN_URL))

    # --- Tazelik kısayolu: bugünün dolu verisi zaten varsa gazetelere dokunma ---
    if not args.discover_only and data_is_fresh(args.out, args.min_interval_hours, args.min_articles):
        return 0

    # --- Yönetici kaynak kuralları (uygulamadaki Yönetim paneli) ---
    # Kuralların ALINMAYA ÇALIŞILDIĞI an kataloğa yazılır: röle, kurallar bundan
    # sonra değiştiyse zorla çekim başlatır (her değişiklik en fazla bir kez).
    kurallar_alindi = datetime.now(timezone.utc).isoformat()
    kurallar, kural_kaynagi, kural_notu = kaynak_kurallari.kurallari_yukle(kurallar_url, args.kaynaklar_out)
    log(f">> Kaynak kuralları: {kural_notu}")
    pasif_kaynak = kaynak_kurallari.pasif_kaynak_anahtarlari(kurallar)
    pasif_yazar = kaynak_kurallari.pasif_yazar_anahtarlari(kurallar)
    aktif_gazeteler = [p for p in NEWSPAPERS if p["key"] not in pasif_kaynak]
    aktif_kisisel = [s for s in PERSONAL_SOURCES if s["key"] not in pasif_kaynak]
    aktif_akislar = [c for c in FEED_SOURCES if c["key"] not in pasif_kaynak]
    ek_kaynaklar = kaynak_kurallari.ek_akis_kaynaklari(kurallar)
    for src in NEWSPAPERS + PERSONAL_SOURCES + FEED_SOURCES:
        if src["key"] in pasif_kaynak:
            log(f"   - {src['name']}: yönetici çekimden çıkardı (pasif)")
    for p in kurallar["pasif"]["yazarlar"]:
        log(f"   - yazar {p['ad']}: yönetici çekimden çıkardı (pasif)")

    # --- Yazar keşfi ---
    log(">> Yazar keşfi (aktif köşe yazarları)")
    try:
        writers_data = discover_writers(args.max_authors_per_paper, aktif_gazeteler)
    except Exception as e:
        log(f"! Yazar keşfi yarıda kesildi: {type(e).__name__}: {e}")
        writers_data = {"papers": [], "total": 0}

    # Keşif tamamen boş döndüyse mevcut writers.json'ı EZME: 1000+ yazarlık
    # dizin bir ağ aksaklığında silinmesin. Eski dosya hem korunur hem de
    # yazar adı/fotoğraf tamamlamalarında roster olarak kullanılmaya devam eder.
    keep_existing_writers = False
    if not writers_data.get("total"):
        previous = load_payload(args.writers_out)
        if previous and previous.get("total"):
            log(f"UYARI: keşif boş döndü — mevcut writers.json korunuyor ({previous['total']} yazar)")
            kept = [p for p in (previous.get("papers") or []) if p.get("key") not in pasif_kaynak]
            writers_data = {
                "papers": kept,
                "total": sum(len(p.get("writers") or []) for p in kept) if pasif_kaynak else (previous.get("total") or 0),
            }
            keep_existing_writers = True

    if args.discover_only:
        if not keep_existing_writers:
            save_writers(writers_data, args.writers_out)
        return 0

    # --- Günlük makale çekimi ---
    # Her kaynak ayrı ayrı korunur: bir gazetenin sayfası beklenmedik bir hata
    # verirse (şablon değişti, ağ koptu) günün geri kalanı kaybolmaz.
    records = []
    papers_with_articles = set()

    for paper in aktif_gazeteler:
        log(f">> {paper['name']} ({paper['today']})")
        try:
            paper_records = fetch_paper_articles(paper, args.max_per_paper)
        except Exception as e:
            log(f"    ! {paper['name']} çekilemedi: {type(e).__name__}: {e}")
            paper_records = []
        if paper_records:
            papers_with_articles.add(paper["name"])
        records.extend(paper_records)

    for src in aktif_kisisel:
        log(f">> {src['name']} (kişisel site)")
        try:
            records.extend(fetch_personal_articles(src, args.max_per_source))
        except Exception as e:
            log(f"    ! {src['name']} çekilemedi: {type(e).__name__}: {e}")

    for cfg in aktif_akislar:
        log(f">> {cfg['name']} (RSS)")
        try:
            records.extend(parse_feed(cfg, args.max_per_source))
        except Exception as e:
            log(f"    ! {cfg['name']} okunamadı: {type(e).__name__}: {e}")

    # Yöneticinin eklediği kaynaklar: adres akışa çözülür (önceki çekimde
    # çözülen akış katalogdan hatırlanır), durum Yönetim panelinde gösterilir.
    onceki_katalog = {}
    for k in (load_payload(args.kaynaklar_out) or {}).get("katalog") or []:
        if isinstance(k, dict) and k.get("key") and k.get("akis"):
            onceki_katalog[k["key"]] = k["akis"]
    ek_durum = {}
    for cfg in ek_kaynaklar:
        log(f">> {cfg['name']} (eklenen kaynak: {cfg['feed']})")
        try:
            feed_url, xml_text, durum = resolve_feed(cfg["feed"], onceki_katalog.get(cfg["key"]))
            if not feed_url:
                log(f"    ! akış bulunamadı ({durum})")
                ek_durum[cfg["key"]] = {"durum": durum}
                continue
            recs = parse_feed({**cfg, "feed": feed_url}, args.max_per_source, xml_text=xml_text)
            ek_durum[cfg["key"]] = {"durum": "ok" if recs else "bos", "akis": feed_url}
            log(f"    + {len(recs)} yazı ({feed_url})")
            records.extend(recs)
        except Exception as e:
            log(f"    ! {cfg['name']} okunamadı: {type(e).__name__}: {e}")
            ek_durum[cfg["key"]] = {"durum": "hata"}

    # dizinlerde kalmış eski yazılar akışı bayat göstermesin
    records = drop_stale_records(records, args.max_age_days)

    # yazarı/fotoğrafı okunamayan kayıtları roster eşleşmesiyle tamamla,
    # ardından makale sayfalarındaki yazar adlarını keşif listesine işle
    fill_missing_authors(records, writers_data)
    fill_missing_photos(records, writers_data)
    if pasif_yazar:
        once = len(records)
        records = [r for r in records if kaynak_kurallari.writer_key(r.get("author")) not in pasif_yazar]
        if once != len(records):
            log(f">> {once - len(records)} yazı pasif yazar kuralıyla elendi")
        for p in writers_data.get("papers") or []:
            p["writers"] = [w for w in (p.get("writers") or [])
                            if kaynak_kurallari.writer_key(w.get("name")) not in pasif_yazar]
            if "count" in p:
                p["count"] = len(p["writers"])
        writers_data["total"] = sum(len(p.get("writers") or []) for p in writers_data.get("papers") or [])
    merge_article_authors(writers_data, records)
    if keep_existing_writers and not records:
        # Keşif de makaleler de boş döndü: dosyaya hiç dokunma (zaman damgası
        # bile yenilenmesin) ki uygulama bayat veriyi taze sanmasın.
        log(">> writers.json korunuyor (keşif boş döndü, makale de yok)")
    else:
        # Keşif boş döndüyse writers_data diskteki mevcut listeden yüklendi,
        # yani yazılan dosya eski dizini KORUR (üzerine boş liste yazılmaz).
        save_writers(writers_data, args.writers_out)

    # başlığa göre tekilleştir — aynı başlık iki kez düşerse (ör. gazete
    # akışı + yazarın kişisel kaynağı) yazar adı bilinen kayıt tercih edilir
    seen, uniq = {}, []
    for r in records:
        key = r["title"].lower()
        if key not in seen:
            seen[key] = len(uniq)
            uniq.append(r)
        else:
            old = uniq[seen[key]]
            real = lambda a: a and a != "Köşe Yazarı"
            if not real(old.get("author")) and real(r.get("author")):
                uniq[seen[key]] = r

    if not uniq:
        log("UYARI: Hiç makale bulunamadı — mevcut daily.json korunuyor.")
        return 2 if args.require_articles > 0 else 0

    now = datetime.now(TR_TZ)
    payload = {
        "fetchedAt": now.astimezone(timezone.utc).isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "count": len(uniq),
        "papers": len(papers_with_articles) or len(aktif_gazeteler),
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

    # Kaynak kataloğu: tüm tanımlı kaynaklar + uygulanan kurallar + kaynak başına
    # yazı sayısı / eklenen kaynağın durumu. Uygulamadaki Yönetim paneli listeler;
    # kural ucu bir sonraki çekimde okunamazsa buradaki kurallar kullanılır.
    sayac = {}
    for r in uniq:
        k = r.get("sourceKey") or str(r.get("id", "")).rsplit("-", 1)[0]
        sayac[k] = sayac.get(k, 0) + 1
    katalog = ([katalog_girdisi(p, "gazete", pasif_kaynak, sayac) for p in NEWSPAPERS]
               + [katalog_girdisi(s, "site", pasif_kaynak, sayac) for s in PERSONAL_SOURCES]
               + [katalog_girdisi(c, "akis", pasif_kaynak, sayac) for c in FEED_SOURCES])
    for e in kurallar["ek"]:
        girdi = katalog_girdisi(e, "ek", pasif_kaynak, sayac)
        girdi["feed"] = e["feed"]
        durum = ek_durum.get(e["key"], {})
        girdi["durum"] = durum.get("durum") or ("pasif" if e["key"] in pasif_kaynak else "bekliyor")
        if durum.get("akis"):
            girdi["akis"] = durum["akis"]
        katalog.append(girdi)
    try:
        kaynak_kurallari.katalog_yaz(args.kaynaklar_out, {
            "guncellendi": payload["fetchedAt"],
            "kurallarAlindi": kurallar_alindi,
            "kurallarKaynagi": kural_kaynagi,
            "kurallarSurumu": kurallar["surum"],
            "kurallarNotu": kural_notu,
            "kurallar": kurallar,
            "katalog": katalog,
        })
        log(f"OK: kaynak kataloğu ({len(katalog)} kaynak, {len(pasif_kaynak)} pasif) -> {args.kaynaklar_out}")
    except Exception as e:
        log(f"UYARI: kaynak kataloğu yazılamadı: {type(e).__name__}: {e}")

    # CI'ın "bugünün verisi gerçekten üretildi mi?" denetimi: eşik altındaysa
    # 2 döner, workflow bir kez daha dener (ağ hatası / dizin değişikliği /
    # çok erken saat gibi geçici durumlarda günlük güncelleme kaybolmasın).
    if args.require_articles > 0 and len(uniq) < args.require_articles:
        log(f"UYARI: {len(uniq)} makale bulundu, beklenen en az {args.require_articles} — koşu başarısız sayıldı.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
