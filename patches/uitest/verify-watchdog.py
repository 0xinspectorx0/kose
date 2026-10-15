#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-watchdog.py — "her gün en son yazılar çekiliyor mu?" denetçisinin testi
=============================================================================
scripts/verify_daily.py ile .github/workflows/verify-columns.yml dosyalarını
ağ gerektirmeden doğrular.

Koşum:
    python3 patches/uitest/verify-watchdog.py            # PyYAML varsa tam
    python3 patches/uitest/verify-watchdog.py --quick    # sadece betik testleri

Beklenti: tüm maddeler GEÇTİ, çıkış kodu 0.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VERIFY = os.path.join(REPO, "scripts", "verify_daily.py")
WORKFLOW = os.path.join(REPO, ".github", "workflows", "verify-columns.yml")
TR = timezone(timedelta(hours=3))
PY = sys.executable

FAILS = []


def check(label, cond, detail=""):
    print(f"  {'GEÇTİ' if cond else 'KALDI'}  {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def run_verify(datapath, writerspath, *extra):
    cmd = [PY, VERIFY, "--data", datapath, "--writers", writerspath, *extra]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return p.returncode, p.stdout + p.stderr


def article(i, source, label, published=None):
    rec = {
        "id": f"a{i}", "author": f"Yazar {i}", "source": source, "title": f"Yazı {i}",
        "url": f"https://example.com/{i}", "date": label, "category": "Gündem",
        "readTime": "2 dk", "snippet": "özet", "fullContent": "<p>metin</p>",
        "photo": "", "avatar": "", "isLive": True,
    }
    if published:
        rec["publishedAt"] = published
    return rec


def write(path, date, fetched_at, arts, count=None):
    json.dump({
        "fetchedAt": fetched_at, "date": date, "count": count if count is not None else len(arts),
        "papers": 5, "writers": 1200, "articles": arts,
    }, open(path, "w", encoding="utf-8"), ensure_ascii=False)


def writers(path, total=1200, fetched_at=None):
    json.dump({"fetchedAt": fetched_at or datetime.now(timezone.utc).isoformat(),
               "date": datetime.now(TR).strftime("%Y-%m-%d"), "total": total, "papers": []},
              open(path, "w", encoding="utf-8"), ensure_ascii=False)


now = datetime.now(timezone.utc)
today = datetime.now(TR).strftime("%Y-%m-%d")
yesterday = (datetime.now(TR) - timedelta(days=1)).strftime("%Y-%m-%d")

with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "daily.json")
    w = os.path.join(td, "writers.json")
    writers(w)

    print("\n[A] SAĞLIKLI VERİ (bugünün, dolu, taze)")
    arts = [article(i, f"Gazete{i % 8}", f"Bugün {4 + i % 12}:0{i % 6}",
                    (now - timedelta(hours=1 + i % 9)).isoformat()) for i in range(90)]
    write(d, today, now.isoformat(), arts)
    rc, out = run_verify(d, w)
    check("çıkış kodu 0", rc == 0, f"rc={rc}")
    check("rapor SAĞLIKLI diyor", "SAĞLIKLI" in out and "SORUN VAR" not in out)
    check("90 yazının tamamı sayıldı", "90 yazı" in out)
    check("son 24 saat denetimi geçti", "✓ Son 24 saatte yayımlanan" in out)

    print("\n[B] DÜNÜN VERİSİ (günlük güncelleme aksamış)")
    write(d, yesterday, (now - timedelta(hours=13)).isoformat(), arts)
    rc, out = run_verify(d, w)
    check("çıkış kodu 1", rc == 1, f"rc={rc}")
    check("'Veri bugünün verisi' maddesi kaldı", "✗ Veri bugünün verisi" in out)

    print("\n[C] SEYREK VERİ (çekim boş dönmüş gibi)")
    write(d, today, now.isoformat(), arts[:12])
    rc, out = run_verify(d, w)
    check("çıkış kodu 1", rc == 1, f"rc={rc}")
    check("yazı sayısı maddesi kaldı", "✗ En az 60 yazı var" in out)

    print("\n[D] ESKİ YAZI SIZMIŞ (akış bayat görünüyor)")
    old = [article(999, "Arşiv Kaynağı", "27 Mayıs 2023",
                   datetime(2023, 5, 27, 9, 0, tzinfo=TR).astimezone(timezone.utc).isoformat())]
    write(d, today, now.isoformat(), arts + old)
    rc, out = run_verify(d, w)
    check("çıkış kodu 1", rc == 1, f"rc={rc}")
    check("yaş maddesi kaldı", "✗ Yazılar 3 günden eski değil" in out)
    check("en eski yazı raporda görünüyor", "2023-05-27" in out)

    print("\n[E] publishedAt YOK — Türkçe etiketten tarih üretiliyor (eski veri biçimi)")
    legacy = [article(i, f"Gazete{i % 7}", ("Bugün 07:0%d" % (i % 6)) if i % 3 else ("Dün 06:0%d" % (i % 6)))
              for i in range(90)]
    write(d, today, now.isoformat(), legacy)
    rc, out = run_verify(d, w)
    check("etiketten tarih okundu (tarihsiz kayıt 0)", "tarihsiz kayıt: 0" in out, out.split("tarihsiz")[0][-40:])
    check("günün yazısı sayıldı", re.search(r"90 yazı veri gününde|(\d{2}) yazı veri gününde", out) is not None)
    check("eski biçimli veri de denetleniyor (rc 0/1 ikisi de geçerli)", rc in (0, 1), f"rc={rc}")

    print("\n[F] BOZUK / EKSİK DOSYA")
    rc, out = run_verify(os.path.join(td, "yok.json"), w)
    check("dosya yoksa çıkış 1", rc == 1, f"rc={rc}")
    broken = os.path.join(td, "bozuk.json")
    open(broken, "w", encoding="utf-8").write("{ bozuk")
    rc, out = run_verify(broken, w)
    check("bozuk JSON'da çıkış 1", rc == 1, f"rc={rc}")
    write(d, today, now.isoformat(), arts)
    rc, out = run_verify(d, os.path.join(td, "yok-writers.json"))
    check("yazar dizini yoksa o madde kalıyor ama çökmüyor",
          rc == 1 and "✗ Yazar dizini sağlam" in out, f"rc={rc}")

    print("\n[G] ÇIKIŞ BİÇİMLERİ")
    rc, out = run_verify(d, w, "--json")
    try:
        payload = json.loads(out)
        check("--json geçerli JSON", True)
        check("--json alanları tam", all(k in payload for k in ("healthy", "failed", "stats", "thresholds")))
        check("--json içinde kaynak kırılımı var", len(payload["stats"]["perSource"]) >= 5)
    except Exception as e:
        check("--json geçerli JSON", False, str(e))
    rc, out = run_verify(d, w, "--markdown")
    check("--markdown iş özeti tablosu üretiyor",
          "| Denetim | Sonuç | Ayrıntı |" in out and "<details>" in out)

# ---------------------------------------------------------------------------
print("\n[H] WATCHDOG WORKFLOW YAPISI")
try:
    import yaml  # type: ignore
except ImportError:
    print("  (PyYAML yok — workflow denetimi atlandı: pip install pyyaml)")
    yaml = None

if yaml and "--quick" not in sys.argv:
    # yukarıdaki `with` bloğu kapandı; workflow/onarma testleri için yeni geçici dizin
    td = tempfile.mkdtemp(prefix="kose-watchdog-")
    doc = yaml.safe_load(open(WORKFLOW, encoding="utf-8"))
    on = doc.get("on", doc.get(True))
    crons = [c["cron"] for c in on.get("schedule", [])]
    check("günde en az 2 denetim slotu", len(crons) >= 2, ", ".join(crons))
    check("denetim saatleri çekim slotlarından sonra (10 ve 19 UTC)",
          {c.split()[1] for c in crons} >= {"10", "19"}, str([c.split()[1] for c in crons]))
    check("actions:write yetkisi var (onarma için dispatch)",
          doc.get("permissions", {}).get("actions") == "write")
    check("concurrency kilidi var", bool(doc.get("concurrency", {}).get("group")))
    steps = doc["jobs"]["verify"]["steps"]
    by_name = {s.get("name"): s for s in steps}
    check("adımlar: denetle → onar → son denetim",
          all(n in by_name for n in ("Veriyi denetle", "Son denetim"))
          and any("onarma" in (n or "").lower() or "zorla" in (n or "") for n in by_name))
    heal = next(s for n, s in by_name.items() if n and "zorla" in n)
    check("onarma yalnızca veri bayatken koşuyor", "healthy == 'no'" in str(heal.get("if", "")),
          str(heal.get("if", "")))
    check("onarma dispatch'i force=true ile çağırıyor",
          "dispatches" in heal["run"] and "force=true" in heal["run"])
    check("onarma koşusunun bitmesi bekleniyor", ".status" in heal["run"] and "completed" in heal["run"])
    check("onarma sonrası main'in verisi indiriliyor",
          "git fetch origin" in heal["run"] and "data/daily.json" in heal["run"])
    last = by_name["Son denetim"]
    check("son denetim her durumda koşuyor", "!cancelled()" in str(last.get("if", "")))
    check("veri hâlâ bayatsa koşu KIRMIZI bitiyor (exit 1)", "exit 1" in last["run"])
    check("kırmızı bitişte ::error:: notu düşüyor", "::error::" in last["run"])

    # Runner kabuğu `bash -e` (pipefail YOK): `... | tee` sonrası rc=$? tee'nin
    # kodunu okur ve denetim hep sağlıklı görünürdü. Bu regresyon korunuyor.
    allruns = "\n".join(s.get("run", "") for s in steps)
    check("çıkış kodu borudan okunmuyor (| tee + rc=$? yok)",
          not re.search(r"\|\s*tee[^\n]*\n\s*rc=\$\?", allruns))

    print("\n[I] ADIM BETİKLERİNİN SÖZDİZİMİ (CI kabuğu)")
    for i, s in enumerate(steps):
        if "run" not in s:
            continue
        p = os.path.join(td, f"step{i}.sh")
        open(p, "w", encoding="utf-8").write(s["run"])
        ok = all(subprocess.run(["bash", *flags, "-n", p], capture_output=True).returncode == 0
                 for flags in (["-e"], ["-eo", "pipefail"]))
        check(f"adım '{s.get('name')}' bash -e / pipefail ile geçerli", ok)

    print("\n[J] ONARMA ADIMI UÇTAN UCA (sahte gh ile)")
    stub_dir = os.path.join(td, "stub")
    os.makedirs(stub_dir, exist_ok=True)
    stub = os.path.join(stub_dir, "gh")
    open(stub, "w", encoding="utf-8").write('''#!/usr/bin/env bash
set -uo pipefail
LOG="$STUB_LOG"; COUNTER="$STUB_COUNTER"; q=""; url=""; method="GET"; prev=""
for a in "$@"; do
  case "$prev" in -q) q="$a" ;; -X) method="$a" ;; esac
  if [ -z "$url" ] && [[ "$a" == repos/* ]]; then url="$a"; fi
  prev="$a"
done
echo "method=$method url=$url" >> "$LOG"
emit() { if [ -n "$q" ]; then printf '%s' "$1" | jq -r "$q"; else printf '%s\\n' "$1"; fi; }
now_plus=$(date -u -d '+1 minute' +%Y-%m-%dT%H:%M:%SZ)
now_minus=$(date -u -d '-2 hour' +%Y-%m-%dT%H:%M:%SZ)
case "$method$url" in
  POST*dispatches) echo "dispatch-ok" ;;
  *"/actions/workflows/fetch-columns.yml/runs"*)
    emit "{\\"workflow_runs\\":[{\\"id\\":111,\\"created_at\\":\\"$now_minus\\",\\"status\\":\\"completed\\"},{\\"id\\":222,\\"created_at\\":\\"$now_plus\\",\\"status\\":\\"in_progress\\"}]}" ;;
  *"/actions/runs/"*)
    n=$(cat "$COUNTER" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$COUNTER"
    if [ "$n" -lt 3 ]; then emit '{"status":"in_progress","conclusion":null}';
    else emit '{"status":"completed","conclusion":"success"}'; fi ;;
  *) echo "{}" ;;
esac
''')
    os.chmod(stub, 0o755)

    # küçük bir depo: origin/main + çalışma kopyası
    root = os.path.join(td, "heal")
    os.makedirs(root)
    sh = lambda *c, cwd=root: subprocess.run(c, cwd=cwd, capture_output=True, text=True)
    sh("git", "init", "-q", "--bare", "origin.git", "-b", "main", cwd=root)
    os.makedirs(os.path.join(root, "work", "data"))
    write(os.path.join(root, "work", "data", "daily.json"), yesterday,
          (now - timedelta(hours=13)).isoformat(), arts)
    writers(os.path.join(root, "work", "data", "writers.json"))
    sh("git", "init", "-q", "work", "-b", "main", cwd=root)
    sh("git", "-C", "work", "add", "-A", cwd=root)
    sh("git", "-C", "work", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "base", cwd=root)
    sh("git", "-C", "work", "remote", "add", "origin", "../origin.git", cwd=root)
    sh("git", "-C", "work", "push", "-q", "origin", "main", cwd=root)

    step = os.path.join(td, "heal.sh")
    open(step, "w", encoding="utf-8").write(heal["run"].replace("sleep 10", "sleep 0.2")
                                            .replace("sleep 30", "sleep 0.2"))
    env = dict(os.environ, PATH=stub_dir + os.pathsep + os.environ["PATH"],
               GITHUB_REPOSITORY="0xinspectorx0/kose", GITHUB_REF_NAME="main",
               GITHUB_OUTPUT=os.path.join(td, "heal-out.txt"),
               GITHUB_STEP_SUMMARY=os.path.join(td, "heal-sum.md"),
               RUNNER_TEMP=td, STUB_LOG=os.path.join(td, "gh.log"),
               STUB_COUNTER=os.path.join(td, "gh.counter"))
    p = subprocess.run(["bash", "-eo", "pipefail", step], cwd=os.path.join(root, "work"),
                       capture_output=True, text=True, env=env)
    outs = open(env["GITHUB_OUTPUT"], encoding="utf-8").read() if os.path.exists(env["GITHUB_OUTPUT"]) else ""
    log = open(env["STUB_LOG"], encoding="utf-8").read() if os.path.exists(env["STUB_LOG"]) else ""
    check("onarma adımı exit 0", p.returncode == 0, p.stdout[-200:] + p.stderr[-200:])
    check("dispatch POST atıldı", "method=POST" in log and "dispatches" in log)
    check("START'tan eski koşu değil, yeni koşu seçildi (id 222)", "run=222" in outs, outs.replace("\n", " "))
    check("koşunun bitmesi beklendi (en az 3 durum sorgusu)", log.count("/actions/runs/222") >= 3)
    check("healed=yes yazıldı", "healed=yes" in outs)
    check("conclusion=success yazıldı", "conclusion=success" in outs)

print()
if FAILS:
    print(f"{len(FAILS)} MADDE KALDI: {', '.join(FAILS)}")
    sys.exit(1)
print("TÜM WATCHDOG DENETİMLERİ GEÇTİ")
