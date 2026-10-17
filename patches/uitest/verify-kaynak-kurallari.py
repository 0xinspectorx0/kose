#!/usr/bin/env python3
"""Yönetici kaynak kuralları — kazıyıcı tarafı (ağ gerektirmez).

1. writer_key (Python) == favKeyName (uygulama, JS) — gerçek veri adları + zor örnekler
2. Kuralların doğrulanması (geçersiz/iç ağ girdileri elenir)
3. Kural ucu: başarılı / kurulum eksik (503) / bozuk yanıt -> önceki kurallar / kuralsız
4. Röle kararı: kurallar son çekimden sonra değişti mi? (+ komut satırı --kontrol)
5. Akış çözümleme: doğrudan akış, <link rel=alternate>, /feed/ yedeği, YouTube @kanal, önbellek
6. fetch_columns.main uçtan uca: pasif kaynak taranmaz, pasif yazar elenir, eklenen akışlar
   okunur, data/kaynaklar.json kataloğu yazılır; uç düşünce önceki kurallar uygulanır

Çalıştırma: .venv/bin/python patches/uitest/verify-kaynak-kurallari.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import kaynak_kurallari as kk  # noqa: E402
import fetch_columns as fc  # noqa: E402

GECEN, HATA = 0, 0


def check(ad, kosul, ayrinti=""):
    global GECEN, HATA
    if kosul:
        GECEN += 1
        print(f"  ✓ {ad}")
    else:
        HATA += 1
        print(f"  ✗ {ad}{' — ' + str(ayrinti) if ayrinti else ''}")


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
print("1) Yazar anahtarı: Python == uygulama (JS)")
ornekler = ["Ahmet HAKAN", "ahmet hakan", "  Ahmet   Hakan ", "KILIÇ", "Kılıç", "İLBER ORTAYLI", "Işık Kansu",
            "Abdulkadir SELVİ", "ABDULKADİR SELVİ", "Şükrü Küçükşahin", "ÇİĞDEM TOKER", "İlke Gürsoy 15 Yazı",
            "Adnan Ekinci | Hukuk Ombudsmanı", "M. Serdar Kuzuloğlu", "Zülfü Livaneli", "Ünal Çeviköz",
            "Ömer Taşpınar", "Gökçer Tahincioğlu", "Âşık Veysel", "Nagehan Alçı", "Ş\u0327ahin"]
with open(os.path.join(REPO, "data", "daily.json"), encoding="utf-8") as f:
    ornekler += sorted({a.get("author", "") for a in json.load(f)["articles"]})
with open(os.path.join(REPO, "data", "writers.json"), encoding="utf-8") as f:
    ornekler += [w.get("name", "") for p in json.load(f)["papers"] for w in p.get("writers", [])][:600]
html = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()


def js_fn(ad):
    i = html.index(f"function {ad}(")
    d, j = 0, html.index("{", i)
    while True:
        if html[j] == "{":
            d += 1
        elif html[j] == "}":
            d -= 1
            if d == 0:
                return html[i:j + 1]
        j += 1


js = "\n".join(js_fn(n) for n in ("cleanWriterName", "deaccentTr", "favKeyName")) + \
    "\nconst ad = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(ad.map(favKeyName)));"
p = subprocess.run(["node", "-e", js], input=json.dumps(ornekler), capture_output=True, text=True, timeout=60)
js_keys = json.loads(p.stdout) if p.returncode == 0 else []
py_keys = [kk.writer_key(n) for n in ornekler]
farklar = [(n, a, b) for n, a, b in zip(ornekler, py_keys, js_keys) if a != b]
check(f"{len(ornekler)} adın hepsinde aynı anahtar", p.returncode == 0 and not farklar, farklar[:5] or p.stderr[:300])
check("büyük/küçük ve aksan farkı tek anahtar", kk.writer_key("KILIÇ") == kk.writer_key("Kılıç") == "kilic")
check("İ/I Türkçe kuralıyla", kk.writer_key("İLBER ORTAYLI") == "ilber ortayli")
check("dizin ekleri atılır", kk.writer_key("İlke Gürsoy 15 Yazı") == "ilke gursoy" and kk.writer_key("Adnan Ekinci | X") == "adnan ekinci")

# ---------------------------------------------------------------------------
print("2) Kuralların doğrulanması")
ham = {
    "ok": True, "surum": 4, "guncellendi": iso(NOW),
    "pasif": {"kaynaklar": [{"key": "bgazete", "ad": "B Gazete"}, {"key": "Bozuk Anahtar!"}, "x"],
              "yazarlar": [{"anahtar": "y:pasif yazar", "ad": "PASİF Yazar"}, {"ad": ""}]},
    "ek": [
        {"key": "ek-1234abcd", "name": "Ek Blog", "author": "Ek Yazar", "category": "Ekonomi", "feed": "https://ek.example/blog"},
        {"key": "ek-5678abcd", "name": "Kanal", "author": "", "category": "Magazin", "feed": "https://www.youtube.com/@kanal"},
        {"key": "ek-9999abcd", "name": "İç ağ", "feed": "http://127.0.0.1:8080/feed"},
        {"key": "ek-aaaaaaaa", "name": "Meta", "feed": "http://169.254.169.254/latest"},
        {"key": "ek-bbbbbbbb", "name": "FTP", "feed": "ftp://x.example/rss"},
        {"key": "yanlis", "name": "Anahtarsız", "feed": "https://y.example/rss"},
        {"key": "ek-1234abcd", "name": "Tekrar", "feed": "https://z.example/rss"},
    ],
}
kur = kk.kurallari_dogrula(ham)
check("geçerli pasif kaynak kaldı, bozuklar elendi", [p["key"] for p in kur["pasif"]["kaynaklar"]] == ["bgazete"])
check("pasif yazar anahtarı addan yeniden hesaplanır", kur["pasif"]["yazarlar"] == [{"ad": "PASİF Yazar", "anahtar": "y:pasif yazar"}])
check("iç ağ / meta / ftp / biçimsiz / tekrar eklenen kaynaklar elendi", [e["key"] for e in kur["ek"]] == ["ek-1234abcd", "ek-5678abcd"], kur["ek"])
check("bilinmeyen kategori Gündem, boş yazar = kaynak adı", kur["ek"][1]["category"] == "Gündem" and kur["ek"][1]["author"] == "Kanal")
check("bozuk girdi boş kurala iner", kk.kurallari_dogrula("bozuk") == kk.bos_kurallar() and kk.kurallari_dogrula({"surum": "x"})["surum"] == 0)
check("en çok 40 eklenen kaynak", len(kk.kurallari_dogrula({"ek": [
    {"key": f"ek-{i:08x}", "name": f"B{i}", "feed": f"https://b{i}.example/rss"} for i in range(60)]})["ek"]) == 40)
check("pasif kümeleri", kk.pasif_kaynak_anahtarlari(kur) == {"bgazete"} and kk.pasif_yazar_anahtarlari(kur) == {"pasif yazar"})
kur_pasif_ek = kk.kurallari_dogrula({**ham, "pasif": {"kaynaklar": [{"key": "ek-5678abcd"}], "yazarlar": []}})
check("pasife alınan eklenen kaynak çekilmez", [e["key"] for e in kk.ek_akis_kaynaklari(kur_pasif_ek)] == ["ek-1234abcd"])

# ---------------------------------------------------------------------------
print("3) Kural ucu ve yedekler")
YANITLAR = {}


class Isleyici(BaseHTTPRequestHandler):
    def do_GET(self):
        durum, govde = YANITLAR.get(self.path.split("?")[0], (404, {"ok": False, "hata": "yok"}))
        veri = govde if isinstance(govde, bytes) else json.dumps(govde).encode("utf-8")
        self.send_response(durum)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(veri)))
        self.end_headers()
        self.wfile.write(veri)

    def log_message(self, *a):
        pass


sunucu = ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
threading.Thread(target=sunucu.serve_forever, daemon=True).start()
TABAN = f"http://127.0.0.1:{sunucu.server_address[1]}"
YANITLAR["/ok"] = (200, ham)
YANITLAR["/kurulum"] = (503, {"ok": False, "kod": "kurulum", "hata": "Sunucu kurulumu eksik"})
YANITLAR["/bozuk"] = (200, b"<html>bu json degil</html>")

k1, h1 = kk.kurallari_indir(f"{TABAN}/ok")
check("uç: kurallar alındı", h1 is None and k1["surum"] == 4 and len(k1["ek"]) == 2)
k2, h2 = kk.kurallari_indir(f"{TABAN}/kurulum")
check("uç: 503 hata metniyle döner", k2 is None and "503" in h2 and "kurulumu eksik" in h2, h2)
k3, h3 = kk.kurallari_indir(f"{TABAN}/bozuk")
check("uç: bozuk yanıt reddedilir", k3 is None and h3)
with tempfile.TemporaryDirectory() as td:
    yol = os.path.join(td, "kaynaklar.json")
    k, kaynak, notu = kk.kurallari_yukle(f"{TABAN}/kurulum", yol)
    check("önceki dosya yoksa kuralsız (yok)", kaynak == "yok" and k == kk.bos_kurallar(), notu)
    kk.katalog_yaz(yol, {"kurallar": k1, "katalog": []})
    k, kaynak, notu = kk.kurallari_yukle(f"{TABAN}/kurulum", yol)
    check("uç düşünce son çekimin kuralları (onceki)", kaynak == "onceki" and kk.pasif_kaynak_anahtarlari(k) == {"bgazete"}, notu)
    k, kaynak, notu = kk.kurallari_yukle("yok", yol)
    check("'yok' adresiyle kurallar kapalı", kaynak == "yok" and k == kk.bos_kurallar())
    k, kaynak, notu = kk.kurallari_yukle(f"{TABAN}/ok", yol)
    check("uç çalışınca api", kaynak == "api" and "sürüm 4" in notu, notu)

# ---------------------------------------------------------------------------
print("4) Röle kararı: kurallar son çekimden sonra değişti mi?")
d, n = kk.kurallar_degisti_mi(None, {})
check("uç okunamadıysa hayır", d is False)
d, n = kk.kurallar_degisti_mi({"guncellendi": None}, {})
check("hiç kural tanımlanmamışsa hayır", d is False, n)
d, n = kk.kurallar_degisti_mi({"guncellendi": iso(NOW)}, None)
check("katalog yoksa (yeni kod ilk kez) evet", d is True, n)
d, n = kk.kurallar_degisti_mi({"guncellendi": iso(NOW)}, {"kurallarAlindi": iso(NOW - timedelta(minutes=20))})
check("kurallar son çekimden sonra değiştiyse evet", d is True, n)
d, n = kk.kurallar_degisti_mi({"guncellendi": iso(NOW - timedelta(minutes=20))}, {"kurallarAlindi": iso(NOW)})
check("son çekim güncel kuralları aldıysa hayır (döngü yok)", d is False, n)
with tempfile.TemporaryDirectory() as td:
    yol = os.path.join(td, "kaynaklar.json")
    out = os.path.join(td, "gh_out")
    kk.katalog_yaz(yol, {"kurallarAlindi": iso(NOW - timedelta(hours=2))})
    YANITLAR["/degisti"] = (200, {**ham, "guncellendi": iso(NOW - timedelta(minutes=5))})
    cli = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "kaynak_kurallari.py"), "--kontrol", "--data", yol,
                          "--url", f"{TABAN}/degisti", "--github-output"],
                         capture_output=True, text=True, env=dict(os.environ, GITHUB_OUTPUT=out), timeout=60)
    check("komut satırı: degisti=true (+ GITHUB_OUTPUT)", "degisti=true" in cli.stdout and "degisti=true" in open(out).read(), cli.stdout + cli.stderr)
    cli = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "kaynak_kurallari.py"), "--kontrol", "--data", yol,
                          "--url", f"{TABAN}/kurulum"], capture_output=True, text=True, timeout=60)
    check("komut satırı: uç 503 ise degisti=false, çıkış 0", cli.returncode == 0 and "degisti=false" in cli.stdout and "503" in cli.stdout, cli.stdout)

# ---------------------------------------------------------------------------
print("5) Akış çözümleme")
RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>T</title>
{items}</channel></rss>"""
ITEM = """<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate>
<description><![CDATA[<p>{t} için yeterince uzun bir paragraf metni burada yer alıyor, otuz karakterden fazla.</p>]]></description></item>"""
ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
<title>Kanal</title><entry><title>Video yazısı</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
<published>{d}</published><media:group><media:description>Bu videonun açıklaması da otuz karakterden uzun bir metin içeriyor.</media:description></media:group></entry></feed>"""
rfc = NOW.strftime("%a, %d %b %Y %H:%M:%S +0000")
SAYFALAR = {
    "https://dogrudan.example/rss": RSS.format(items=ITEM.format(t="Doğrudan", u="https://dogrudan.example/1", d=rfc)),
    "https://ek.example/blog": '<html><head><link rel="alternate" type="application/rss+xml" href="/blog/feed.xml"></head><body>blog</body></html>',
    "https://ek.example/blog/feed.xml": RSS.format(items=ITEM.format(t="Blog yazısı bir", u="https://ek.example/blog/1", d=rfc)
                                                   + ITEM.format(t="Blog yazısı iki", u="https://ek.example/blog/2", d=rfc)),
    "https://wp.example/": "<html><head><title>WP</title></head></html>",
    "https://wp.example/feed/": RSS.format(items=ITEM.format(t="WP yazısı", u="https://wp.example/1", d=rfc)),
    "https://www.youtube.com/@kanal": '<html><script>var x = {"channelId":"UCQmDWRUf_X8BSrrDOSZA-NA"};</script></html>',
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCQmDWRUf_X8BSrrDOSZA-NA": ATOM.format(d=iso(NOW)),
    "https://bos.example/": "<html><head><link rel='alternate' type='application/rss+xml' href='http://10.0.0.5/feed'></head></html>",
    "https://gazete-a.example/bugun": "<html>a</html>",
}
ISTEKLER = []


def sahte_fetch(url):
    ISTEKLER.append(url)
    return SAYFALAR.get(url)


fc.fetch = sahte_fetch
u, x, dr = fc.resolve_feed("https://dogrudan.example/rss")
check("doğrudan akış olduğu gibi", u == "https://dogrudan.example/rss" and dr == "ok" and fc.looks_like_feed(x))
u, x, dr = fc.resolve_feed("https://ek.example/blog")
check("<link rel=alternate> ile akış bulundu", u == "https://ek.example/blog/feed.xml" and dr == "ok", (u, dr))
u, x, dr = fc.resolve_feed("https://wp.example/")
check("link yoksa /feed/ yedeği (WordPress)", u == "https://wp.example/feed/" and dr == "ok", (u, dr))
u, x, dr = fc.resolve_feed("https://www.youtube.com/@kanal")
check("YouTube @kanal -> kanal akışı", u == "https://www.youtube.com/feeds/videos.xml?channel_id=UCQmDWRUf_X8BSrrDOSZA-NA" and dr == "ok", (u, dr))
ISTEKLER.clear()
u, x, dr = fc.resolve_feed("https://bos.example/")
check("iç ağa işaret eden aday denenmez; akış yok", dr == "akis-yok" and not any("10.0.0.5" in i for i in ISTEKLER), ISTEKLER)
check("istek sayısı sınırlı (en çok 4)", len(ISTEKLER) <= 4, ISTEKLER)
u, x, dr = fc.resolve_feed("https://ulasilamaz.example/")
check("ulaşılamayan adres", u is None and dr == "erisilemedi")
ISTEKLER.clear()
u, x, dr = fc.resolve_feed("https://ek.example/blog", cached="https://ek.example/blog/feed.xml")
check("önceki çekimde çözülen akış tek istekle kullanılır", u == "https://ek.example/blog/feed.xml" and ISTEKLER == ["https://ek.example/blog/feed.xml"], ISTEKLER)
check("HTML akış sanılmaz", not fc.looks_like_feed("<html><body><rss>") and fc.looks_like_feed("\ufeff<?xml version='1.0'?>\n<feed xmlns='x'>"))

# ---------------------------------------------------------------------------
print("6) Kazıyıcı uçtan uca (sahte kaynaklarla)")
A = {"key": "agazete", "name": "A Gazete", "category": "Gündem", "mode": "today", "today": "https://gazete-a.example/bugun",
     "roster": None, "article_pattern": r"x", "author_pattern": None}
B = {"key": "bgazete", "name": "B Gazete", "category": "Gündem", "mode": "today", "today": "https://gazete-b.example/bugun",
     "roster": None, "article_pattern": r"x", "author_pattern": None}
F = {"key": "dogrudan", "name": "Doğrudan Blog", "category": "Ekonomi", "author": "Blog Yazarı", "feed": "https://dogrudan.example/rss"}
fc.NEWSPAPERS, fc.PERSONAL_SOURCES, fc.FEED_SOURCES = [A, B], [], [F]
taranan_gazeteler, kesif_gazeteleri = [], []


def sahte_kesif(maks, papers=None):
    kesif_gazeteleri.append([p["key"] for p in papers])
    return {"papers": [{"key": p["key"], "name": p["name"], "count": 2,
                        "writers": [{"name": "Pasif YAZAR", "url": f"https://{p['key']}/pasif", "photo": ""},
                                    {"name": "Kalan Yazar", "url": f"https://{p['key']}/kalan", "photo": ""}]} for p in papers],
            "total": 2 * len(papers)}


def sahte_gazete(paper, maks):
    taranan_gazeteler.append(paper["key"])
    blocks = [("p", "Gazete köşe yazısının gövdesi otuz karakterden uzun bir paragraf.")]
    simdi = datetime.now(fc.TR_TZ)
    return [fc.build_record(paper["key"], paper["name"], paper["category"], yazar, f"{paper['name']} {i} {yazar}",
                            f"https://{paper['key']}/yazi-{i}", blocks, simdi)
            for i, yazar in enumerate(["PASİF Yazar", "Kalan Yazar", "Öteki Yazar"])]


fc.discover_writers = sahte_kesif
fc.fetch_paper_articles = sahte_gazete
with tempfile.TemporaryDirectory() as td:
    out, wout, kout = (os.path.join(td, n) for n in ("daily.json", "writers.json", "kaynaklar.json"))
    argv = sys.argv
    sys.argv = ["fetch_columns.py", "--out", out, "--writers-out", wout, "--kaynaklar-out", kout,
                "--kurallar-url", f"{TABAN}/ok", "--min-interval-hours", "0", "--require-articles", "1"]
    ISTEKLER.clear()
    try:
        rc = fc.main()
    finally:
        sys.argv = argv
    daily = json.load(open(out, encoding="utf-8"))
    yazilar = daily["articles"]
    check("çekim başarılı", rc == 0, rc)
    check("pasif gazete hiç taranmadı (keşif + bugünün yazıları)", taranan_gazeteler == ["agazete"] and kesif_gazeteleri == [["agazete"]],
          (taranan_gazeteler, kesif_gazeteleri))
    check("pasif yazarın yazısı elendi (büyük/küçük/aksan farkına rağmen)", not any(kk.writer_key(a["author"]) == "pasif yazar" for a in yazilar))
    check("diğer gazete yazıları duruyor", sum(1 for a in yazilar if a["sourceKey"] == "agazete") == 2)
    check("her kayıtta sourceKey var", all(a.get("sourceKey") for a in yazilar))
    check("yerleşik akış okundu", any(a["sourceKey"] == "dogrudan" for a in yazilar))
    ek1 = [a for a in yazilar if a["sourceKey"] == "ek-1234abcd"]
    ek2 = [a for a in yazilar if a["sourceKey"] == "ek-5678abcd"]
    check("eklenen blog (otomatik keşif) okundu, yazar/kategori kuraldan", len(ek1) == 2 and ek1[0]["author"] == "Ek Yazar" and ek1[0]["category"] == "Ekonomi", ek1[:1])
    check("eklenen YouTube kanalı okundu", len(ek2) == 1 and ek2[0]["source"] == "Kanal", ek2)
    check("eklenen kaynağın uid'si ek-…-md5 biçiminde", ek1[0]["id"].startswith("ek-1234abcd-"))
    writers = json.load(open(wout, encoding="utf-8"))
    check("writers.json: pasif gazete ve pasif yazar dizinde yok",
          [p["key"] for p in writers["papers"]] == ["agazete"] and all(kk.writer_key(w["name"]) != "pasif yazar" for p in writers["papers"] for w in p["writers"]),
          writers["papers"])
    check("writers.json: sayılar güncel", writers["papers"][0]["count"] == len(writers["papers"][0]["writers"]))
    kat = json.load(open(kout, encoding="utf-8"))
    girdiler = {k["key"]: k for k in kat["katalog"]}
    check("katalog: tüm tanımlı kaynaklar + eklenenler", set(girdiler) == {"agazete", "bgazete", "dogrudan", "ek-1234abcd", "ek-5678abcd"}, sorted(girdiler))
    check("katalog: pasif gazete aktif:false, yazı 0", girdiler["bgazete"]["aktif"] is False and girdiler["bgazete"]["yazi"] == 0)
    check("katalog: yazı sayıları", girdiler["agazete"]["yazi"] == 2 and girdiler["ek-1234abcd"]["yazi"] == 2)
    check("katalog: eklenen kaynak durumu ve çözülen akış", girdiler["ek-1234abcd"]["durum"] == "ok" and girdiler["ek-1234abcd"]["akis"] == "https://ek.example/blog/feed.xml"
          and girdiler["ek-5678abcd"]["akis"].endswith("channel_id=UCQmDWRUf_X8BSrrDOSZA-NA"))
    check("katalog: kural kaynağı api, sürüm 4, alınma anı yazıldı",
          kat["kurallarKaynagi"] == "api" and kat["kurallarSurumu"] == 4 and kk._iso(kat["kurallarAlindi"]) is not None)
    check("katalog: uygulanan kuralların kopyası (yedek için)", kk.pasif_kaynak_anahtarlari(kk.kurallari_dogrula(kat["kurallar"])) == {"bgazete"})
    check("kataloğun alınma anı veriden önce", kk._iso(kat["kurallarAlindi"]) <= kk._iso(kat["guncellendi"]))

    print("   -- ikinci çekim: kural ucu düştü (503)")
    taranan_gazeteler.clear()
    ISTEKLER.clear()
    sys.argv = ["fetch_columns.py", "--out", out, "--writers-out", wout, "--kaynaklar-out", kout,
                "--kurallar-url", f"{TABAN}/kurulum", "--min-interval-hours", "0", "--require-articles", "1"]
    try:
        rc = fc.main()
    finally:
        sys.argv = argv
    kat2 = json.load(open(kout, encoding="utf-8"))
    check("uç düşünce önceki kurallar uygulandı (B yine taranmadı)", rc == 0 and taranan_gazeteler == ["agazete"] and kat2["kurallarKaynagi"] == "onceki", kat2.get("kurallarNotu"))
    check("çözülen akışlar katalogdan hatırlandı (blog sayfası yeniden açılmadı)",
          "https://ek.example/blog" not in ISTEKLER and "https://www.youtube.com/@kanal" not in ISTEKLER, ISTEKLER)
    check("katalogda kurallar korunur", kk.pasif_yazar_anahtarlari(kk.kurallari_dogrula(kat2["kurallar"])) == {"pasif yazar"})

sunucu.shutdown()
print(f"\n{GECEN} denetim geçti, {HATA} başarısız")
if HATA:
    print("KAYNAK KURALI TESTLERİ BAŞARISIZ")
    sys.exit(1)
print("TÜM KAYNAK KURALI TESTLERİ GEÇTİ")
