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
| Yoklama | **Birincil:** `zamanlayici.yml` röle zinciri — ≈30 dk'da bir, GitHub cron'undan bağımsız (aşağıdaki *Zamanlayıcı* bölümü) · **Yedek:** her saatin `:07` ve `:37`'si (`7,37 * * * *`) |
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

## Zamanlayıcı (30 dk röle) — GitHub cron'u çalışmadığında

GitHub'ın `schedule` tetikleyicisi 26 Ağustos 2026'dan beri birçok depoda ya hiç
koşu üretmiyor ya da saatlerce geciktiriyor; elle/API ile tetikleme ise anında
çalışıyor. Bu depoda 15 Ekim 2026'da 09:39-14:08 UTC arasında yarım saatlik
yoklamadan da watchdog'dan da **tek koşu oluşmadı**, veri 4,5 saat bayat kaldı.
`.github/workflows/zamanlayici.yml` veriyi GitHub cron'una bağlı kalmadan taze tutar.

| Konu | Durum |
|---|---|
| Mantık | Kendi kendini yeniden başlatan zincir. Her koşu ("halka") iki iş içerir; ikisi aynı anda başlar |
| `kontrol` işi | **Hemen** koşar: main'deki veriye `scripts/freshness.py` ile bakar (politika yukarıdakiyle aynı); çekim gerekiyorsa ve main'de süren bir çekim yoksa `fetch-columns.yml`'i main'de tetikler |
| `sonraki` işi | `kose-zamanlayici` ortamının **bekleme süresi** (wait timer, 30 dk) dolunca koşar ve bu iş akışını yeniden tetikler → bir sonraki halka |
| Neden cron'dan bağımsız? | Bekleme, GitHub'ın ortam koruma kuralıdır; beklerken runner meşgul edilmez, süre faturalanmaz. `deployment: false` sayesinde dağıtım kaydı oluşmaz. `GITHUB_TOKEN` ile yapılan `workflow_dispatch` yeni koşu başlatabilir — ek token/secret gerekmez |
| Kaçak döngü kilidi | Bekleme uygulanmadıysa (koşu başlayalı 20 dk geçmemişse ya da ortamdaki süre 20 dk'dan kısaysa) zincir **durur**, koşu kurulum talimatını hata notu olarak düşer; tazelik kontrolü yine de bir kez yapılır |
| Tek zincir | `concurrency: kose-zamanlayici-<dal>` — en fazla 1 koşu + 1 bekleyen. push/cron/elle tetikleme üst üste gelse de tek zincir kalır (fazladan bekleyen koşu "iptal" görünür; normaldir) |
| Test dalları | Varsayılan dal dışında yalnızca push ile başlayan koşu bir halka daha başlatır; tetiklenmiş halkalar orada durur (0 → 1). Girdiye bağlı değildir |
| Koşu başlığı | Actions listesinde her koşu `Zamanlayıcı — halka N (olay)` olarak görünür; N her halkada bir artar |
| Kopan zincir | Bu dosya main'de değişince (push), seyrek cron (`41 */4 * * *`, GitHub zamanlayıcısı toparlanınca) ya da elle: Actions → *Zamanlayıcı (30 dk röle)* → **Run workflow** |
| GitHub cron'u düzelirse | `fetch-columns.yml`'in kendi `7,37` yoklaması da koşar; iki taraf aynı politikayı kullandığı ve süren çekim varken yenisi açılmadığı için çift çekim olmaz |

**Tek seferlik kurulum (depo yöneticisi):** Settings → Environments →
`kose-zamanlayici` (yoksa **New environment**) → **Wait timer** kutusunu
işaretleyip `30` yazın → **Save protection rules**. Zinciri main'e merge
başlatır; koparsa Actions → *Zamanlayıcı (30 dk röle)* → **Run workflow**.

> Veriyi **hemen** tazelemek için zamanlayıcıyı değil *Köşe Yazılarını Güncelle
> (Günlük)*'ü çalıştırın — zamanlayıcının her halkası bekleme süresi kadar sürer.

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

## Ana ekran: favori yazar dairelerinin sırası

Ana ekrandaki daireler iki kurala göre sıralanır:

1. **Okuduğunuz yazarlar sona geçer.** Bugünkü yazılarının tamamı okunmuş (halkası gri)
   yazarlar listenin sonunda toplanır; ertesi gün yeni yazı gelince başa döner.
2. **"Karıştır" açıksa okunmamışlar karışık gelir.** Başlıktaki **Karıştır** düğmesi
   (Ayarlar → *Favori yazarları karıştır* anahtarı da aynı ayarı değiştirir) her
   dokunuşta yeni bir karışık sıra üretir; kapatınca favoriye eklenme sırasına
   dönülür. Karışık sıra `localStorage`'da saklandığı için veri yenilenince,
   sekmeye dönünce ya da sayfa yeniden açılınca sıra zıplamaz.

Karıştırma yalnızca okunmamış grubun içinde çalışır: okuduğunuz favoriler her iki
durumda da sonda kalır.

## Pasif yazarlar (yazısı güncellenmesin) ve Keşfet'ten silme

Keşfet'te her yazarın yanındaki **⋯** düğmesi yazar seçeneklerini açar:

| İşlem | Ne olur | Nerede saklanır |
|---|---|---|
| **Pasife al** | Yazar Keşfet'te soluk "pasif" olarak kalır; yazıları **güncellenmez**. Eldeki son yazısı akışta `PASİF YAZAR` etiketiyle donar, tekrar çekilmez | `kose-passive-writers` (localStorage) |
| **Keşfet listesinden sil** | Yazar Keşfet listesinden tamamen kaldırılır (akıştaki yazıları etkilenmez) | `kose-hidden-writers` |
| Gazete satırındaki **⋯ → Gazeteyi Keşfet'ten sil** | Gazete ve tüm yazar çipleri listeden kalkar | `kose-hidden-papers` |

Silinen yazarlar ve gazeteler Keşfet'in altındaki **Gizlenenler** kartından, pasif
yazarlar **Pasif yazarlar** kartından (ya da akıştaki kartın "Aktif et" düğmesinden)
geri alınır. Pasif yazarın yazısı akışta soluk görünür; okunabilir, kaydedilebilir.

### Yazarın yazısı gerçekten güncellenmesin (kazıyıcı tarafı)

Uygulamada işaretlemek cihazla sınırlıdır. Güncellemeyi **kaynağında** durdurmak için
liste depoya `data/passive-writers.json` olarak eklenir: **Ayarlar → Pasif yazarlar ·
depo listesi → “JSON'u kopyala”/“JSON indir”**. Dosya depoya girdiğinde:

* `scripts/fetch_columns.py` bu yazarların yazılarını **hiç çekmez** (yazar dizininde
  profil bağlantısı eşleşirse istek bile yapılmaz),
* çekim sırasında yakalanan yazılar çıktıya **yazılmaz** (`daily.json`'a girmez),
* pasif yazarın **son bilinen yazısı dondurulur**: yeniden çekilmez, içeriği değişmez,
  akışta `passive: true` işaretiyle soluk görünür (2 günden eskiyse normal yaş
  filtresiyle akıştan düşer),
* `data/writers.json`'da yazar `"passive": true` ile işaretlenir — uygulama cihazda
  işaret olmasa da yazarı pasif gösterir,
* dosya `main`'e işlendiğinde `fetch-columns.yml`'in `push` tetikleyicisi **hemen
  zorla çekim** başlatır: yeni liste beklemeden devreye girer.

Dosya biçimi (`source`/`url` isteğe bağlıdır; `source` verilirse eşleşme o gazetede
olmalı — aynı ad başka gazetede yazıyor olabilir):

```json
{
  "updatedAt": "2026-10-15T18:20:00.000Z",
  "writers": [
    { "name": "Ahmet Hakan", "source": "Hürriyet",
      "url": "https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/" },
    { "name": "Sadece Isim" }
  ]
}
```

Kazıyıcıyı elle koşarken liste dosyası değiştirilebilir:

```bash
.venv/bin/python scripts/fetch_columns.py --passive-file data/passive-writers.json
.venv/bin/python scripts/fetch_columns.py --passive-file -   # pasif listeyi yok say
```

> Ad karşılaştırması Türkçe duyarlıdır: büyük/küçük harf, aksan ve boşluk farkları
> önemsenmez (`"AHMET HAKAN"` = `"Ahmet Hakan"`). Dosya bozuksa/eksikse çekim durmaz;
> o koşu pasif listesiz çalışır.

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
.venv/bin/python patches/uitest/verify-relay.py      # zamanlayıcı: yapı + bekleme kilidi + zincir/test dalı senaryoları (sahte gh)
.venv/bin/python patches/uitest/verify-passive.py    # pasif yazarlar: dosya okuma, eşleşme, yazı eleme, donmuş son yazı, writers.json işareti

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
node verify-passive.mjs    # pasif yazarlar + Keşfet'ten silme: ⋯ menüsü, akışta soluk etiket, Gizlenenler, depo JSON çıktısı
node verify-shuffle.mjs    # ana ekran: "Yazarları karıştır", okuduğum favoriler sonda, karışık sıranın kalıcılığı
```
