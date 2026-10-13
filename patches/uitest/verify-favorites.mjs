// Favori Yazarlar regresyonu: alt menü sekmesi, kalpler, ana sayfa daireleri
import { readFileSync } from 'node:fs';
import { JSDOM } from '/tmp/uitest/node_modules/jsdom/lib/api.js';

const html = readFileSync('/home/user/kose/index.html', 'utf8');
const fails = [];
const ok = (cond, msg) => { if (!cond) fails.push(msg); else console.log('  ✓ ' + msg); };

// --- 1) Statik yapı ---
ok(/data-tab="favorites"/.test(html), 'alt menüde Favoriler sekmesi var');
ok((html.match(/class="nav-btn/g) || []).length === 5, 'alt menüde 5 sekme var');
ok(/id="favorites-view"/.test(html), 'favorites-view bölümü var');
ok(/id="favorites-list"/.test(html), 'favorites-list kapsayıcısı var');
ok(/id="favorites-empty"/.test(html), 'favori boş durumu var');
ok(/id="reader-favorite-btn"/.test(html), 'okuyucuda kalp düğmesi var');
ok(/Favori Yazarlar/.test(html), '"Favori Yazarlar" başlığı var');
ok(!/Takip Edilenler/.test(html), 'eski "Takip Edilenler" başlığı kaldırıldı');
for (const fn of ['renderFavorites', 'toggleFavoriteWriter', 'isFavoriteWriter', 'saveFavoriteWriters',
  'unfavoriteFromAvatar', 'openFavoriteWriterArticles', 'findWriterPhoto', 'updateReaderFavoriteIcon',
  'toggleFavoriteFromCard', 'favoriteArticles', 'deaccentTr']) {
  ok(new RegExp(`function ${fn}\\(`).test(html), `${fn}() tanımlı`);
}
ok(/kose-favorite-writers/.test(html), 'favoriler localStorage anahtarı kullanılıyor');

// --- 2) jsdom ile davranış ---
function makeDom(stored) {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'http://localhost/',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.lucide = { createIcons() {} };
      window.fetch = () => Promise.reject(new Error('offline'));
      window.speechSynthesis = {
        getVoices: () => [], addEventListener() {}, cancel() {}, speak() {}, pause() {}, resume() {}
      };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      window.Element.prototype.scrollTo = () => {};
      if (stored) window.localStorage.setItem('kose-favorite-writers', stored);
    }
  });
  return dom;
}

const dom = makeDom(null);
const { window } = dom;
const doc = window.document;
await new Promise(r => setTimeout(r, 250));

// örnek veriyi elle yükle (çevrimdışı simülasyonu)
window.eval(`
  articles = [{ id: 1, author: 'Ahmet HAKAN', source: 'Hürriyet', avatar: 'a.png', category: 'Gündem',
    title: 'Deneme yazısı', snippet: 'x', readTime: '2 dk', date: 'Bugün', isBookmarked: false, isLive: true,
    url: 'http://x', fullContent: '<p>merhaba</p>' },
   { id: 2, author: 'Mahfi Eğilmez', source: 'Kendime Yazılar', avatar: '', category: 'Ekonomi',
    title: 'İkinci yazı', snippet: 'y', readTime: '3 dk', date: 'Bugün', isBookmarked: false, isLive: true,
    url: '', fullContent: '<p>iki</p>' }];
`);

// başlangıç: favori yok -> ana sayfa daireleri boş durum gösterir
window.eval('renderAuthorAvatars()');
const track = doc.getElementById('authors-avatar-track');
ok(/Henüz favori yazarın yok/.test(track.innerHTML), 'favori yokken ana sayfada boş durum kartı görünüyor');
ok(track.querySelectorAll('img').length === 0, 'favori yokken hiçbir yazar dairesi çizilmiyor');

// Favoriler sekmesi boş durumu
window.eval("setTab('favorites')");
ok(!doc.getElementById('favorites-view').classList.contains('hidden'), 'Favoriler sekmesi görünür oldu');
ok(!doc.getElementById('favorites-empty').classList.contains('hidden'), 'favori yokken boş durum kartı görünür');
ok(doc.getElementById('writers-view').classList.contains('hidden'), 'Keşfet gizlendi');
ok(doc.getElementById('articles-list').classList.contains('hidden'), 'akış listesi gizlendi');
ok(doc.getElementById('feed-authors-section').classList.contains('hidden'), 'ana sayfa daireleri Favoriler sekmesinde gizli');

// favori ekle
window.eval("toggleFavoriteWriter({ name: 'Ahmet HAKAN', source: 'Hürriyet', photo: 'ah.png', url: 'http://y' })");
ok(window.eval('favoriteWriters.length') === 1, 'favori eklendi');
ok(window.localStorage.getItem('kose-favorite-writers').includes('Ahmet HAKAN'), 'favori localStorage’a yazıldı');
const track2 = doc.getElementById('authors-avatar-track').innerHTML;
ok(/Ahmet/.test(track2) && !/Mahfi/.test(track2), 'ana sayfadaki dairelerde yalnızca favori yazar var');
ok(/unfavoriteFromAvatar/.test(track2), 'dairenin üzerinde favoriden çıkarma kalbi var');

const favHtml = doc.getElementById('favorites-list').innerHTML;
ok(/Ahmet/.test(favHtml), 'Favoriler sayfasında yazar listeleniyor');
ok(/Bugün 1 yazı/.test(favHtml), 'Favoriler sayfasında günlük yazı sayısı gösteriliyor');
ok(doc.getElementById('favorites-empty').classList.contains('hidden'), 'favori varken boş durum gizli');
ok(doc.getElementById('favorites-meta').textContent === '1 yazar', 'favori sayacı doğru');
ok(/data-open-fav="0"/.test(favHtml) && /data-remove-fav="0"/.test(favHtml), 'favori satırında yazıları aç ve çıkar düğmeleri var');

// okuyucu kalbi
window.eval('openReader(1)');
ok(doc.getElementById('reader-favorite-btn').innerHTML.includes('fill-accent'), 'okuyucudaki kalp favori yazarda dolu');
window.eval('openReader(2)');
ok(!doc.getElementById('reader-favorite-btn').innerHTML.includes('fill-accent'), 'okuyucudaki kalp favori olmayan yazarda boş');
doc.getElementById('reader-favorite-btn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval("isFavoriteWriter('Mahfi Eğilmez','Kendime Yazılar')"), 'okuyucudaki kalple yazar favorilere eklendi');
doc.getElementById('reader-favorite-btn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval('favoriteWriters.length') === 1, 'okuyucudaki kalple favori geri alınabildi');

// yazı kartındaki kalp
window.eval("setTab('feed')");
window.eval('applyFilters()');
const cards = [...doc.querySelectorAll('#articles-list article')];
const mahfiCard = cards.find(c => /Mahfi/.test(c.textContent));
const heartBtn = [...mahfiCard.querySelectorAll('button')].find(b => (b.getAttribute('onclick') || '').includes('toggleFavoriteFromCard'));
ok(!!heartBtn, 'yazı kartında favori kalbi var');
heartBtn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval('favoriteWriters.length') === 2, 'kart kalbi yazarı favorilere ekledi');
ok(window.eval("isFavoriteWriter('Mahfi Eğilmez', 'Kendime Yazılar')"), 'karttan eklenen yazar doğru kaydedildi');
window.eval('applyFilters()');
const mahfiCard2 = [...doc.querySelectorAll('#articles-list article')].find(c => /Mahfi/.test(c.textContent));
ok(/fill-accent/.test([...mahfiCard2.querySelectorAll('button')].find(b => (b.getAttribute('onclick') || '').includes('toggleFavoriteFromCard')).innerHTML),
  'favori yazarın kart kalbi dolu görünüyor');

// Keşfet çiplerinde kalp
window.eval(`
  writersData = { fetchedAt: new Date().toISOString(), total: 2, papers: [
    { key: 'hurriyet', name: 'Hürriyet', count: 2, writers: [
      { name: 'Ahmet Hakan', url: 'http://a', photo: 'p1.jpg' },
      { name: 'Zeynep Başka', url: 'http://b', photo: '' },
      { name: 'Portresiz Yazar', url: 'http://c', photo: 'p1.jpg' } ] } ] };
  writersLoaded = true;
`);
window.eval("setTab('discover')");
const chipHearts = [...doc.querySelectorAll('#writers-list button[data-fav-writer]')];
ok(chipHearts.length === 3, 'Keşfet’te her yazar çipinde kalp var');
const favChip = chipHearts.find(b => b.dataset.favWriter === 'Ahmet Hakan');
ok(favChip.getAttribute('aria-pressed') === 'true', 'favori yazarın kalbi Keşfet’te dolu (ad yazım farkına rağmen)');
ok(chipHearts.every(b => b.closest('span.inline-flex').querySelector('button[data-writer]')),
  'Keşfet çiplerinde ad düğmesi ile kalp bir arada');
const otherChip = chipHearts.find(b => b.dataset.favWriter === 'Zeynep Başka');
otherChip.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval('favoriteWriters.length') === 3, 'Keşfet kalbi yeni yazarı favorilere ekledi');
ok(window.eval("favoriteWriters.some(f => f.name === 'Zeynep Başka' && f.source === 'Hürriyet' && f.photo === '')"),
  'Keşfet’ten eklenen favoride gazete adı saklanıyor');
ok(doc.querySelectorAll('#writers-list button[data-fav-writer]').length === 3, 'kalp tıklamasından sonra Keşfet listesi yeniden çizildi');

// Favoriler sekmesi portre ve sayaç
window.eval("setTab('favorites')");
await new Promise(r => setTimeout(r, 120));   // loadWriters (çevrimdışı) sonuçlansın
ok(doc.getElementById('favorites-meta').textContent === '3 yazar', 'Favoriler sayacı 3 yazar');
ok(/Zeynep/.test(doc.getElementById('favorites-list').innerHTML), 'yazısı olmayan favori de Favoriler sayfasında listeleniyor');
ok(/Bugün yeni yazısı yok/.test(doc.getElementById('favorites-list').innerHTML), 'yazısı olmayan favori için "Bugün yeni yazısı yok"');
// portre: favoride fotoğraf yoksa gazete dizininden (writers.json) doldurulur
window.eval("toggleFavoriteWriter({ name: 'Portresiz Yazar', source: 'Hürriyet' })");
window.eval("renderFavorites()");
ok(/p1\.jpg/.test(doc.getElementById('favorites-list').innerHTML), 'portre gazete dizininden (writers.json) dolduruluyor');
window.eval("toggleFavoriteWriter({ name: 'Portresiz Yazar', source: 'Hürriyet' })");

// favoriden çıkar
await new Promise(r => setTimeout(r, 50));
const rmBtn = [...doc.querySelectorAll('#favorites-list button[data-remove-fav]')]
  .find(b => b.closest('.bg-white').textContent.includes('Zeynep'));
rmBtn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval('favoriteWriters.length') === 2, 'Favoriler sayfasından yazar çıkarılabildi');
ok(doc.getElementById('favorites-meta').textContent === '2 yazar', 'sayaç çıkarınca güncellendi');
ok(!/Zeynep/.test(doc.getElementById('authors-avatar-track').innerHTML), 'çıkarılan yazarın dairesi ana sayfadan düştü');

// ana sayfadaki daireden çıkar
window.eval("setTab('feed')");
const circleHeart = doc.querySelector('#authors-avatar-track [onclick^="unfavoriteFromAvatar"]');
ok(!!circleHeart, 'ana sayfadaki dairede favoriden çıkarma kalbi var');
const circleName = circleHeart.closest('[data-name]').dataset.name;
circleHeart.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(!window.eval(`isFavoriteWriter(${JSON.stringify(circleName)}, '')`), 'dairedeki kalple favori çıkarıldı');

// favorideki yazarın yazısı yoksa bilgi kartı
window.eval("toggleFavoriteWriter({ name: 'Yok Yazar', source: 'Sabah', url: 'http://yok' })");
window.eval("setTab('feed')");
window.eval('quickOpenByAuthor("Yok Yazar", "Sabah")');
ok(/köşe yazısı yok/.test(doc.getElementById('articles-list').innerHTML), 'yazısı olmayan favori yazar için bilgi kartı çıkıyor');
ok(/Gazetedeki yazar sayfasını aç/.test(doc.getElementById('articles-list').innerHTML), 'bilgi kartında gazete bağlantısı var');

// Favoriler sekmesinden yazıları aç
window.eval("setTab('favorites')");
await new Promise(r => setTimeout(r, 80));
const openBtn = doc.querySelector('#favorites-list button[data-open-fav]');
openBtn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ok(window.eval('currentTab') === 'feed', 'Favoriler’den "yazılarını aç" akış sekmesine götürüyor');

// kalıcılık: aynı kayıtla yeniden yükle
const stored = window.localStorage.getItem('kose-favorite-writers');
ok(JSON.parse(stored).length === 2, 'localStorage’da 2 favori saklı');
const dom2 = makeDom(stored);
await new Promise(r => setTimeout(r, 250));
ok(dom2.window.eval('favoriteWriters.length') === 2, 'favoriler sayfa yeniden açılınca korunuyor');
dom2.window.close();

dom.window.close();
if (fails.length) {
  console.error('\nBAŞARISIZ (' + fails.length + '):');
  fails.forEach(f => console.error('  ✗ ' + f));
  process.exit(1);
}
console.log('\nTÜM FAVORİ TESTLERİ GEÇTİ');
process.exit(0);
