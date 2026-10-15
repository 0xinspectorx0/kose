#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-pipeline.py — günlük güncelleme hattının çevrimdışı denetimi
==================================================================
Ağ gerektirmez: fetch_columns.py'nin yeni tazelik/yaş/çıkış-kodu mantığını ve
workflow'un kritik ayarlarını doğrular.

Koşum:
    python3 patches/uitest/verify-pipeline.py
Beklenti: tüm maddeler "GEÇTİ", çıkış kodu 0.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import fetch_columns as fc  # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    print(f"  {'GEÇTİ' if cond else 'KALDI'}  {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def write_daily(path, articles, fetched_at, date):
    payload = {"fetchedAt": fetched_at, "date": date, "count": len(articles),
               "articles": articles, "papers": 3, "writers": 10}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


print("\n[A] TAZELİK KISAYOLU (data_is_fresh)")
now_utc = datetime.now(timezone.utc)
today_tr = datetime.now(fc.TR_TZ).strftime("%Y-%m-%d")
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "daily.json")

    write_daily(p, [{"title": "x"}] * 150, iso(now_utc - timedelta(hours=1)), today_tr)
    check("bugünün dolu verisi 1 saatlik -> çekim atlanır",
          fc.data_is_fresh(p, 4.0, 100) is True)

    write_daily(p, [{"title": "x"}] * 150, iso(now_utc - timedelta(hours=6)), today_tr)
    check("bugünün verisi 6 saatlik (eşik 4) -> yeniden çekilir",
          fc.data_is_fresh(p, 4.0, 100) is False)

    write_daily(p, [{"title": "x"}] * 30, iso(now_utc - timedelta(hours=1)), today_tr)
    check("bugünün verisi seyrek (30 < 100) -> yeniden çekilir",
          fc.data_is_fresh(p, 4.0, 100) is False)

    yesterday = (datetime.now(fc.TR_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    write_daily(p, [{"title": "x"}] * 150, iso(now_utc - timedelta(hours=1)), yesterday)
    check("veri dününse -> her zaman çekilir",
          fc.data_is_fresh(p, 4.0, 100) is False)

    check("--min-interval-hours 0 kısayolu kapatır",
          fc.data_is_fresh(p, 0, 100) is False)
    check("dosya yoksa çekim yapılır",
          fc.data_is_fresh(os.path.join(td, "yok.json"), 4.0, 100) is False)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ bozuk json")
    check("bozuk daily.json çekimi engellemez",
          fc.data_is_fresh(p, 4.0, 100) is False)

print("\n[B] YAŞ FİLTRESİ (drop_stale_records)")
recs = [
    {"title": "taze", "publishedAt": iso(now_utc - timedelta(hours=3)), "author": "A", "date": "Bugün"},
    {"title": "iki günlük", "publishedAt": iso(now_utc - timedelta(days=2)), "author": "B", "date": "x"},
    {"title": "haftalık", "publishedAt": iso(now_utc - timedelta(days=7)), "author": "C", "date": "x"},
    {"title": "tarihsiz", "publishedAt": "", "author": "D", "date": "x"},
    {"title": "alanı yok", "author": "E", "date": "x"},
]
kept = fc.drop_stale_records(recs, 3)
titles = [r["title"] for r in kept]
check("3 günden eski yazı elenir", "haftalık" not in titles)
check("2 günlük yazı korunur", "iki günlük" in titles)
check("taze yazı korunur", "taze" in titles)
check("tarihi okunamayan yazı korunur",
      "tarihsiz" in titles and "alanı yok" in titles, f"({len(kept)}/{len(recs)} kayıt)")
check("--max-age-days 0 filtre uygulamaz", len(fc.drop_stale_records(recs, 0)) == len(recs))

print("\n[C] KAYIT ŞEMASI (build_record / publishedAt)")
rec = fc.build_record("test", "Deneme Gazetesi", "Gündem", "Ayşe Yılmaz", "Deneme Başlığı",
                      "https://example.com/yazi", [("p", "Birinci paragraf."), ("p", "İkinci paragraf.")],
                      datetime(2026, 10, 14, 8, 30, tzinfo=fc.TR_TZ))
check("publishedAt UTC ISO-8601 yazılıyor",
      rec["publishedAt"] == "2026-10-14T05:30:00+00:00", rec["publishedAt"])
check("date alanı Türkçe etiket olarak kalıyor", rec["date"] == fc.format_date_tr(datetime(2026, 10, 14, 8, 30, tzinfo=fc.TR_TZ)), rec["date"])
check("uygulamanın beklediği alanlar duruyor",
      all(k in rec for k in ("id", "author", "source", "title", "url", "category",
                             "readTime", "snippet", "fullContent", "avatar", "isLive")))
rec_none = fc.build_record("test", "G", "Gündem", "A", "B", "https://example.com/x",
                           [("p", "a"), ("p", "b")], None)
check("tarih None ise çökmüyor, publishedAt boş kalıyor",
      rec_none["publishedAt"] == "" and isinstance(rec_none["date"], str), rec_none["date"])
check("format_date_tr(None) çökmüyor", bool(fc.format_date_tr(None)))

print("\n[D] ÇIKIŞ KODLARI (main: ağ yok / veri üretilemedi)")
with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, "daily.json")
    wout = os.path.join(td, "writers.json")
    write_daily(out, [{"title": "dünün dolu verisi"}] * 150,
                iso(now_utc - timedelta(hours=20)),
                (datetime.now(fc.TR_TZ) - timedelta(days=1)).strftime("%Y-%m-%d"))
    with open(wout, "w", encoding="utf-8") as f:
        json.dump({"fetchedAt": iso(now_utc - timedelta(hours=20)), "date": "x", "total": 1270,
                   "papers": [{"key": "k", "name": "G", "count": 2,
                               "writers": [{"name": "A B", "url": "https://g/a-b", "photo": ""}]}]}, f)
    before_daily = open(out, encoding="utf-8").read()
    before_writers = open(wout, encoding="utf-8").read()

    real_fetch = fc.fetch
    fc.fetch = lambda url: None  # tüm kaynaklar erişilemez
    argv = sys.argv
    sys.argv = ["fetch_columns.py", "--out", out, "--writers-out", wout, "--require-articles", "20"]
    try:
        rc = fc.main()
    finally:
        sys.argv = argv
        fc.fetch = real_fetch
    check("hiç makale bulunamazsa çıkış kodu 2 (CI yeniden dener)", rc == 2, f"rc={rc}")
    check("mevcut daily.json bozulmadan korunuyor",
          open(out, encoding="utf-8").read() == before_daily)
    after_writers = open(wout, encoding="utf-8").read() if os.path.exists(wout) else ""
    check("keşif boş döndüğünde writers.json hiç değişmiyor",
          after_writers == before_writers and json.loads(after_writers)["total"] == 1270,
          "dosya korundu" if after_writers == before_writers else "DOSYA DEĞİŞTİ")

print("\n[E] TAZE VERİ VARKEN AĞA HİÇ DOKUNULMUYOR")
with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, "daily.json")
    wout = os.path.join(td, "writers.json")
    write_daily(out, [{"title": "bugünün verisi"}] * 150, iso(now_utc - timedelta(minutes=40)), today_tr)
    calls = []
    real_fetch = fc.fetch
    fc.fetch = lambda url: (calls.append(url), None)[1]
    argv = sys.argv
    sys.argv = ["fetch_columns.py", "--out", out, "--writers-out", wout]
    try:
        rc = fc.main()
    finally:
        sys.argv = argv
        fc.fetch = real_fetch
    check("taze veride çıkış kodu 0", rc == 0, f"rc={rc}")
    check("taze veride tek istek atılmıyor", not calls, f"{len(calls)} istek")

print("\n[F] WORKFLOW AYARLARI")
wf_path = os.path.join(REPO, ".github/workflows/fetch-columns.yml")
wf = open(wf_path, encoding="utf-8").read()
try:
    import yaml  # type: ignore
    doc = yaml.safe_load(wf)
    triggers = doc.get("on", doc.get(True))
    crons = [c["cron"] for c in triggers.get("schedule", [])]
    check("en az 4 zamanlanmış slot var", len(crons) >= 4, f"{len(crons)} slot: {', '.join(crons)}")
    minutes = [c.split()[0] for c in crons]
    hours = [c.split()[1] for c in crons]
    check("cron dakikaları :00/:30 değil (GitHub yoğunluğunda daha az gecikir)",
          all(m not in ("0", "30") for m in minutes), ", ".join(minutes))
    check("cron saatleri 3-18 UTC arasında (TSİ 06:00-21:00)",
          all(h.isdigit() and 3 <= int(h) <= 18 for h in hours), ", ".join(hours))
    check("slotlar gün içine yayılmış (en az 3 farklı saat)", len(set(hours)) >= 3)
    check("workflow_dispatch + force girdisi var",
          "force" in str(triggers.get("workflow_dispatch", "")))
    check("concurrency grubu tanımlı (eşzamanlı koşu çakışması olmasın)",
          doc.get("concurrency", {}).get("group") == "kose-fetch-columns")
    check("contents: write yetkisi var",
          doc.get("permissions", {}).get("contents") == "write")
    steps = doc["jobs"]["fetch-columns"]["steps"]
    names = [s.get("name", "") for s in steps]
    check("checkout tam geçmişle çekiyor (fetch-depth: 0)",
          any(s.get("uses", "").startswith("actions/checkout") and
              str(s.get("with", {}).get("fetch-depth")) == "0" for s in steps))
    check("commit adımı iptal dışında hep koşuyor",
          any(n == "Sonuçları commit'le" and "!cancelled()" in str(s.get("if", ""))
              for n, s in zip(names, steps)))
    commit_step = next(s["run"] for s in steps if s.get("name") == "Sonuçları commit'le")
    check("push en az 3 kez deneniyor", commit_step.count("git push origin") >= 1 and
          "for attempt in 1 2 3" in commit_step)
    check("uzak daha tazeyse zarif geçiş var", "REMOTE_NEWER" in commit_step)
    check("reset --hard + yeniden commit kurtarma yolu var",
          "git reset --hard" in commit_step and "cp \"$GEN\"" in commit_step)
    fetch_step = next(s["run"] for s in steps if s.get("name") == "Köşe yazılarını çek")
    check("çekim adımı 2 deneme yapıyor", "for attempt in 1 2" in fetch_step)
except ImportError:
    print("  (PyYAML yok — workflow yapısal denetimi atlandı)")

print("\n[G] GERÇEK VERİ DOSYASI")
daily = os.path.join(REPO, "data/daily.json")
if os.path.exists(daily):
    d = json.load(open(daily, encoding="utf-8"))
    arts = d.get("articles", [])
    check("data/daily.json bugünün verisi",
          d.get("date") == datetime.now(fc.TR_TZ).strftime("%Y-%m-%d"), d.get("date", ""))
    check("makale sayısı makul (>= 20)", len(arts) >= 20, f"{len(arts)} makale")
    check("uygulamanın okuduğu alanlar mevcut",
          all(k in arts[0] for k in ("author", "source", "title", "url", "date", "fullContent")))
else:
    print("  (data/daily.json yok — atlandı)")

print()
if FAILS:
    print(f"{len(FAILS)} MADDE KALDI: {', '.join(FAILS)}")
    sys.exit(1)
print("TÜM HAT DENETİMLERİ GEÇTİ")
