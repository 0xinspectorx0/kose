#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_daily.py — "Bugünün en son yazıları gerçekten çekilmiş mi?" denetimi
==========================================================================
data/daily.json (+ data/writers.json) dosyalarını okur ve günlük güncelleme
hattının gerçekten çalışıp çalışmadığını ölçer. Ağ gerektirmez; yalnızca
depodaki veriye bakar, yani "kazıyıcı çalıştı ama boş mu döndü?", "günün
yazıları mı yoksa dünün mü?", "son 24 saatte yayımlanan yazılar gelmiş mi?"
sorularının hepsine cevap verir.

Kullanım:
    python3 scripts/verify_daily.py                  # insan okumasına yönelik rapor
    python3 scripts/verify_daily.py --markdown       # GitHub iş özeti biçiminde
    python3 scripts/verify_daily.py --json           # makine okunur
    python3 scripts/verify_daily.py --data /tmp/d.json --writers /tmp/w.json

Çıkış kodları:
    0  sağlıklı — bugünün verisi var, dolu ve son yayımlanan yazıları içeriyor
    1  sorun var (bayat / seyrek / dünün verisi) — denetim koşusu bunu kırmızı gösterir
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

TR_TZ = timezone(timedelta(hours=3))  # Türkiye saati (UTC+3)

TURKISH_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

RE_BUGUN = re.compile(r"^Bugün\s+(\d{1,2}):(\d{2})$", re.I)
RE_DUN = re.compile(r"^Dün\s+(\d{1,2}):(\d{2})$", re.I)
RE_TAM = re.compile(r"^(\d{1,2})\s+([A-Za-zçğıöşüÇĞİÖŞÜ]+)\s+(\d{4})$")
RE_SAAT = re.compile(r"(\d{1,2}):(\d{2})")


def load_json(path):
    """JSON dosyasını okur; yoksa/bozuksa (None, neden) döner."""
    if not path or not os.path.exists(path):
        return None, "dosya yok"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def parse_stamp(value):
    """ISO-8601 damgasını tz-aware datetime'a çevirir (başarısızsa None)."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=TR_TZ)
    except Exception:
        return None


def article_time(rec, fetched_dt):
    """Bir kaydın yayım zamanını çıkarır.

    Öncelik makine okunur `publishedAt` alanında; eski veri dosyalarında bu
    alan yok, o yüzden Türkçe `date` etiketi ("Bugün 04:00", "Dün 07:30",
    "12 Ekim 2026") çekim gününe göre yorumlanır. Saat bilgisi yoksa gün
    ortası (12:00) varsayılır — yaş hesabında ±12 saat tolerans anlamına gelir.
    """
    direct = parse_stamp(rec.get("publishedAt"))
    if direct:
        return direct.astimezone(TR_TZ), "publishedAt"
    label = (rec.get("date") or "").strip()
    if not label or not fetched_dt:
        return None, "yok"
    base = fetched_dt.astimezone(TR_TZ)
    m = RE_BUGUN.match(label)
    if m:
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                            second=0, microsecond=0), "Bugün etiketi"
    m = RE_DUN.match(label)
    if m:
        d = base - timedelta(days=1)
        return d.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                         second=0, microsecond=0), "Dün etiketi"
    m = RE_TAM.match(label)
    if m:
        month = TURKISH_MONTHS.get(m.group(2).lower())
        if month:
            hm = RE_SAAT.search(label)
            hour, minute = (int(hm.group(1)), int(hm.group(2))) if hm else (12, 0)
            try:
                return datetime(int(m.group(3)), month, int(m.group(1)), hour, minute,
                                tzinfo=TR_TZ), "tam tarih etiketi"
            except ValueError:
                return None, "yok"
    return None, "yok"


def num(value, nd=1, suffix=""):
    """Sayıyı güvenli biçimde metne çevirir (None -> '?'); iç içe f-string gerektirmez."""
    if value is None:
        return "?"
    return f"{value:.{nd}f}{suffix}"


def stamp16(value):
    """ISO damgasını 'YYYY-AA-GG SS:DD' biçimine indirger (yoksa '?')."""
    return value[:16].replace("T", " ") if value else "?"


def stamp10(value):
    return value[:10] if value else "?"


def analyze(daily, writers):
    """Veriden denetim metriklerini çıkarır (dict)."""
    arts = daily.get("articles") or []
    fetched = parse_stamp(daily.get("fetchedAt"))
    now = datetime.now(timezone.utc)
    data_day = (daily.get("date") or "").strip()
    today_tr = datetime.now(TR_TZ).strftime("%Y-%m-%d")

    times, per_source = [], {}
    dated_from = {"publishedAt": 0, "Bugün etiketi": 0, "Dün etiketi": 0,
                  "tam tarih etiketi": 0, "yok": 0}
    for rec in arts:
        src = rec.get("source") or "?"
        slot = per_source.setdefault(src, {"count": 0, "same_day": 0, "newest": None})
        slot["count"] += 1
        t, how = article_time(rec, fetched)
        dated_from[how] = dated_from.get(how, 0) + 1
        if not t:
            continue
        times.append(t)
        if data_day and t.astimezone(TR_TZ).strftime("%Y-%m-%d") == data_day:
            slot["same_day"] += 1
        if slot["newest"] is None or t > slot["newest"]:
            slot["newest"] = t

    newest = max(times) if times else None
    oldest = min(times) if times else None
    ref = fetched or now
    same_day = sum(1 for t in times if t.astimezone(TR_TZ).strftime("%Y-%m-%d") == data_day) if data_day else 0
    recent_24h = sum(1 for t in times if 0 <= (ref - t).total_seconds() <= 24 * 3600)
    recent_36h = sum(1 for t in times if 0 <= (ref - t).total_seconds() <= 36 * 3600)
    fresh_sources = sorted(
        (s for s, v in per_source.items() if v["same_day"] > 0),
        key=lambda s: -per_source[s]["same_day"],
    )

    w_fetched = parse_stamp((writers or {}).get("fetchedAt"))
    return {
        "date": data_day,
        "today": today_tr,
        "isToday": data_day == today_tr,
        "fetchedAt": daily.get("fetchedAt") or "",
        "ageHours": round((now - fetched).total_seconds() / 3600.0, 2) if fetched else None,
        "count": len(arts),
        "sourceCount": len(per_source),
        "papers": daily.get("papers"),
        "sameDay": same_day,
        "recent24h": recent_24h,
        "recent36h": recent_36h,
        "newest": newest.astimezone(TR_TZ).isoformat() if newest else None,
        "newestAgeHours": round((ref - newest).total_seconds() / 3600.0, 2) if newest else None,
        "oldest": oldest.astimezone(TR_TZ).isoformat() if oldest else None,
        "oldestAgeDays": round((ref - oldest).total_seconds() / 86400.0, 2) if oldest else None,
        "undatedRecords": dated_from.get("yok", 0),
        "freshSourceCount": len(fresh_sources),
        "freshSources": fresh_sources,
        "perSource": {
            s: {"count": v["count"], "sameDay": v["same_day"],
                "newest": v["newest"].astimezone(TR_TZ).isoformat() if v["newest"] else None}
            for s, v in sorted(per_source.items(), key=lambda kv: -kv[1]["count"])
        },
        "writersTotal": (writers or {}).get("total"),
        "writersDate": (writers or {}).get("date"),
        "writersAgeHours": round((now - w_fetched).total_seconds() / 3600.0, 2) if w_fetched else None,
    }


def check(stats, thresholds):
    """Denetim maddelerini üretir: [(ad, geçti mi, açıklama)]"""
    def hours(h):
        return "?" if h is None else f"{h:.1f} sa"

    items = [
        (
            "Veri bugünün verisi",
            bool(stats["isToday"]),
            f"veri günü {stats['date'] or '?'}, bugün {stats['today']}",
        ),
        (
            f"Çekim {thresholds['max_age_hours']:g} saatten yeni",
            stats["ageHours"] is not None and stats["ageHours"] <= thresholds["max_age_hours"],
            f"yaş {hours(stats['ageHours'])} (son çekim {stats['fetchedAt'][:19] or '?'})",
        ),
        (
            f"En az {thresholds['min_articles']} yazı var",
            stats["count"] >= thresholds["min_articles"],
            f"{stats['count']} yazı · {stats['sourceCount']} kaynak",
        ),
        (
            f"En az {thresholds['min_fresh_sources']} kaynak günün yazısını getirmiş",
            stats["freshSourceCount"] >= thresholds["min_fresh_sources"],
            f"{stats['freshSourceCount']} kaynak: {', '.join(stats['freshSources'][:8])}"
            + ("…" if stats["freshSourceCount"] > 8 else ""),
        ),
        (
            f"Son 24 saatte yayımlanan en az {thresholds['min_recent']} yazı çekilmiş",
            stats["recent24h"] >= thresholds["min_recent"],
            f"son 24 sa: {stats['recent24h']} · son 36 sa: {stats['recent36h']} · "
            f"en yeni yazı {stamp16(stats['newest'])} ({hours(stats['newestAgeHours'])} önce)",
        ),
        (
            f"Yazılar {thresholds['max_article_age_days']:g} günden eski değil",
            stats["oldestAgeDays"] is None or stats["oldestAgeDays"] <= thresholds["max_article_age_days"],
            f"en eski yazı {stamp10(stats['oldest'])} ({num(stats['oldestAgeDays'])} gün)",
        ),
        (
            "Yazar dizini sağlam",
            bool(stats["writersTotal"]) and stats["writersTotal"] >= thresholds["min_writers"]
            and (stats["writersAgeHours"] is None
                 or stats["writersAgeHours"] <= thresholds["max_writers_age_hours"]),
            f"{stats['writersTotal'] or 0} yazar · {hours(stats['writersAgeHours'])} önce",
        ),
    ]
    return items


def render_text(stats, items, ok):
    head = "SAĞLIKLI" if ok else "SORUN VAR"
    lines = [
        f"KÖŞE YAZISI GÜNLÜK VERİ DENETİMİ — {head}",
        f"  veri günü     : {stats['date'] or '?'} (bugün {stats['today']})",
        f"  son çekim     : {stats['fetchedAt'][:19].replace('T', ' ') or '?'} UTC"
        f" ({num(stats['ageHours'])} saat önce)",
        f"  hacim         : {stats['count']} yazı · {stats['sourceCount']} kaynak · "
        f"{stats['sameDay']} yazı veri gününde · {stats['recent24h']} yazı son 24 saatte",
        f"  en yeni yazı  : {stamp16(stats['newest'])}"
        f" · en eski: {stamp10(stats['oldest'])} ({num(stats['oldestAgeDays'])} gün)",
        f"  tarihsiz kayıt: {stats['undatedRecords']}",
        "",
        "  DENETİM MADDELERİ",
    ]
    for name, passed, detail in items:
        lines.append(f"    {'✓' if passed else '✗'} {name} — {detail}")
    lines.append("")
    lines.append("  KAYNAK BAZINDA (yazı | günün yazısı | en yeni)")
    for src, v in stats["perSource"].items():
        lines.append(f"    {src:<20} {v['count']:>3} | {v['sameDay']:>3} | "
                     f"{stamp16(v['newest']) if v['newest'] else '-'}")
    return "\n".join(lines)


def render_markdown(stats, items, ok, reason):
    icon = "✅" if ok else "⚠️"
    title = "Veri sağlıklı — bugünün en son yazıları çekilmiş" if ok else f"Denetim başarısız — {reason}"
    out = [f"### {icon} Günlük veri denetimi", "", f"**{title}**", ""]
    out += [
        f"- **Veri günü (TSİ):** {stats['date'] or '?'} (bugün {stats['today']})",
        f"- **Son çekim:** {stats['fetchedAt'][:19].replace('T', ' ') or '?'} UTC"
        f" ({num(stats['ageHours'])} saat önce)",
        f"- **Hacim:** {stats['count']} yazı · {stats['sourceCount']} kaynak · "
        f"{stats['sameDay']} yazı veri gününde · **{stats['recent24h']} yazı son 24 saatte yayımlanmış**",
        f"- **En yeni yazı:** {stamp16(stats['newest'])} · en eski: {stamp10(stats['oldest'])}",
        "", "| Denetim | Sonuç | Ayrıntı |", "|---|---|---|",
    ]
    for name, passed, detail in items:
        out.append(f"| {name} | {'✅' if passed else '❌'} | {detail} |")
    out += ["", "<details><summary>Kaynak bazında dağılım</summary>", "",
            "| Kaynak | Yazı | Günün yazısı | En yeni |", "|---|---|---|---|"]
    for src, v in stats["perSource"].items():
        newest = stamp16(v["newest"]) if v["newest"] else "-"
        out.append(f"| {src} | {v['count']} | {v['sameDay']} | {newest} |")
    out += ["", "</details>", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Günlük köşe yazısı verisinin sağlık denetimi")
    ap.add_argument("--data", default="data/daily.json")
    ap.add_argument("--writers", default="data/writers.json")
    ap.add_argument("--max-age-hours", type=float, default=24.0,
                    help="Son çekim bu kadar saatten eskiyse başarısız (varsayılan 24)")
    ap.add_argument("--min-articles", type=int, default=60,
                    help="En az bu kadar yazı olmalı (varsayılan 60)")
    ap.add_argument("--min-fresh-sources", type=int, default=6,
                    help="Günün yazısını getirmiş en az bu kadar kaynak olmalı (varsayılan 6)")
    ap.add_argument("--min-recent", type=int, default=40,
                    help="Son 24 saatte yayımlanmış en az bu kadar yazı olmalı (varsayılan 40)")
    ap.add_argument("--max-article-age-days", type=float, default=3.0,
                    help="Akıştaki en eski yazı bu kadar günden eskiyse başarısız (varsayılan 3)")
    ap.add_argument("--min-writers", type=int, default=200,
                    help="Yazar dizininde en az bu kadar yazar olmalı (varsayılan 200)")
    ap.add_argument("--max-writers-age-hours", type=float, default=72.0,
                    help="Yazar dizini bu kadar saatten eskiyse başarısız (varsayılan 72)")
    ap.add_argument("--markdown", action="store_true", help="GitHub iş özeti biçiminde yaz")
    ap.add_argument("--json", action="store_true", help="Makine okunur çıktı")
    args = ap.parse_args()

    thresholds = {
        "max_age_hours": args.max_age_hours,
        "min_articles": args.min_articles,
        "min_fresh_sources": args.min_fresh_sources,
        "min_recent": args.min_recent,
        "max_article_age_days": args.max_article_age_days,
        "min_writers": args.min_writers,
        "max_writers_age_hours": args.max_writers_age_hours,
    }

    daily, err = load_json(args.data)
    writers, werr = load_json(args.writers)
    if daily is None:
        print(f"✗ {args.data} okunamadı: {err}")
        if args.markdown:
            print(f"### ⚠️ Günlük veri denetimi\n\n**`{args.data}` okunamadı:** {err}")
        return 1
    if writers is None:
        writers = {}
        print(f"! {args.writers} okunamadı: {werr} (yazar dizini maddesi başarısız sayılacak)")

    stats = analyze(daily, writers)
    items = check(stats, thresholds)
    failed = [name for name, ok, _ in items if not ok]
    ok = not failed

    if args.json:
        print(json.dumps({"healthy": ok, "failed": failed, "thresholds": thresholds,
                          "stats": stats}, ensure_ascii=False, indent=2))
    elif args.markdown:
        reason = ", ".join(failed) if failed else ""
        print(render_markdown(stats, items, ok, reason))
    else:
        print(render_text(stats, items, ok))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
