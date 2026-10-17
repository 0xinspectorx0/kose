#!/usr/bin/env python3
"""Zamanlayıcı (30 dk röle) iş akışının çevrimdışı doğrulaması.

1. Yapı: tetikleyiciler, izinler, concurrency, ortam (deployment: false),
   işlerin paralel olması, run betiklerinde ${{ inputs.* }} enjeksiyonu yok.
2. Davranış: iki run betiği sahte `gh` / `sleep` / `scripts/freshness.py`
   ile bash'te koşturulur; her senaryoda hangi API çağrılarının yapıldığı,
   çıkış kodu ve uyarılar denetlenir.

Çalıştırma (depo kökünden):  .venv/bin/python patches/uitest/verify-relay.py
"""
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF_PATH = ROOT / ".github" / "workflows" / "zamanlayici.yml"
REPO = "0xinspectorx0/kose"

failures = []


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- 1. yapı
print("YAPI")
wf = yaml.safe_load(WF_PATH.read_text(encoding="utf-8"))
on = wf.get("on", wf.get(True))  # PyYAML 'on' anahtarını True okur
check(isinstance(on, dict), "tetikleyiciler okunabildi")
check("halka" in on["workflow_dispatch"]["inputs"], "workflow_dispatch 'halka' girdisi var")
check(on["workflow_dispatch"]["inputs"]["halka"].get("default") == "0", "halka varsayılanı '0'")
check(".github/workflows/zamanlayici.yml" in on["push"]["paths"], "push yalnızca bu dosya değişince")
check(on["push"]["branches"] == ["main"], "push yalnızca main (geçici dal tetikleyicisi kaldırılmış)")
check("inputs.halka" in wf.get("run-name", ""), "koşu başlığı halka numarasını gösterir (run-name)")
check(bool(on.get("schedule")), "kopan zinciri yeniden başlatan seyrek cron var")
check(wf["permissions"] == {"contents": "read", "actions": "write"}, "izinler: contents read + actions write (fazlası yok)")
conc = wf["concurrency"]
check("kose-zamanlayici" in conc["group"] and "github.ref_name" in conc["group"], "concurrency dal başına tek zincir")
check(conc["cancel-in-progress"] is False, "cancel-in-progress: false (bekleyen halka iptal edilmez)")
jobs = wf["jobs"]
check(set(jobs) == {"kontrol", "sonraki"}, "iki iş: kontrol + sonraki")
check("needs" not in jobs["kontrol"] and "needs" not in jobs["sonraki"], "işler paralel (kontrol beklemeye takılmaz)")
check("environment" not in jobs["kontrol"], "kontrol ortam beklemesine tabi değil (hemen koşar)")
env = jobs["sonraki"]["environment"]
check(env.get("name") == "kose-zamanlayici", "sonraki: ortam kose-zamanlayici")
check(env.get("deployment") is False, "sonraki: deployment: false (dağıtım kaydı yok)")
for name, job in jobs.items():
    check(int(job.get("timeout-minutes", 999)) <= 10, f"{name}: timeout-minutes ≤ 10")
    for st in job["steps"]:
        run = st.get("run", "")
        check("${{" not in run, f"{name}/{st.get('name')}: run betiğinde ${{{{ }}}} yok (girdiler env ile)")

ck = jobs["kontrol"]["steps"][0]
check(ck.get("uses", "").startswith("actions/checkout@"), "kontrol: checkout")
check(ck["with"]["ref"] == "${{ github.event.repository.default_branch }}", "kontrol: veriyi her zaman main'den okur")
KONTROL_RUN = jobs["kontrol"]["steps"][1]["run"]
SONRAKI_RUN = jobs["sonraki"]["steps"][0]["run"]

# --------------------------------------------------------- 2. davranış
FAKE_GH = r'''#!/usr/bin/env bash
# Sahte gh: çağrıyı kaydeder, senaryoya göre yanıt verir.
printf '%s\n' "$*" >> "$GH_LOG"
args="$*"
case "$args" in
  *"-X POST"*"fetch-columns.yml/dispatches"*) exit "${FAKE_FETCH_RC:-0}" ;;
  *"-X POST"*"zamanlayici.yml/dispatches"*)   exit "${FAKE_NEXT_RC:-0}" ;;
  *"fetch-columns.yml/runs"*)
     [ -n "$FAKE_ACTIVE_FAIL" ] && exit 1; echo "${FAKE_ACTIVE:-0}"; exit 0 ;;
  *"/actions/runs/"*)
     [ -n "$FAKE_RUN_FAIL" ] && exit 1; echo "$FAKE_STARTED"; exit 0 ;;
  *"/environments/"*)
     [ -n "$FAKE_TIMER_FAIL" ] && { echo '{"message":"Not Found"}' >&2; exit 1; }; echo "${FAKE_TIMER:-0}"; exit 0 ;;
esac
echo "beklenmeyen gh çağrısı: $args" >&2
exit 3
'''

FAKE_FRESHNESS = r'''import os, sys
if os.environ.get("FAKE_FRESH_SILENT"):
    sys.exit(int(os.environ.get("FAKE_FRESH_RC", "1")))
print("needed=" + os.environ.get("FAKE_NEEDED", "false"))
print("reason=" + os.environ.get("FAKE_REASON", "test gerekçesi"))
sys.exit(int(os.environ.get("FAKE_FRESH_RC", "0")))
'''


# Sahte kaynak kuralı kontrolü: çağrıldığını işaretler, senaryoya göre karar basar
FAKE_KURAL = r'''import os, sys
open("kural-cagrildi", "w").write("1")
if os.environ.get("FAKE_KURAL_CRASH"):
    raise SystemExit(3)
print("degisti=" + os.environ.get("FAKE_KURAL_DEGISTI", "false"))
print("neden=" + os.environ.get("FAKE_KURAL_NEDEN", "kural test gerekçesi"))
'''


def iso_minutes_ago(m):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=m)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_script(script, **scenario):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH)
        (bindir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
        for f in ("gh", "sleep"):
            (bindir / f).chmod(0o755)
        (tmp / "scripts").mkdir()
        (tmp / "scripts" / "freshness.py").write_text(FAKE_FRESHNESS)
        (tmp / "scripts" / "kaynak_kurallari.py").write_text(FAKE_KURAL)
        (tmp / "data").mkdir()
        (tmp / "data" / "daily.json").write_text("{}")
        log = tmp / "gh.log"
        log.write_text("")
        summary = tmp / "summary.md"
        summary.write_text("")
        envv = {
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "HOME": str(tmp),
            "GH_LOG": str(log),
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_RUN_ID": "123",
            "GITHUB_EVENT_NAME": scenario.pop("event", "workflow_dispatch"),
            "GITHUB_REF_NAME": scenario.pop("ref", "main"),
            "GITHUB_STEP_SUMMARY": str(summary),
            "ANA_DAL": "main",
            "ORTAM": "kose-zamanlayici",
            "EN_AZ_BEKLEME_DK": "20",
            "HALKA": scenario.pop("halka", "0"),
        }
        envv.update({k: str(v) for k, v in scenario.items()})
        # GitHub Actions run adımları `bash -e {0}` ile koşar
        p = subprocess.run(["bash", "-e", "-c", script], cwd=tmp, env=envv,
                           capture_output=True, text=True, timeout=60)
        calls = [c for c in log.read_text().splitlines() if c]
        run_script.kural_cagrildi = (tmp / "kural-cagrildi").exists()
        return p.returncode, p.stdout + p.stderr, calls, summary.read_text()


def posts(calls, wf_name):
    return [c for c in calls if "-X POST" in c and f"{wf_name}/dispatches" in c]


print("\nKONTROL İŞİ")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false")
check(rc == 0 and not posts(calls, "fetch-columns.yml") and "gerekmedi" in summ,
      "veri taze → çekim tetiklenmez")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="true", FAKE_ACTIVE="0")
p = posts(calls, "fetch-columns.yml")
check(rc == 0 and len(p) == 1 and "ref=main" in p[0], "bayat veri → fetch-columns main'de 1 kez tetiklenir")
check("::notice title=Çekim tetiklendi::" in out, "tetikleme notu düşülür")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="true", FAKE_ACTIVE="2")
check(rc == 0 and not posts(calls, "fetch-columns.yml") and "atlandı" in summ,
      "main'de süren çekim varsa ikincisi açılmaz")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="true", FAKE_ACTIVE_FAIL="1")
check(rc == 0 and len(posts(calls, "fetch-columns.yml")) == 1,
      "süren çekim sorgusu hata verirse yine de tetiklenir (güvenli taraf)")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="true", FAKE_FETCH_RC="1")
check(rc == 0 and len(posts(calls, "fetch-columns.yml")) == 3 and "::error title=Çekim tetiklenemedi::" in out,
      "tetikleme hatası → 3 deneme, hata notu, iş yine de 0 ile biter")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_FRESH_SILENT="1", FAKE_FRESH_RC="1")
check(rc == 0 and len(posts(calls, "fetch-columns.yml")) == 1 and "güvenli taraf" in summ,
      "karar betiği çökerse güvenli taraf: çekim istenir")

rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false", halka='1"; touch PWNED; echo "')
check(rc == 0 and "Halka:** 0" in summ, "zararlı halka girdisi 0'a indirgenir")

print("\nKONTROL İŞİ — yönetici kaynak kuralları")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false", FAKE_KURAL_DEGISTI="true",
                                  FAKE_KURAL_NEDEN="kurallar 10 dk önce değişti")
p = posts(calls, "fetch-columns.yml")
check(rc == 0 and len(p) == 1 and "inputs[force]=true" in p[0] and "ref=main" in p[0],
      "veri taze ama kurallar değişti → fetch-columns force=true ile 1 kez tetiklenir")
check("kaynak kuralları değişti" in summ and "10 dk önce" in summ, "gerekçe özette (kural değişikliği)")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false", FAKE_KURAL_DEGISTI="false")
check(rc == 0 and not posts(calls, "fetch-columns.yml") and run_script.kural_cagrildi,
      "veri taze, kurallar değişmedi → çekim yok (kural kontrolü yapıldı)")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="true", FAKE_ACTIVE="0", FAKE_KURAL_DEGISTI="true")
p = posts(calls, "fetch-columns.yml")
check(rc == 0 and len(p) == 1 and "inputs[force]=false" in p[0] and not run_script.kural_cagrildi,
      "veri zaten bayat → normal (force'suz) çekim; kural kontrolüne gerek kalmaz")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false", FAKE_KURAL_CRASH="1")
check(rc == 0 and not posts(calls, "fetch-columns.yml") and "gerekmedi" in summ,
      "kural kontrolü çökerse zincir düşmez, çekim de açılmaz")
rc, out, calls, summ = run_script(KONTROL_RUN, FAKE_NEEDED="false", FAKE_KURAL_DEGISTI="true", FAKE_ACTIVE="1")
check(rc == 0 and not posts(calls, "fetch-columns.yml") and "atlandı" in summ,
      "kural değişti ama süren çekim var → ikincisi açılmaz")

print("\nSONRAKİ İŞİ (bekleme kilidi + zincir)")
rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(1), FAKE_TIMER="0")
check(rc == 0 and not posts(calls, "zamanlayici.yml"), "bekleme süresi yok (1 dk) → zincir DURUR")
check("::error title=Zamanlayıcı kurulu değil" in out and "Wait timer" in summ, "kurulum talimatı hata notunda ve özette")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30", halka="5")
p = posts(calls, "zamanlayici.yml")
check(rc == 0 and len(p) == 1 and "ref=main" in p[0] and "inputs[halka]=6" in p[0],
      "31 dk bekledi, süre 30 → main'de halka 6 tetiklenir")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="10")
check(rc == 0 and not posts(calls, "zamanlayici.yml") and "10 dk" in out, "ortam süresi 10 dk (< 20) → zincir durur")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER_FAIL="1")
check(rc == 0 and len(posts(calls, "zamanlayici.yml")) == 1, "ortam okunamazsa geçen süre kilidi yeterli → zincir sürer")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_RUN_FAIL="1", FAKE_TIMER="30")
check(rc == 0 and not posts(calls, "zamanlayici.yml"), "koşu başlangıcı okunamazsa güvenli taraf: zincir durur")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30",
                                  ref="test-dali", halka="0", event="push")
p = posts(calls, "zamanlayici.yml")
check(rc == 0 and len(p) == 1 and "ref=test-dali" in p[0] and "inputs[halka]=1" in p[0],
      "test dalı, push ile başlayan halka 0 → aynı dalda halka 1 tetiklenir")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30",
                                  ref="test-dali", halka="1", event="workflow_dispatch")
check(rc == 0 and not posts(calls, "zamanlayici.yml") and "Test zinciri bitti" in summ,
      "test dalı, tetiklenmiş halka 1 → zincir biter")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30",
                                  ref="test-dali", halka="0", event="workflow_dispatch")
check(rc == 0 and not posts(calls, "zamanlayici.yml"),
      "test dalı, girdi kaybolmuş tetiklenmiş halka (0) → yine biter (girdiye bağlı değil)")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30",
                                  ref="main", halka="0", event="schedule")
p = posts(calls, "zamanlayici.yml")
check(rc == 0 and len(p) == 1 and "ref=main" in p[0] and "inputs[halka]=1" in p[0],
      "main'de cron ile yeniden başlatılan zincir halka 1 ile sürer")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30", FAKE_NEXT_RC="1")
check(rc == 1 and len(posts(calls, "zamanlayici.yml")) == 5 and "::error title=Zincir koptu::" in out,
      "sonraki halka tetiklenemezse 5 deneme, kırmızı koşu + talimat")

rc, out, calls, summ = run_script(SONRAKI_RUN, FAKE_STARTED=iso_minutes_ago(31), FAKE_TIMER="30", halka="abc")
p = posts(calls, "zamanlayici.yml")
check(rc == 0 and len(p) == 1 and "inputs[halka]=1" in p[0], "sayı olmayan halka 0 sayılır")

print()
if failures:
    print(f"BAŞARISIZ: {len(failures)} madde")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("TÜM ZAMANLAYICI TESTLERİ GEÇTİ")
