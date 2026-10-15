#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-passive.py — "pasif yazarlar" hattının çevrimdışı denetimi
=================================================================
Pasif yazar özelliğinin kazıyıcı tarafını doğrular (ağ gerektirmez):

  * data/passive-writers.json okuma (eksik/bozuk dosya güvenli)
  * ad + gazete eşleşmesi (Türkçe büyük/küçük harf ve aksan farkı önemsenmez)
  * pasif yazarın yazısı daily.json'a YAZILMAZ (drop_passive_records)
  * pasif yazarın son yazısı DONDURULUR: tekrar çekilmez, "passive": true ile korunur
  * yazar dizininde pasif yazarın yazısı hiç indirilmez (is_passive_url)
  * writers.json'da pasif yazar "passive": true ile işaretlenir, eski işaret temizlenir
  * CLI'da --passive-file, workflow'da data/passive-writers.json push tetikleyicisi

Koşum:
    python3 patches/uitest/verify-passive.py
Beklenti: tüm maddeler "GEÇTİ", çıkış kodu 0.
"""
import json
import os
import re
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


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


PASSIVE = {"writers": [
    {"name": "Ahmet Hakan",
     "source": "Hürriyet",
     "url": "https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/"},
    {"name": "Sadece Isim"},                       # gazete belirtilmemiş: ad tek başına yeter
    {"name": "   "},                               # boş ad: atlanır
    "metin",                                       # sözlük değil: atlanır
    {"source": "Posta"},                           # adsız: atlanır
]}

print("\n[A] PASİF YAZAR DOSYASI (load_passive_writers)")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "passive-writers.json")
    write_json(path, PASSIVE)
    pas = fc.load_passive_writers(path)
    check("geçerli kayıtlar okundu", pas["total"] == 2, f"total={pas['total']}")
    check("kaynaklı kayıt (ad, gazete) çifti olarak saklandı",
          ("ahmet hakan", "hurriyet") in pas["pairs"])
    check("kaynaksız kayıt 'ad tek başına' kümesinde",
          "sadece isim" in pas["bare"])
    check("profil bağlantısı normalize edildi (sonda / yok, küçük harf)",
          "https://www.hurriyet.com.tr/yazarlar/ahmet-hakan" in pas["urls"],
          str(sorted(pas["urls"])))

    empty = fc.load_passive_writers(os.path.join(td, "yok.json"))
    check("olmayan dosya -> boş liste (çekim durmaz)",
          empty["total"] == 0 and not empty["names"] and not empty["urls"])

    broken = os.path.join(td, "bozuk.json")
    with open(broken, "w", encoding="utf-8") as f:
        f.write("{bu json degil")
    bad = fc.load_passive_writers(broken)
    check("bozuk dosya -> boş liste", bad["total"] == 0 and not bad["names"])

    write_json(path, {"writers": "liste değil"})
    check("'writers' liste değilse -> boş liste", fc.load_passive_writers(path)["total"] == 0)

print("\n[B] EŞLEŞME (is_passive_author / is_passive_record / is_passive_url)")
check("ad + gazete eşleşmesi (harf büyüklüğü önemsenmez)",
      fc.is_passive_author("AHMET HAKAN", "Hürriyet", pas) is True)
check("aynı ad BAŞKA gazetede pasif sayılmaz",
      fc.is_passive_author("Ahmet Hakan", "Posta", pas) is False)
check("aksansız/farklı yazım eşleşir (SADECE ISIM)",
      fc.is_passive_author("sadece isim", "T24", pas) is True)
check("kaynaksız kayıt her gazetede geçerli", fc.is_passive_author("Sadece Isim", "", pas) is True)
check("listede olmayan yazar pasif değil",
      fc.is_passive_author("Başka Yazar", "Hürriyet", pas) is False)
check("boş ad pasif sayılmaz", fc.is_passive_author("", "Hürriyet", pas) is False)
check("is_passive_record kaydın alanlarını kullanır",
      fc.is_passive_record({"author": "Ahmet Hakan", "source": "Hürriyet"}, pas) is True)
check("profil bağlantısı tanınıyor (sonda / olsa da)",
      fc.is_passive_url("https://www.hurriyet.com.tr/yazarlar/ahmet-hakan", pas) is True)
check("tanınmayan profil bağlantısı", fc.is_passive_url("https://www.hurriyet.com.tr/yazarlar/x", pas) is False)

print("\n[C] PASİF YAZI GÜNCELLENMESİN (drop_passive_records)")
records = [
    {"author": "Ahmet HAKAN", "source": "Hürriyet", "title": "pasif 1"},
    {"author": "Sadece Isim", "source": "T24", "title": "pasif 2"},
    {"author": "Ahmet Hakan", "source": "Posta", "title": "başka gazete, kalır"},
    {"author": "Başka Yazar", "source": "Hürriyet", "title": "kalır"},
]
kept = fc.drop_passive_records(records, pas)
check("pasif yazarların yazıları elendi",
      [r["title"] for r in kept] == ["başka gazete, kalır", "kalır"],
      str([r["title"] for r in kept]))
check("pasif liste boşsa kayıtlara dokunulmaz",
      fc.drop_passive_records(records, fc.empty_passive()) == records)

print("\n[D] DONMUŞ SON YAZI (carry_passive_records)")
now = datetime.now(timezone.utc)
previous = {"articles": [
    {"title": "Ahmet Hakan'ın son yazısı", "author": "Ahmet Hakan", "source": "Hürriyet",
     "publishedAt": (now - timedelta(hours=4)).isoformat(), "fullContent": "<p>x</p>"},
    {"title": "Aktif yazarın yazısı", "author": "Başka Yazar", "source": "Hürriyet",
     "publishedAt": (now - timedelta(hours=4)).isoformat()},
    {"title": "Başka gazetedeki aynı ad", "author": "Ahmet Hakan", "source": "Posta",
     "publishedAt": (now - timedelta(hours=4)).isoformat()},
]}
frozen = fc.carry_passive_records(previous, pas)
check("yalnızca pasif yazarın yazısı devralındı",
      [r["title"] for r in frozen] == ["Ahmet Hakan'ın son yazısı"],
      str([r["title"] for r in frozen]))
check("devralınan kayıt passive: true ile işaretli", frozen and frozen[0].get("passive") is True)
check("içerik olduğu gibi korunuyor (güncellenmiyor)",
      frozen[0]["fullContent"] == "<p>x</p>" and frozen[0]["title"] == "Ahmet Hakan'ın son yazısı")
check("önceki veri değiştirilmedi (kopya alınıyor)",
      "passive" not in previous["articles"][0])
check("pasif liste boşsa devralma yok", fc.carry_passive_records(previous, fc.empty_passive()) == [])

merged = frozen + [{"title": "yeni", "author": "Başka Yazar", "source": "Hürriyet",
                    "publishedAt": now.isoformat()}]
old_frozen = dict(frozen[0], publishedAt=(now - timedelta(days=5)).isoformat())
check("2 günden eski donmuş yazı yaş filtresine takılır (akış bayat görünmesin)",
      [r["title"] for r in fc.drop_stale_records([old_frozen] + merged, 2)] == ["yeni", "Ahmet Hakan'ın son yazısı"]
      or [r["title"] for r in fc.drop_stale_records([old_frozen] + merged, 2)] == ["Ahmet Hakan'ın son yazısı", "yeni"],
      str([r["title"] for r in fc.drop_stale_records([old_frozen] + merged, 2)]))

print("\n[E] YAZAR DİZİNİ (writers.json işaretleri + erken atlama)")
writers_data = {"total": 0, "papers": [{"key": "hurriyet", "name": "Hürriyet", "writers": [
    {"name": "Ahmet Hakan"},
    {"name": "Ahmet Hakan", "passive": True},   # eski işaret: pasif artık değilse temizlenir
    {"name": "Sadece Isim"},
    {"name": "Başka Yazar"},
]}]}
# Eski işareti olan ama artık listede OLMAYAN bir yazarla karışık senaryo:
writers_data["papers"][0]["writers"][1]["name"] = "Pasiften Cikarilan"
marked = fc.mark_passive_writers(writers_data, pas)
check("pasif yazarlar işaretlendi", marked == 2, f"işaretlenen={marked}")
check("writers.json'da passive: true",
      writers_data["papers"][0]["writers"][0].get("passive") is True)
check("listeden çıkarılan yazarın eski işareti silindi",
      "passive" not in writers_data["papers"][0]["writers"][1])
check("pasif olmayan yazar işaretsiz",
      "passive" not in writers_data["papers"][0]["writers"][3])

# gazete yöneticisi modu: pasif yazarın yazısı hiç indirilmemeli
paper = {
    "key": "ornek", "name": "Örnek", "mode": "authors",
    "today": "https://ornek.test/yazarlar",
    "author_pattern": r"/yazarlar/[^/]+/?$",
    "article_pattern": r"/yazarlar/[^/]+/[^/]+$",
    "author_denylist": [""],
}
fetched = []


def fake_fetch(url):
    fetched.append(url)
    return '<html><a href="%s">y</a></html>' % url


orig = (fc.fetch, fc.extract_links, fc.safe_parse_article)
try:
    fc.fetch = fake_fetch
    def fake_extract(html, base, pattern, denylist=None, limit=None):
        # Yazar dizininden gelen adresler: ilki pasif listenin profil bağlantısıyla AYNI
        if base.rstrip("/") == paper["today"]:
            return ["https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/",
                    "https://ornek.test/yazarlar/baska-yazar/"]
        return [base.rstrip("/") + "/yazi-1"]

    fc.extract_links = fake_extract
    fc.safe_parse_article = lambda url, sub: {"author": sub.get("author") or url,
                                              "title": url, "source": sub["name"]}
    recs = fc.fetch_paper_articles(paper, 5, pas)
finally:
    fc.fetch, fc.extract_links, fc.safe_parse_article = orig
check("pasif yazarın adresi hiç indirilmedi",
      "https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/" not in fetched, str(fetched))
check("pasif olmayan yazarın adresi indirildi",
      "https://ornek.test/yazarlar/baska-yazar/" in fetched)
check("pasif yazar için kayıt üretilmedi (yalnızca aktif yazarın yazısı)",
      len(recs) == 1 and "baska-yazar" in recs[0]["title"] and not any("ahmet-hakan" in r["title"] for r in recs),
      str([r["title"] for r in recs]))

print("\n[F] CLI / WORKFLOW / DOSYA")
src = open(os.path.join(REPO, "scripts", "fetch_columns.py"), encoding="utf-8").read()
check("CLI'da --passive-file var", 'ap.add_argument("--passive-file"' in src)
check("varsayılan dosya data/passive-writers.json",
      fc.PASSIVE_FILE_DEFAULT == "data/passive-writers.json")
check("çekimden önce pasif liste okunuyor", "load_passive_writers(args.passive_file)" in src)
check("pasif kayıtlar çıktıya yazılmadan önce eleniyor",
      "records = drop_passive_records(records, passive)" in src)
check("donmuş kayıtlar devralınıyor", "carry_passive_records(load_payload(args.out), passive)" in src)
check("writers.json pasif işaretlemesi kayıttan önce",
      src.index("mark_passive_writers(writers_data, passive)") < src.index("save_writers(writers_data, args.writers_out)"))

repo_file = os.path.join(REPO, "data", "passive-writers.json")
check("data/passive-writers.json depoda", os.path.exists(repo_file))
if os.path.exists(repo_file):
    with open(repo_file, encoding="utf-8") as f:
        cfg = json.load(f)
    check("dosya geçerli JSON ve 'writers' listesi", isinstance(cfg.get("writers"), list))
    check("başlangıçta boş liste (kimse pasif değil)", cfg.get("writers") == [])

wf = open(os.path.join(REPO, ".github", "workflows", "fetch-columns.yml"), encoding="utf-8").read()
check("workflow pasif liste değişince zorla çekim tetikliyor",
      "'data/passive-writers.json'" in wf and re.search(r"- 'data/passive-writers\.json'", wf) is not None)

print()
if FAILS:
    print(f"{len(FAILS)} MADDE KALDI: {', '.join(FAILS)}")
    sys.exit(1)
print("TÜM PASİF YAZAR HAT DENETİMLERİ GEÇTİ")
