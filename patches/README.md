# Mürekkep — bekleyen değişiklikler (patch paketi)

Bu klasör, `arena/d1241d9e-kose` dalındaki **5 commit'in** tamamını içeriyor.
Hepsi merge edilmiş `main`'in (`87d94fc`) üzerine uygulanacak şekilde hazırlandı ve
uygulandıktan sonra çıkan ağaç birebir doğrulandı.

## İçerik

| Dosya | Ne işe yarar |
|---|---|
| `0001-…patch` … `0005-…patch` | Commit commit yamalar (`git am` ile uygulanır, mesajlar korunur) |
| `kose-tum-degisiklikler.patch` | Hepsinin tek parça diff'i (`git apply` ile uygulanır) |
| `uitest/verify-*.mjs` | jsdom test koşumları (depoda `.uitest/` altında, gitignore'da) |

Değişen dosyalar: `index.html` (+548/-…), `scripts/fetch_columns.py` (+22), `.gitignore` (+1).

## Commit listesi

1. `feat: gerçek seslendirme (Web Speech API) + Keşfet yazar etkileşimi`
2. `feat(seslendirme): hızlandır / yavaşlat denetimi (0,75×–1,75×)`
3. `feat(seslendirme): okuyucuda oynat/duraklat düğmesi + alt menü üstünde mini oynatıcı`
4. `feat(seslendirme): ses seçimi — tarayıcıdaki Türkçe sesler arasından seç`
5. `feat(ui): yazar adı biçimi, okundu halkası, turuncu yukarı-çık ve oynatıcı renkleri`

## Yeni sohbette nasıl uygulanır

```bash
cd kose
git checkout main && git pull          # main = 87d94fc olmalı
git checkout -b seslendirme-ve-ui      # isteğe bağlı: ayrı dal

# 1) commit commit (önerilen):
git am patches/0*.patch

# 2) ya da tek parça:
git apply patches/kose-tum-degisiklikler.patch
git add -A && git commit -m "feat: seslendirme, mini oynatıcı, yazar adı biçimi ve okundu halkası"

git push -u origin <dal-adı>
gh pr create --base main --title "Seslendirme + mini oynatıcı + UI iyileştirmeleri"
```

`git am` çakışırsa: `git am --abort` deyip 2. yöntemi dene.

## Uygulamadan sonra doğrulama

```bash
mkdir -p /tmp/uitest && cd /tmp/uitest && npm init -y && npm install jsdom lucide
cp patches/uitest/*.mjs .              # ya da .uitest/ altına kopyala
node verify-ui2.mjs      # yazar adı biçimi, okundu halkası, renkler/gradient
node verify-tts.mjs      # seslendirme: oynat/duraklat, hız, ses seçimi, mini oynatıcı
node verify-round9.mjs   # Keşfet: alfabetik gazeteler, öne çıkan yazarlar, yazara tıkla
node verify-core.mjs     # akış, alt menü, yukarı çık, A-/A+, Ayarlar
node verify-icons.mjs    # lucide 1.55.0 simge denetimi
node verify-freshness.mjs # bayat veri uyarısı, otomatik yeniden deneme, çok kaynaklı yoklama
```

Ayrıca günlük güncelleme hattının (kazıyıcı + workflow) ağ gerektirmeyen denetimi:

```bash
python3 patches/uitest/verify-pipeline.py   # tazelik kısayolu, yaş filtresi, çıkış kodları, cron/push ayarları
```

Beş koşum da bu paketi oluştururken çalıştırıldı ve `exit 0` döndü.
Not: betikler jsdom'u `/tmp/uitest/node_modules` üzerinden içe aktarır; farklı bir
klasöre kurarsan import satırındaki yolu güncelle.

## Kapsam özeti

- **Seslendirme:** Web Speech API ile gerçek okuma (tr-TR), bölüm bölüm ilerleme,
  duraklat/sürdür, hız 0,75×–1,75× (kalıcı), ses seçimi (kalıcı), okuyucu başlığında
  oynat/duraklat, alt menü üstünde mini oynatıcı (yazar · yazı · sayaç · ✕).
- **Keşfet:** yazar çipleri tıklanınca akışta o yazarın yazıları; çiplerde yalnızca ad;
  öne çıkan yazarlar başta (bugün yazanlar > portresi olanlar > kalanlar).
- **Kazıyıcı:** yazar adlarındaki "15 Yazı" / "| Köşe adı" ekleri temizleniyor,
  rakamla başlayan ve kimlik görünümlü kayıtlar eleniyor.
- **UI:** "Ad SOYAD" biçimi, okunan yazarın halkası gri, yukarı çık düğmesi ve
  oynatıcı düğmeleri mürekkep turuncusu, mini oynatıcıda soldan sağa gradient.
