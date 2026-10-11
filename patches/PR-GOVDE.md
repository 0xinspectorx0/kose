# Seslendirme (Web Speech API), mini oynatıcı ve UI iyileştirmeleri

## Özet

Okuyucuya gerçek seslendirme, ana sayfaya mini medya oynatıcı, Keşfet'e yazar etkileşimi ve bir dizi görsel düzeltme ekliyor. Kazıyıcı tarafında yazar adlarını kirleten ekler temizleniyor.

Değişen dosyalar: `index.html` (+548/−…), `scripts/fetch_columns.py` (+22), `.gitignore` (+1).

## Seslendirme

- "Yapay Zeka Seslendirmesi" bir animasyondu; yerine **Web Speech API** ile gerçek okuma geldi: başlık + yazar + gazete + tam metin `tr-TR` ile seslendiriliyor.
- Türkçe ses otomatik seçiliyor; **Ayarlar'dan ses seçilebiliyor** (Türkçe sesler üstte, diğer diller ayrı grupta) ve seçim kalıcı.
- **Hız denetimi:** 0,75× – 1,75× (adım 0,25), kalıcı; konuşma sırasında değişirse aynı bölüm yeni hızla baştan okunuyor.
- Metin cümle sınırlarından ~200 karakterlik bölümlere ayrılıyor (uzun `utterance` kesilmesi için); şeritte "3/21 bölüm" + ilerleme çubuğu var.
- Okuyucu başlığındaki düğme duruma göre **oynat/duraklat** simgesi gösteriyor.
- **Mini oynatıcı:** okuyucuyu kapatmak sesi kesmiyor; alt menünün üstünde ince bir şerit beliriyor (yazar · yazı adı · bölüm sayacı · oynat/duraklat · kapat). Yazıya tıklayınca okuyucu yeniden açılıyor, sekme değişimlerinde yerinde kalıyor.
- Desteklemeyen tarayıcıda açıklayıcı mesaj gösteriliyor.

## Keşfet

- Yazar çipleri artık düğme: tıklayınca akışa geçip o yazarın yazılarını listeliyor (bugün yazısı yoksa bilgi kartı + gazetedeki yazar sayfası bağlantısı).
- Çiplerde yalnızca yazar adı görünüyor; her gazetenin **öne çıkan yazarları başta** (bugün yazanlar → portresi olanlar → kalanlar; her katmanda gazetenin kendi sırası korunuyor).
- Gazete adları alfabetik (önceki PR'dan).

## Kazıyıcı

- Yazar adlarındaki dizin artıkları temizleniyor: "İlke Gürsoy 15 Yazı" → "İlke Gürsoy", "Adnan Ekinci | Hukuk Ombudsmanı" → "Adnan Ekinci".
- Rakamla başlayan ("15. İstanbul Bienali") ve kimlik görünümlü (`6998422Eeb…`) kayıtlar eleniyor. Mevcut 1278 kayıt üzerinde: 3 kayıt elendi, 71 ad temizlendi, gerçek adlar değişmedi.

## Arayüz

- Yazar adları her yerde **"Ad SOYAD"** biçiminde (Türkçe duyarlı: `ı→I`, `i→İ`; "Dr."/"M." kısaltmaları korunur).
- Ana menüde yazarın bugünkü tüm yazıları okunduysa çemberin turuncu halkası **griye** dönüyor; okundu bilgisi `localStorage`'da.
- Yukarı çık düğmesi ve oynatıcı düğmeleri mürekkep turuncusu (`accent #D9532F`).
- Mini oynatıcı soldan sağa 0'dan (şeffaf) başlayan turuncu gradient; ilerleme çizgileri gradient.

## Doğrulama

jsdom koşumları (`patches/uitest/`, depoda `.uitest/`): `verify-ui2`, `verify-tts` (13 bölüm), `verify-round9`, `verify-core`, `verify-icons` — beşi de `exit 0`. Ayrıca `node --check` ve `python3 -m py_compile scripts/fetch_columns.py` temiz. Kazıyıcı temizliği gerçek `writers.json` üzerinde çalıştırılarak doğrulandı.

**Doğrulanamayan:** gerçek ses çıkışı ve görsel yerleşim (sandbox'ta tarayıcı/ses cihazı yok) — tarayıcıda denenmesi gerekiyor.

## Notlar

- Kazıyıcıdaki ad temizliği ayrıca arayüzde de uygulanıyor, yani eski `data/writers.json` ile de ekran temiz görünüyor.
- T24'te "Kendine Ait Bir Köşe" (bir köşe adı, kişi değil) kurala takılmıyor; istenirse kaynak bazlı istisna eklenebilir.
