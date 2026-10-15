# kose — Mürekkep

[![Köşe Yazılarını Güncelle (Günlük)](https://github.com/0xinspectorx0/kose/actions/workflows/fetch-columns.yml/badge.svg)](https://github.com/0xinspectorx0/kose/actions/workflows/fetch-columns.yml)
[![Günlük Veri Denetimi (Watchdog)](https://github.com/0xinspectorx0/kose/actions/workflows/verify-columns.yml/badge.svg)](https://github.com/0xinspectorx0/kose/actions/workflows/verify-columns.yml)

Türk gazetelerinin köşe yazılarını toplayan tek dosyalık okuyucu (`index.html`) ve
onu besleyen günlük kazıyıcı (`scripts/fetch_columns.py`).

Uygulama açılışta veriyi üç kaynaktan yoklar ve **en taze** olanı kullanır:

1. `https://raw.githubusercontent.com/0xinspectorx0/kose/main/data/daily.json` (canlı)
2. `https://cdn.jsdelivr.net/gh/0xinspectorx0/kose@main/data/daily.json` (CDN yedeği)
3. `data/daily.json` (depoyla paketlenen anlık görüntü — çevrimdışı yedek)

Aynı mantık yazar dizini için de geçerlidir (`data/writers.json`).

## Günlük güncelleme nasıl çalışıyor?

`.github/workflows/fetch-columns.yml` zamanlanmış koşularla `data/daily.json` ve
`data/writers.json` dosyalarını üretip **main'e commit'ler**.

| Konu | Durum |
|---|---|
| Zamanlama | Günde 6 slot: TSİ 06:13, 09:17, 12:23, 15:13, 18:17, 21:23 |
| Dakikalar | Kasıtlı olarak `:00`/`:30` değil — GitHub tam saatteki koşuları yoğunlukta daha çok geciktiriyor |
| Tazelik kısayolu | Veri bugünün verisiyse, 4 saatten yeniyse ve en az 80 yazı içeriyorsa çekim atlanır (gazetelere boşuna istek gitmez) |
| Seyrek sabah çekimi | Erken saatteki çekim 80 yazının altında kalırsa sonraki slot yeniden çeker, günün kalan köşeleri toplanır |
| Eşzamanlılık | `concurrency: kose-fetch-columns` — iki koşu aynı anda main'e yazmaya çalışmaz |
| Push çakışması | Reddedilirse: uzak uç çekilir → uzaktaki veri daha tazeyse bizimki bırakılır → değilse uzağa sıfırlanıp taze çıktı yeniden commit'lenir (5 deneme) |
| Çekim hatası | Betik `2` dönerse (bugünün verisi üretilemedi) koşu bir kez daha dener; mevcut `daily.json` asla boşaltılmaz |
| Yaş filtresi | Yayım tarihi 2 günden eski yazılar akışa alınmaz (`publishedAt` alanı) — akışta bugün + dün kalır |
| Elle çalıştırma | Actions → *Köşe Yazılarını Güncelle (Günlük)* → **Run workflow** (`force` = tazelik kısayolunu atla) |

> `schedule` tetikleyicisi GitHub'da yalnızca **varsayılan dalda** (main) çalışır.
> Bu dosya main'de olduğu sürece zamanlama etkindir; başka bir dalda yalnızca
> *Run workflow* ile elle koşulur.

## Peki gerçekten güncellendi mi? (Watchdog)

`fetch-columns.yml` veriyi **üretir**; `.github/workflows/verify-columns.yml` ise
üretilen veriyi **denetler** ve gerekirse kendini onarır.

| Konu | Durum |
|---|---|
| Zamanlama | Günde 2 denetim: TSİ **13:07** ve **22:07** (çekim slotlarından sonra) |
| Denetleyen | `scripts/verify_daily.py` (ağ gerektirmez, yalnızca `data/*.json`'a bakar) |
| Denetim maddeleri | Veri bugünün verisi mi · son çekim 24 saatten yeni mi · en az 60 yazı var mı · **en az 6 kaynak günün yazısını getirmiş mi** · **son 24 saatte yayımlanan en az 40 yazı çekilmiş mi** · akışa 3 günden eski yazı sızmış mı · yazar dizini sağlam mı |
| Kendi kendini onarma | Denetim başarısızsa `fetch-columns.yml` **force=true** ile tetiklenir (`actions: write`), bitmesi beklenir, main'in verisi indirilip yeniden denetlenir |
| Kırmızı koşu | Onarmaya rağmen bugünün verisi yoksa koşu `exit 1` ile biter → Actions'ta kırmızı görünür, iş özeti hangi maddenin kaldığını ve kaynak bazında günün yazısı sayısını yazar |
| Elle | Actions → *Günlük Veri Denetimi (Watchdog)* → **Run workflow** (`heal=false` ile yalnızca rapor) |

Yerelde tek komutla denetim:

```bash
python3 scripts/verify_daily.py              # insan okumasına yönelik rapor
python3 scripts/verify_daily.py --markdown   # GitHub iş özeti biçimi
python3 scripts/verify_daily.py --json       # makine okunur
```

Rapor "en son yayımlanan yazılar çekilmiş mi?" sorusunu kaynak bazında cevaplar:

```
  KAYNAK BAZINDA (yazı | günün yazısı | en yeni)
    Cumhuriyet            13 |  13 | 2026-10-15 09:46
    Hürriyet              13 |  10 | 2026-10-15 11:41
    Evrensel               2 |   0 | 2026-10-11 12:00   ← günün yazısı yok
```

## Yerelde çalıştırma

```bash
python3 -m venv .venv && .venv/bin/pip install requests beautifulsoup4
.venv/bin/python scripts/fetch_columns.py                      # tam çekim
.venv/bin/python scripts/fetch_columns.py --discover-only      # sadece yazar dizini
.venv/bin/python scripts/fetch_columns.py --min-interval-hours 0   # tazelik kısayolunu atla
.venv/bin/python scripts/fetch_columns.py --max-per-paper 5    # hızlı deneme
```

Uygulama statiktir: `index.html` dosyasını açmak yeterlidir.

## Doğrulama

```bash
# 1) Hat (kazıyıcı + workflow) — ağ gerektirmez
.venv/bin/python patches/uitest/verify-pipeline.py   # tazelik kısayolu, yaş filtresi, çıkış kodları, cron/push ayarları
.venv/bin/python patches/uitest/verify-watchdog.py   # verify_daily.py senaryoları + watchdog'un onarma akışı (sahte gh)

# 2) Arayüz — jsdom koşumları
mkdir -p /tmp/uitest && cd /tmp/uitest && npm init -y && npm install jsdom lucide
cp <repo>/patches/uitest/*.mjs .
node verify-freshness.mjs  # bayat veri uyarısı, otomatik yeniden deneme, çok kaynaklı yoklama
node verify-core.mjs       # akış, alt menü, yukarı çık, A-/A+, Ayarlar
node verify-ui2.mjs        # yazar adı biçimi, okundu halkası, renkler
node verify-tts.mjs        # seslendirme
node verify-round9.mjs     # Keşfet
node verify-favorites.mjs  # Favori yazarlar
node verify-icons.mjs      # lucide simgeleri
```
