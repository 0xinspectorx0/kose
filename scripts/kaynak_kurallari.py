#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yönetici kaynak kuralları — kazıyıcı (fetch_columns.py) ve röle (zamanlayici.yml) ortak
======================================================================================
Site sahibi uygulamadaki Yönetim panelinden çekim listesini yönetir:
  * kaynağı (gazete / site / akış) çekimden çıkarır ya da yeniden açar,
  * yazarı çekimden çıkarır (hangi kaynaktan gelirse gelsin yazıları alınmaz),
  * yeni RSS/Atom/YouTube/site kaynağı ekler veya siler.
Kurallar Vercel'deki /api/yonetim?islem=kaynaklar ucundan HERKESE AÇIK okunur
(sır içermez). Bu modül yalnızca standart kütüphaneyi kullanır: rölenin
bağımlılıksız "kontrol" işi de içe aktarabilsin.

Uç erişilemezse son başarılı çekimin data/kaynaklar.json'a yazdığı kurallar
kullanılır (kurallar bir ağ aksaklığında sessizce kaybolmasın); o da yoksa
kural uygulanmaz.

Komut satırı (röle):
    python3 scripts/kaynak_kurallari.py --kontrol --data data/kaynaklar.json --github-output
    -> degisti=true|false, neden=...  (kurallar son çekimden sonra değiştiyse true)
"""

import argparse
import ipaddress
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

VARSAYILAN_URL = "https://murekkep.vercel.app/api/yonetim?islem=kaynaklar"
KATEGORILER = ("Gündem", "Ekonomi", "Teknoloji", "Kültür-Sanat")
EK_SINIRI = 40
USER_AGENT = "kose-kosebot/1.0 (+https://github.com/0xinspectorx0/kose; kaynak kurallari)"


# ---------------------------------------------------------------------------
# Yazar anahtarı — uygulamadaki favKeyName() ile birebir aynı kural
# ---------------------------------------------------------------------------
_TR_KUCUK = str.maketrans({"I": "ı", "İ": "i"})
_AKSANSIZ = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u",
})


def temiz_yazar_adi(ham):
    """Uygulamadaki cleanWriterName(): '|' sonrası ve 'N yazı' eki atılır."""
    n = re.sub(r"\s+", " ", str(ham or "")).strip()
    if "|" in n:
        n = n.split("|")[0].strip()
    n = re.sub(r"\s+\d+\s+(?:adet\s+)?yaz[ıi]\s*$", "", n, flags=re.I).strip()
    return n


def writer_key(ad):
    """Türkçe küçült (I->ı, İ->i), aksanları at, boşlukları sadeleştir.

    "Ahmet HAKAN" == "ahmet hakan", "KILIÇ" == "Kılıç" == "kilic". Uygulama
    (index.html favKeyName) aynı anahtarı üretir; yazar kuralları iki tarafta
    da aynı yazara denk gelir.
    """
    s = unicodedata.normalize("NFC", temiz_yazar_adi(ad))
    s = s.translate(_TR_KUCUK).lower().translate(_AKSANSIZ)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Kuralların doğrulanması
# ---------------------------------------------------------------------------
def bos_kurallar():
    return {"surum": 0, "guncellendi": None, "pasif": {"kaynaklar": [], "yazarlar": []}, "ek": []}


def _metin(v, sinir):
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        return ""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v))
    return re.sub(r"\s+", " ", s).strip()[:sinir]


def ozel_adres_mi(host):
    """Yerel/iç ağ adresleri (kazıyıcı bunlara asla istek atmaz)."""
    h = (host or "").strip("[]").lower()
    if not h or h == "localhost" or h.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    except ValueError:
        return False


def guvenli_adres(v):
    s = _metin(v, 600)
    if not s:
        return ""
    try:
        u = urlparse(s)
    except ValueError:
        return ""
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return ""
    if ozel_adres_mi(u.hostname):
        return ""
    return s


def kurallari_dogrula(veri):
    """API'den ya da dosyadan gelen kuralları güvenli, eksiksiz bir yapıya indirger."""
    out = bos_kurallar()
    if not isinstance(veri, dict):
        return out
    try:
        out["surum"] = max(0, int(veri.get("surum") or 0))
    except (TypeError, ValueError):
        out["surum"] = 0
    g = veri.get("guncellendi")
    out["guncellendi"] = g if isinstance(g, str) and _iso(g) else None
    pasif = veri.get("pasif") if isinstance(veri.get("pasif"), dict) else {}
    for p in pasif.get("kaynaklar") or []:
        if isinstance(p, dict) and isinstance(p.get("key"), str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", p["key"]):
            out["pasif"]["kaynaklar"].append({"key": p["key"], "ad": _metin(p.get("ad"), 120) or p["key"]})
    for p in pasif.get("yazarlar") or []:
        if not isinstance(p, dict):
            continue
        ad = _metin(p.get("ad"), 120)
        anahtar = writer_key(ad)
        if anahtar:
            out["pasif"]["yazarlar"].append({"ad": ad, "anahtar": f"y:{anahtar}"})
    gorulen = set()
    for e in veri.get("ek") or []:
        if not isinstance(e, dict):
            continue
        key = e.get("key")
        feed = guvenli_adres(e.get("feed"))
        name = _metin(e.get("name"), 80)
        if not (isinstance(key, str) and re.fullmatch(r"ek-[0-9a-f]{8}", key)) or not feed or not name or key in gorulen:
            continue
        gorulen.add(key)
        out["ek"].append({
            "key": key,
            "name": name,
            "author": _metin(e.get("author"), 80) or name,
            "category": e.get("category") if e.get("category") in KATEGORILER else "Gündem",
            "feed": feed,
        })
        if len(out["ek"]) >= EK_SINIRI:
            break
    return out


def _iso(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Kuralların alınması
# ---------------------------------------------------------------------------
def kurallari_indir(url, timeout=15):
    """(kurallar, hata) döndürür. Kurulum eksikse (503) ya da uç yoksa hata dolu gelir."""
    if not url:
        return None, "kural adresi verilmedi"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 — sabit/izinli https adresi
            veri = json.loads(r.read(512 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        neden = f"HTTP {e.code}"
        try:
            govde = json.loads(e.read(4096).decode("utf-8"))
            if isinstance(govde, dict) and govde.get("hata"):
                neden += f": {govde['hata']}"
        except Exception:
            pass
        return None, neden
    except Exception as e:  # ağ, zaman aşımı, bozuk JSON
        return None, f"{type(e).__name__}: {e}"
    if not isinstance(veri, dict) or veri.get("ok") is not True:
        return None, "beklenmeyen yanıt"
    return kurallari_dogrula(veri), None


def onceki_kurallar(yol):
    try:
        with open(yol, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("kurallar"), dict):
            return kurallari_dogrula(d["kurallar"])
    except Exception:
        pass
    return None


def kurallari_yukle(url, onceki_yol):
    """(kurallar, kaynak, not) — kaynak: 'api' | 'onceki' | 'yok'."""
    if url and url.strip().lower() not in ("yok", "-", "kapali", "none"):
        kurallar, hata = kurallari_indir(url)
        if kurallar is not None:
            return kurallar, "api", (
                f"yönetici kuralları alındı (sürüm {kurallar['surum']}): "
                f"{len(kurallar['pasif']['kaynaklar'])} pasif kaynak, "
                f"{len(kurallar['pasif']['yazarlar'])} pasif yazar, {len(kurallar['ek'])} eklenen kaynak"
            )
        onceki = onceki_kurallar(onceki_yol)
        if onceki is not None:
            return onceki, "onceki", f"kural ucu okunamadı ({hata}) — son çekimin kuralları kullanılıyor"
        return bos_kurallar(), "yok", f"kural ucu okunamadı ({hata}) ve önceki kural yok — kural uygulanmıyor"
    return bos_kurallar(), "yok", "kural adresi kapalı — kural uygulanmıyor"


def pasif_kaynak_anahtarlari(kurallar):
    return {p["key"] for p in kurallar["pasif"]["kaynaklar"]}


def pasif_yazar_anahtarlari(kurallar):
    return {writer_key(p["ad"]) for p in kurallar["pasif"]["yazarlar"] if writer_key(p["ad"])}


def ek_akis_kaynaklari(kurallar):
    """Etkin (pasif olmayan) eklenen kaynaklar — fetch_columns FEED_SOURCES biçiminde."""
    pasif = pasif_kaynak_anahtarlari(kurallar)
    return [dict(e) for e in kurallar["ek"] if e["key"] not in pasif]


# ---------------------------------------------------------------------------
# Katalog dosyası (data/kaynaklar.json)
# ---------------------------------------------------------------------------
def katalog_yaz(yol, icerik):
    klasor = os.path.dirname(yol)
    if klasor:
        os.makedirs(klasor, exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(icerik, f, ensure_ascii=False, indent=2)
        f.write("\n")


def kurallar_degisti_mi(api_kurallar, katalog):
    """Kurallar son çekimden SONRA değiştiyse (True, neden).

    Karşılaştırma, kazıyıcının kuralları çekmeye çalıştığı anla (kurallarAlindi)
    yapılır: kazıyıcı uca ulaşamamış olsa bile her kural değişikliği en fazla
    BİR zorla çekim tetikler (sonsuz döngü olmaz).
    """
    if api_kurallar is None:
        return False, "kural ucu okunamadı"
    degisim = _iso(api_kurallar.get("guncellendi"))
    if not degisim:
        return False, "hiç kaynak kuralı tanımlanmamış"
    if not isinstance(katalog, dict):
        return True, "kaynak kataloğu yok (yeni kod henüz hiç çekim yapmadı)"
    alindi = _iso(katalog.get("kurallarAlindi"))
    if not alindi:
        return True, "katalogda kuralların alındığı an yok"
    if degisim > alindi:
        return True, (f"kurallar {degisim.isoformat()} tarihinde değişti; son çekim kuralları "
                      f"{alindi.isoformat()} anında almıştı")
    return False, "son çekim güncel kuralları uyguladı"


def main():
    ap = argparse.ArgumentParser(description="Yönetici kaynak kuralları")
    ap.add_argument("--kontrol", action="store_true", help="kurallar son çekimden sonra değişti mi?")
    ap.add_argument("--data", default="data/kaynaklar.json")
    ap.add_argument("--url", default=os.environ.get("KAYNAK_KURALLARI_URL") or VARSAYILAN_URL)
    ap.add_argument("--github-output", action="store_true", help="sonucu $GITHUB_OUTPUT'a da yaz")
    args = ap.parse_args()
    if not args.kontrol:
        kurallar, kaynak, notu = kurallari_yukle(args.url, args.data)
        print(json.dumps({"kaynak": kaynak, "not": notu, "kurallar": kurallar}, ensure_ascii=False, indent=2))
        return 0
    kurallar, hata = kurallari_indir(args.url)
    try:
        with open(args.data, encoding="utf-8") as f:
            katalog = json.load(f)
    except Exception:
        katalog = None
    degisti, neden = kurallar_degisti_mi(kurallar, katalog)
    if hata:
        neden = f"{neden} ({hata})"
    print(f"degisti={'true' if degisti else 'false'}")
    print(f"neden={neden}")
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"degisti={'true' if degisti else 'false'}\n")
            f.write(f"neden={neden}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
