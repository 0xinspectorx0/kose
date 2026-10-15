#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
freshness.py — "Şimdi gazetelere gidip çekim yapmalı mıyız?" kararı
===================================================================
Tek doğruluk kaynağı: hem fetch_columns.py'nin tazelik kısayolu hem de
fetch-columns.yml'in hafif "kontrol" işi bu modülü kullanır. Yalnızca
standart kütüphane — CI'da bağımlılık kurmadan birkaç saniyede koşar.

Neden ayrı bir karar adımı?
    GitHub `schedule` koşuları bu depoda 3-6 saat gecikiyor. Sabit birkaç
    slot yerine yarım saatte bir yoklama yapılıyor; her yoklama önce bu
    kararı veriyor ve asıl çekim (≈8 dk, ~250 istek) yalnızca veri gerçekten
    bayatsa başlıyor. Böylece gecikme ne olursa olsun gün boyu düzenli koşu
    düşüyor ama gazetelere giden istek sayısı aşağıdaki politikayla sınırlı.

Politika (Türkiye saati, UTC+3):
    * veri yok / bozuk / bugünün verisi değil      → çek
    * yayın penceresinde (05:00-12:00) ≥ 1 saatlik → çek
    * diğer saatlerde ≥ 3 saatlik                  → çek
    * seyrek (< 80 yazı) ve ≥ 1 saatlik            → çek (günün kalanı toplansın)
    * aksi halde                                   → atla

Kullanım:
    python3 scripts/freshness.py                        # karar + gerekçe
    python3 scripts/freshness.py --github-output        # needed=/reason= → $GITHUB_OUTPUT
    python3 scripts/freshness.py --min-interval-hours 0 # zorla (her zaman çek)
    python3 scripts/freshness.py --data /tmp/daily.json --now 2026-10-15T07:30:00+03:00

Çıkış kodu her zaman 0'dır (karar stdout'a / $GITHUB_OUTPUT'a yazılır); karar
verilemezse güvenli taraf seçilir: çek.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

TR_TZ = timezone(timedelta(hours=3))  # Türkiye saati (UTC+3, yaz saati yok)

# Köşelerin büyük kısmı bu aralıkta yayımlanıyor (Karar 00:01, Yeni Şafak 04:00,
# Sözcü 05:00, Posta/Milliyet/Takvim 07:00, Cumhuriyet/Habertürk/Star ~09:30-10:00,
# Hürriyet ~11:40). Sabah açan okur sabah köşelerini görebilsin diye saatlik.
PEAK_START_HOUR = 5
PEAK_END_HOUR = 12
PEAK_INTERVAL_HOURS = 1.0
# Öğleden sonra / akşam (Sabah 13:45, Akşam 17:47, Diken 19:43, Altaylı 21:22…)
OFFPEAK_INTERVAL_HOURS = 3.0
# Seyrek veride (sabahın ilk çekimi gibi) yeniden deneme aralığı
SPARSE_RETRY_HOURS = 1.0
DEFAULT_MIN_ARTICLES = 80


def now_tr(now=None):
    """Verilen anı (yoksa şimdiyi) Türkiye saatine çevirir."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(TR_TZ)


def refresh_interval_hours(now=None):
    """Günün saatine göre 'veri ne kadar eskiyse yenilenmeli' eşiği (saat)."""
    hour = now_tr(now).hour
    if PEAK_START_HOUR <= hour < PEAK_END_HOUR:
        return PEAK_INTERVAL_HOURS
    return OFFPEAK_INTERVAL_HOURS


def parse_stamp(value):
    """ISO-8601 damgasını tz-aware datetime'a çevirir (başarısızsa None)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def decide(payload, now=None, min_interval_hours=None, min_articles=DEFAULT_MIN_ARTICLES):
    """Çekim gerekli mi? -> (needs_fetch: bool, reason: str)

    min_interval_hours:
        None -> günün saatine göre politika (refresh_interval_hours)
        <= 0 -> zorla: her zaman çek
        > 0  -> sabit eşik (eski --min-interval-hours davranışı)
    """
    if min_interval_hours is not None and min_interval_hours <= 0:
        return True, "zorla çekim istendi (tazelik kısayolu kapalı)"
    if not isinstance(payload, dict):
        return True, "mevcut veri yok ya da okunamadı — çekim yapılacak"

    now_local = now_tr(now)
    fetched = parse_stamp(payload.get("fetchedAt"))
    if not fetched:
        return True, "mevcut verinin çekim damgası (fetchedAt) yok — çekim yapılacak"

    today = now_local.strftime("%Y-%m-%d")
    data_day = payload.get("date")
    if data_day != today:
        return True, f"mevcut veri bugüne ait değil ({data_day} != {today}) — çekim yapılacak"

    age_h = max(0.0, (now_local - fetched).total_seconds() / 3600.0)
    count = len(payload.get("articles") or [])
    if min_interval_hours is None:
        interval = refresh_interval_hours(now_local)
        window = (f"yayın penceresi {PEAK_START_HOUR:02d}-{PEAK_END_HOUR:02d} TSİ"
                  if interval == PEAK_INTERVAL_HOURS else "pencere dışı")
    else:
        interval = float(min_interval_hours)
        window = "sabit eşik"

    if age_h >= interval:
        return True, (f"mevcut veri {age_h:.1f} saatlik (eşik {interval:g} sa, {window}) "
                      f"— çekim yapılacak")
    sparse_retry = min(SPARSE_RETRY_HOURS, interval)
    if count < min_articles:
        if age_h >= sparse_retry:
            return True, (f"mevcut veri seyrek ({count} yazı < {min_articles}) ve {age_h:.1f} saatlik "
                          f"— günün kalan köşeleri için yeniden çekilecek")
        return False, (f"veri yeni ama seyrek: {count} yazı, {age_h:.1f} saat önce çekildi "
                       f"— {sparse_retry:g} saat dolunca yeniden denenecek, şimdilik atlanıyor")
    return False, (f"veri taze: {count} yazı, {age_h:.1f} saat önce çekildi "
                   f"(eşik {interval:g} sa, {window}) — çekim atlanıyor")


def load_payload(path):
    """JSON dosyasını okur; yoksa/bozuksa None döner."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def decide_file(path, now=None, min_interval_hours=None, min_articles=DEFAULT_MIN_ARTICLES):
    """decide()'ın dosya okuyan sarmalayıcısı."""
    return decide(load_payload(path), now=now, min_interval_hours=min_interval_hours,
                  min_articles=min_articles)


def _write_github_output(needed, reason):
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as f:
        f.write(f"needed={'true' if needed else 'false'}\n")
        f.write(f"reason={reason.replace(chr(10), ' ')}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Köşe yazısı verisi için 'çekim gerekli mi?' kararı")
    ap.add_argument("--data", default="data/daily.json", help="Değerlendirilecek daily.json")
    ap.add_argument("--min-interval-hours", type=float, default=None,
                    help="Sabit tazelik eşiği (saat). Verilmezse günün saatine göre politika; 0 = zorla")
    ap.add_argument("--min-articles", type=int, default=DEFAULT_MIN_ARTICLES,
                    help="Verinin 'dolu' sayılması için gereken en az yazı")
    ap.add_argument("--now", default=None, help="Test için şimdiki an (ISO-8601)")
    ap.add_argument("--github-output", action="store_true",
                    help="Kararı $GITHUB_OUTPUT'a needed=/reason= olarak da yaz")
    args = ap.parse_args(argv)

    try:
        now = parse_stamp(args.now) if args.now else None
        needed, reason = decide_file(args.data, now=now, min_interval_hours=args.min_interval_hours,
                                     min_articles=args.min_articles)
    except Exception as exc:  # karar verilemiyorsa güvenli taraf: çek
        needed, reason = True, f"karar hesaplanamadı ({type(exc).__name__}: {exc}) — çekim yapılacak"

    print(f"needed={'true' if needed else 'false'}")
    print(f"reason={reason}")
    if args.github_output:
        _write_github_output(needed, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
