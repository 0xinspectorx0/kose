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

Sayfa açıkken yarım saatte bir yeniden yoklar; sekmeye geri dönüldüğünde (ya da
bağlantı geri geldiğinde) ekrandaki veri 10 dakikadan eskiyse **hemen** yeniler.
"x dk önce" etiketi canlı güncellenir; bugünün verisi 12 saattir yenilenmediyse ya da
07:00'den sonra hâlâ dünün verisi gösteriliyorsa banner sarıya döner.

## Günlük güncelleme nasıl çalışıyor?

`.github/workflows/fetch-columns.yml` `data/daily.json` ve `data/writers.json`
dosyalarını üretip **main'e commit'ler**.

**Neden sabit saatler değil de yarım saatte bir yoklama?** GitHub'ın `schedule`
tetikleyicisi bu depoda koşuları planlanan saatten **3-6 saat sonra** başlatıyor
(13-15 Ekim 2026: 04:00 UTC slotu 09:17'de, 08:30 slotu 13:55'te, 14:00 slotu
18:15'te başladı; bir koşu 9,5 saat kuyrukta bekledi; 15 Ekim sabahı hiç koşu
düşmedi). "06:13 sabah çekimi" fiilen öğleden sonraya kayıyor, sabah köşeleri
öğlene kadar gelmiyordu. Artık her yarım saatte ~10 saniyelik bir **kontrol işi**
koşuyor; asıl çekim (≈8 dk) yalnızca veri gerçekten bayatsa başlıyor. Gecikme ne
olursa olsun gün boyu düzenli yoklama düşüyor, gazetelere giden istek sayısı ise
aşağıdaki politikayla sınırlı kalıyor.

| Konu | Durum |
|---|---|
| Yoklama | Her saatin `:07` ve `:37`'sinde (`7,37 * * * *`) — günde 48 hafif kontrol |
| Karar (`scripts/freshness.py`) | Veri bugünün değilse **çek** · 05:00-12:00 TSİ arası 1 saatten eskiyse **çek** · diğer saatlerde 3 saatten eskiyse **çek** · seyrekse (< 80 yazı) saatte bir yeniden **çek** · aksi halde atla |
| Kontrol işi | Bağımlılık kurmaz (yalnızca standart kütüphane), kararı ve gerekçesini iş özetine yazar; çekim işi `needs.kontrol.outputs.needed == 'true'` ise koşar |
| Dakikalar | Kasıtlı olarak `:00`/`:30` değil — GitHub tam/yarım saatteki koşuları yoğunlukta daha çok geciktiriyor |
| Tazelik kısayolu | Betik de aynı politikayla tazeliği yeniden denetler (tek doğruluk kaynağı `freshness.py`) — kilitte beklerken veri tazelendiyse çekim atlanır |
| Merge sonrası | Kazıyıcı/politika/workflow değişikliği main'e merge edilince (`push`, `paths` filtresi) **hemen zorla çekim** — yeni kod beklemeden devreye girer. Botun veri commit'leri `GITHUB_TOKEN` ile atıldığı için yeni koşu tetiklemez (döngü yok) |
| Eşzamanlılık | `concurrency: kose-fetch-columns` **çekim işinde** — iki çekim aynı anda main'e yazmaz, hafif kontroller kilide takılmaz; çekim işi dalın güncel ucunu (`ref: github.ref_name`) çeker |
| Push çakışması | Reddedilirse: uzak uç çekilir → uzaktaki veri daha tazeyse bizimki bırakılır → değilse uzağa sıfırlanıp taze çıktı yeniden commit'lenir (5 deneme) |
| Çekim hatası | Betik `2` dönerse (bugünün verisi üretilemedi) koşu bir kez daha dener; mevcut `daily.json` asla boşaltılmaz |
| Yaş filtresi | Yayım tarihi 2 günden eski yazılar akışa alınmaz (`publishedAt` alanı) — akışta bugün + dün kalır |
| Elle çalıştırma | Actions → *Köşe Yazılarını Güncelle (Günlük)* → **Run workflow** (`force` = tazelik kısayolunu atla) |

> `schedule` tetikleyicisi GitHub'da yalnızca **varsayılan dalda** (main) çalışır.
> Bu dosya main'de olduğu sürece zamanlama etkindir; başka bir dalda yalnızca
> *Run workflow* ile elle koşulur.

Kararı yerelde görmek için:

```bash
python3 scripts/freshness.py                                   # şimdi çekim gerekir mi? (needed=… reason=…)
python3 scripts/freshness.py --now 2026-10-15T08:30:00+03:00   # belirli bir an için
```

## Peki gerçekten güncellendi mi? (Watchdog)

`fetch-columns.yml` veriyi **üretir**; `.github/workflows/verify-columns.yml` ise
üretilen veriyi **denetler** ve gerekirse kendini onarır.

| Konu | Durum |
|---|---|
| Zamanlama | Günde 2 denetim: TSİ **11:07** (sabah yayın penceresi kapandıktan sonra) ve **18:07** |
| Gece koruması | GitHub gecikmesiyle 00:00-09:00 TSİ arasına kayan **zamanlanmış** denetim atlanır (günün köşeleri henüz yayımlanmamışken yanlış alarm vermesin); elle tetikleme her saatte denetler |
| Denetleyen | `scripts/verify_daily.py` (ağ gerektirmez, yalnızca `data/*.json`'a bakar) |
| Denetim maddeleri | Veri bugünün verisi mi · son çekim 24 saatten yeni mi · en az 60 yazı var mı · **en az 6 kaynak günün yazısını getirmiş mi** · **son 24 saatte yayımlanan en az 40 yazı çekilmiş mi** · akışa 3 günden eski yazı sızmış mı · yazar dizini sağlam mı |
| Kendi kendini onarma | Denetim başarısızsa `fetch-columns.yml` **force=true** ile tetiklenir (`actions: write`; girdi `inputs[force]` olarak gönderilir), yalnızca bu tetiklemenin koşusu izlenir, bitmesi beklenir, main'in verisi indirilip yeniden denetlenir |
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
# 1) Hat (kazıyıcı + workflow) — ağ gerektirmez (yapısal denetimler için: pip install pyyaml)
.venv/bin/python patches/uitest/verify-pipeline.py   # tazelik politikası, kontrol işi uçtan uca, yaş filtresi, çıkış kodları, cron/push ayarları
.venv/bin/python patches/uitest/verify-watchdog.py   # verify_daily.py senaryoları + onarma akışı (sahte gh) + gece koruması (sahte date)

# 2) Arayüz — jsdom koşumları
mkdir -p /tmp/uitest && cd /tmp/uitest && npm init -y && npm install jsdom lucide
cp <repo>/patches/uitest/*.mjs .
node verify-freshness.mjs  # bayat veri uyarısı, otomatik yeniden deneme, çok kaynaklı yoklama, sekmeye dönüşte yenileme
node verify-core.mjs       # akış, alt menü, yukarı çık, A-/A+, Ayarlar
node verify-ui2.mjs        # yazar adı biçimi, okundu halkası, renkler
node verify-tts.mjs        # seslendirme
node verify-round9.mjs     # Keşfet
node verify-favorites.mjs  # Favori yazarlar
node verify-icons.mjs      # lucide simgeleri
```
