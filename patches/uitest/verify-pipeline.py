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
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import fetch_columns as fc  # noqa: E402
import freshness  # noqa: E402

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

print("\n[A2] GÜNÜN SAATİNE GÖRE TAZELİK POLİTİKASI (scripts/freshness.py)")
TR = freshness.TR_TZ


def payload_at(fetched_tr, n=150):
    return {"date": fetched_tr.strftime("%Y-%m-%d"), "fetchedAt": fetched_tr.isoformat(),
            "articles": [{"title": "x"}] * n}


def at(h, m=0, day=15):
    return datetime(2026, 10, day, h, m, tzinfo=TR)


policy_cases = [
    ("08:30 yayın penceresi, 40 dk'lık dolu veri -> atla", at(8, 30), at(7, 50), 150, False),
    ("08:30 yayın penceresi, 70 dk'lık dolu veri -> çek (eşik 1 sa)", at(8, 30), at(7, 20), 150, True),
    ("15:00 pencere dışı, 2 sa'lik dolu veri -> atla (eşik 3 sa)", at(15), at(13), 150, False),
    ("15:00 pencere dışı, 3.2 sa'lik dolu veri -> çek", at(15), at(11, 48), 150, True),
    ("15:00 seyrek veri 30 dk'lık -> atla (saatte bir dener)", at(15), at(14, 30), 40, False),
    ("15:00 seyrek veri 70 dk'lık -> çek", at(15), at(13, 50), 40, True),
    ("00:10 gün dönümü, dünün verisi -> çek", at(0, 10, day=16), at(22, 0), 150, True),
    ("02:00 gece, 1.5 sa'lik bugünün dolu verisi -> atla", at(2, 0, day=16), at(0, 30, day=16), 150, False),
    ("11:59 pencerenin son dakikası, 65 dk'lık -> çek", at(11, 59), at(10, 54), 150, True),
    ("12:00 pencere kapandı, 65 dk'lık -> atla", at(12, 0), at(10, 55), 150, False),
]
for label, now_tr, fetched_tr, n, expected in policy_cases:
    got, why = freshness.decide(payload_at(fetched_tr, n), now=now_tr)
    check(label, got is expected, why)
check("eşik: 05-12 TSİ arası 1 sa, diğer saatler 3 sa",
      [freshness.refresh_interval_hours(at(h)) for h in (4, 5, 11, 12, 23)] == [3.0, 1.0, 1.0, 3.0, 3.0])
check("zorla (min_interval_hours=0) her zaman çeker",
      freshness.decide(payload_at(at(8, 0)), now=at(8, 1), min_interval_hours=0)[0] is True)
check("veri yoksa/bozuksa çeker", freshness.decide(None)[0] is True and freshness.decide("x")[0] is True)
check("fetchedAt yoksa çeker", freshness.decide({"date": "2026-10-15", "articles": []}, now=at(9))[0] is True)
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "daily.json")
    out = os.path.join(td, "gh-output.txt")
    json.dump(payload_at(at(8, 0)), open(p, "w", encoding="utf-8"))
    cli = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "freshness.py"), "--data", p,
                          "--now", at(8, 30).isoformat(), "--github-output"],
                         capture_output=True, text=True, env=dict(os.environ, GITHUB_OUTPUT=out))
    written = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
    check("CLI: kararı stdout'a ve $GITHUB_OUTPUT'a yazıyor, çıkış 0",
          cli.returncode == 0 and "needed=false" in cli.stdout and "needed=false" in written
          and "reason=" in written, (cli.stdout + cli.stderr).strip().replace("\n", " | ")[:160])
    cli2 = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "freshness.py"), "--data",
                           os.path.join(td, "yok.json")], capture_output=True, text=True)
    check("CLI: dosya yoksa needed=true, çıkış 0", cli2.returncode == 0 and "needed=true" in cli2.stdout)
check("fetch_columns aynı politikayı kullanıyor (tek doğruluk kaynağı)",
      fc.freshness is freshness and "freshness.decide_file" in open(
          os.path.join(REPO, "scripts", "fetch_columns.py"), encoding="utf-8").read())

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

    def runs_per_day(expr):
        minute, hour = expr.split()[:2]
        n_min = len(minute.split(","))
        if hour == "*":
            n_hour = 24
        elif hour.startswith("*/"):
            n_hour = 24 // int(hour[2:])
        else:
            n_hour = len(hour.split(","))
        return n_min * n_hour

    per_day = sum(runs_per_day(c) for c in crons)
    check("gün boyu sık yoklama (günde en az 24 koşu — GitHub gecikmesine dayanıklı)",
          per_day >= 24, f"{per_day} koşu/gün: {', '.join(crons)}")
    check("her saat yoklanıyor (saat alanı '*')", all(c.split()[1] == "*" for c in crons))
    minutes = [m for c in crons for m in c.split()[0].split(",")]
    check("cron dakikaları :00/:30 değil (GitHub yoğunluğunda daha az gecikir)",
          all(m not in ("0", "30") for m in minutes), ", ".join(minutes))
    check("workflow_dispatch + force girdisi var",
          "force" in str(triggers.get("workflow_dispatch", "")))
    push = triggers.get("push") or {}
    check("push tetikleyicisi yalnızca main'de (geçici dal tetikleyicisi kalmamış)",
          push.get("branches") == ["main"], str(push.get("branches")))
    check("push yalnızca kazıyıcı/politika/workflow değişince (paths filtresi)",
          {"scripts/fetch_columns.py", "scripts/freshness.py",
           ".github/workflows/fetch-columns.yml"} <= set(push.get("paths") or []),
          str(push.get("paths")))
    check("contents: write yetkisi var",
          doc.get("permissions", {}).get("contents") == "write")

    jobs = doc["jobs"]
    kontrol = jobs.get("kontrol") or {}
    fetch_job = jobs["fetch-columns"]
    check("önce hafif 'kontrol' işi var", bool(kontrol), ", ".join(jobs))
    k_steps = kontrol.get("steps", [])
    k_text = json.dumps(k_steps, ensure_ascii=False)
    check("kontrol işi bağımlılık kurmuyor (pip/setup-python yok)",
          "pip install" not in k_text and "setup-python" not in k_text)
    check("kontrol kararı scripts/freshness.py'den alıyor", "scripts/freshness.py" in k_text)
    check("kontrol çıktıları: needed / force / reason",
          set((kontrol.get("outputs") or {}).keys()) >= {"needed", "force", "reason"})
    check("çekim işi kontrole bağlı ve yalnızca gerekince koşuyor",
          fetch_job.get("needs") == "kontrol"
          and "needs.kontrol.outputs.needed == 'true'" in str(fetch_job.get("if", "")),
          str(fetch_job.get("if")))
    check("concurrency kilidi ÇEKİM işinde (kontroller kilide takılmaz)",
          (fetch_job.get("concurrency") or {}).get("group") == "kose-fetch-columns"
          and not doc.get("concurrency"))
    check("kilit beklerken sıradaki çekim iptal edilmiyor (cancel-in-progress: false)",
          (fetch_job.get("concurrency") or {}).get("cancel-in-progress") is False)
    steps = fetch_job["steps"]
    names = [s.get("name", "") for s in steps]
    checkouts = [st for job in (kontrol, fetch_job) for st in job.get("steps", [])
                 if st.get("uses", "").startswith("actions/checkout")]
    check("iki iş de dalın GÜNCEL ucunu çekiyor (ref: github.ref_name)",
          len(checkouts) == 2 and all("github.ref_name" in str(st.get("with", {}).get("ref"))
                                      for st in checkouts))
    check("Node 24 sürümlü eylemler (checkout@v6+, setup-python@v6+)",
          all(st.get("uses", "").split("@")[-1] not in ("v4", "v5")
              for job in jobs.values() for st in job.get("steps", []) if st.get("uses")))
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
    fetch_step = next(s for s in steps if s.get("name") == "Köşe yazılarını çek")
    check("çekim adımı 2 deneme yapıyor", "for attempt in 1 2" in fetch_step["run"])
    check("zorla çekim kontrolün force çıktısından geliyor",
          "needs.kontrol.outputs.force" in str(fetch_step.get("env", {}))
          and "--min-interval-hours 0" in fetch_step["run"])

    print("\n[F2] ADIM BETİKLERİNİN SÖZDİZİMİ (CI kabuğu)")
    with tempfile.TemporaryDirectory() as td:
        for job_id, job in jobs.items():
            for i, st in enumerate(job.get("steps", [])):
                if "run" not in st:
                    continue
                sp = os.path.join(td, f"{job_id}-{i}.sh")
                open(sp, "w", encoding="utf-8").write(st["run"])
                ok = all(subprocess.run(["bash", *flags, "-n", sp], capture_output=True).returncode == 0
                         for flags in (["-e"], ["-eo", "pipefail"]))
                check(f"{job_id} / '{st.get('name')}' bash -e / pipefail ile geçerli", ok)

    print("\n[F3] KONTROL ADIMI UÇTAN UCA (gerçek betik, sahte runner ortamı)")
    karar = next(st for st in k_steps if st.get("id") == "karar")

    def run_karar(daily, event="schedule", force_input="", ref="main", default="main"):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "data"))
            os.makedirs(os.path.join(td, "scripts"))
            subprocess.run(["cp", os.path.join(REPO, "scripts", "freshness.py"),
                            os.path.join(td, "scripts")], check=True)
            if daily is not None:
                json.dump(daily, open(os.path.join(td, "data", "daily.json"), "w", encoding="utf-8"))
            sp = os.path.join(td, "karar.sh")
            open(sp, "w", encoding="utf-8").write(karar["run"])
            out, summ = os.path.join(td, "out.txt"), os.path.join(td, "sum.md")
            env = dict(os.environ, GITHUB_OUTPUT=out, GITHUB_STEP_SUMMARY=summ,
                       GITHUB_EVENT_NAME=event, GITHUB_REF_NAME=ref,
                       FORCE_INPUT=force_input, DEFAULT_BRANCH=default)
            p = subprocess.run(["bash", "-e", sp], cwd=td, capture_output=True, text=True, env=env)
            kv = {}
            for line in open(out, encoding="utf-8").read().splitlines() if os.path.exists(out) else []:
                k, _, v = line.partition("=")
                kv[k] = v  # GitHub'da da aynı anahtarın SON değeri geçerlidir
            return p.returncode, kv, (open(summ, encoding="utf-8").read() if os.path.exists(summ) else "")

    now_tr = datetime.now(freshness.TR_TZ)
    fresh = {"date": now_tr.strftime("%Y-%m-%d"), "fetchedAt": iso(now_utc - timedelta(minutes=10)),
             "articles": [{"title": "x"}] * 150}
    stale = {"date": (now_tr - timedelta(days=1)).strftime("%Y-%m-%d"),
             "fetchedAt": iso(now_utc - timedelta(hours=20)), "articles": [{"title": "x"}] * 150}
    rc, kv, summ = run_karar(fresh)
    check("taze veri + zamanlanmış yoklama -> needed=false, force=false",
          rc == 0 and kv.get("needed") == "false" and kv.get("force") == "false", str(kv))
    check("iş özetine karar ve gerekçe yazılıyor", "Tazelik kontrolü" in summ and "Gerekçe" in summ)
    rc, kv, _ = run_karar(stale)
    check("dünün verisi -> needed=true", rc == 0 and kv.get("needed") == "true", kv.get("reason", ""))
    rc, kv, _ = run_karar(fresh, event="workflow_dispatch", force_input="true")
    check("elle force -> taze veride bile needed=true, force=true",
          kv.get("needed") == "true" and kv.get("force") == "true", str(kv))
    rc, kv, _ = run_karar(fresh, event="push", ref="main")
    check("main'e push (kod merge) -> zorla çekim",
          kv.get("needed") == "true" and kv.get("force") == "true", str(kv))
    rc, kv, _ = run_karar(fresh, event="push", ref="ozellik-dali")
    check("başka dala push -> zorlamaz, politikaya bakar",
          kv.get("needed") == "false" and kv.get("force") == "false", str(kv))
    rc, kv, _ = run_karar(None)
    check("veri dosyası yoksa -> needed=true (güvenli taraf)", rc == 0 and kv.get("needed") == "true",
          kv.get("reason", ""))
except ImportError:
    print("  (PyYAML yok — workflow yapısal denetimi atlandı)")

print("\n[G] GERÇEK VERİ DOSYASI")
daily = os.path.join(REPO, "data/daily.json")
if os.path.exists(daily):
    d = json.load(open(daily, encoding="utf-8"))
    arts = d.get("articles", [])
    # Not: verinin bugüne ait olup olmaması bu paketin konusu değil — o iş
    # scripts/verify_daily.py + verify-columns.yml (watchdog) koşusuna ait.
    # Burası yalnızca dosyanın şemasını doğrular; gün bilgisi not düşülür.
    today = datetime.now(fc.TR_TZ).strftime("%Y-%m-%d")
    print(f"  BİLGİ  data/daily.json veri günü: {d.get('date')} (bugün {today})"
          + ("" if d.get("date") == today else " — bayat; denetim için: python3 scripts/verify_daily.py"))
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
