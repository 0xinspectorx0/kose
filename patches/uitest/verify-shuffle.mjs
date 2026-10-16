// Ana ekran: "Karıştır" — favori yazar daireleri + yazı listesi
//   1) okunmuş favori yazarlar her zaman listenin sonunda (karıştırma kapalıyken de)
//   2) "Karıştır" düğmeleri (favori başlığı + kategori satırı) ve Ayarlar anahtarı
//      aynı ayarı değiştirir: hem daireler hem aşağıdaki yazılar karışır
//   3) karışık sıralar kalıcı ve kararlı (her çizimde yeniden karışmaz)
//   4) yeni yazılar başa, yeni favoriler okunmamış grubun sonuna gelir
//   5) kapatınca doğal sıra döner (favoriler: eklenme sırası, akış: veri sırası)
import { readFileSync } from 'node:fs';
import { JSDOM } from '/tmp/uitest/node_modules/jsdom/lib/api.js';

const html = readFileSync('/home/user/kose/index.html', 'utf8');
const fails = [];
const ok = (cond, msg, detail = '') => {
  if (!cond) { fails.push(msg); console.log(`  ✗ ${msg}${detail ? ' — ' + detail : ''}`); }
  else console.log(`  ✓ ${msg}${detail ? ' — ' + detail : ''}`);
};

function extract(name) {
  let start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error('bulunamadı: ' + name);
  if (html.slice(Math.max(0, start - 6), start) === 'async ') start = html.lastIndexOf('async', start);
  let d = 0;
  for (let j = html.indexOf('{', start); j < html.length; j++) {
    if (html[j] === '{') d++;
    else if (html[j] === '}') { d--; if (!d) return html.slice(start, j + 1); }
  }
  throw new Error('kapanmadı: ' + name);
}
const extractConst = n => html.match(new RegExp('const ' + n + ' = [^;]+;'))[0];
const block = (a, b) => {
  const i = html.indexOf(a), j = html.indexOf(b);
  if (i < 0 || j < 0) throw new Error(`blok bulunamadı: ${a} (i=${i}, j=${j})`);
  return html.slice(i, j);
};

console.log('\n[A] STATİK YAPI');
ok(/id="shuffle-authors-btn"/.test(html), 'favori başlığında #shuffle-authors-btn var');
ok(/id="shuffle-feed-btn"/.test(html), 'kategori (Tümü) satırında #shuffle-feed-btn var');
ok(html.indexOf('id="shuffle-feed-btn"') > html.indexOf("filterCategory('Tümü')"),
  'yazı karıştırma düğmesi kategori pilleriyle aynı satırda (Tümü’nün yanında)');
ok(/id="set-shuffle"[^>]*role="switch"/.test(html), 'Ayarlar’da #set-shuffle anahtarı var');
ok(/shuffle: false/.test(html), 'varsayılan: karıştırma kapalı (shuffle: false)');
ok(/stored\.shuffleAuthors/.test(html), 'eski shuffleAuthors ayarı yeni shuffle’a taşınıyor');
ok(html.includes("const ARTICLE_ORDER_KEY = 'kose-article-shuffle-order'"), 'yazı sırası localStorage anahtarı tanımlı');
ok(/data-lucide="shuffle"/.test(html), 'shuffle simgesi kullanılıyor (iki düğme)');
for (const fn of ['orderedFavoriteWriters', 'orderedArticles', 'setShuffle', 'paintShuffleControls', 'shuffleArray',
  'favSortKey', 'articleSortKey', 'isFavoriteAuthorRead', 'loadOrderList', 'saveOrderList', 'ensureShuffleOrders']) {
  ok(new RegExp(`function ${fn}\\(`).test(html), `${fn}() tanımlı`);
}
ok(!/function setAuthorShuffle\(/.test(html), 'eski setAuthorShuffle kaldırıldı (tek ayar: setShuffle)');
ok(/renderArticles\(orderedArticles\(filtered\)\)/.test(html), 'applyFilters akışı orderedArticles ile çiziyor');
ok(/for \(const id of \['shuffle-authors-btn', 'shuffle-feed-btn', 'set-shuffle'\]\)/.test(html),
  'üç kontrol aynı ayarı değiştiriyor');
ok(/paintShuffleControls\(\);   \/\/ "Karıştır" düğmeleri yalnızca ait oldukları sekmede görünür/.test(html),
  'sekme değişiminde karıştırma düğmeleri tazeleniyor');
ok(/\(currentTab === 'feed' && articles\.length\)/.test(html),
  'yazı karıştırma düğmesi yalnızca Akış sekmesinde görünür');

console.log('\n[B] TEST ORTAMI');
// 6 favori; 2’si tamamen okunmuş (Ayşe İki, Ece Beş)
const FAVS = [
  { name: 'Ali Bir', source: 'Gazete A', photo: '' },
  { name: 'Ayşe İki', source: 'Gazete A', photo: '' },
  { name: 'Can Üç', source: 'Gazete A', photo: '' },
  { name: 'Deniz Dört', source: 'Gazete A', photo: '' },
  { name: 'Ece Beş', source: 'Gazete A', photo: '' },
  { name: 'Fatih Altı', source: 'Gazete A', photo: '' },
];
const ARTS = FAVS.map((f, i) => ({
  id: 5000 + i, author: f.name, source: f.source, avatar: '', category: 'Gündem',
  title: `${f.name} yazısı`, snippet: 'x', readTime: '2 dk', date: 'Bugün',
  isBookmarked: false, isLive: true, url: `https://gazete.test/${5000 + i}`, fullContent: '<p>x</p>',
}));
const READ_SEED = [ARTS[1].id, ARTS[4].id];          // Ayşe İki + Ece Beş okundu
const READ_NAMES = ['Ayşe İki', 'Ece Beş'];

function boot(extra = {}) {
  const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const doc = window.document;
  const srcConsts = ['DAILY_FEED_URL', 'WRITERS_URL', 'isoDayKey', 'FEED_RECHECK_MS', 'STALE_AFTER_HOURS'].map(extractConst);
  const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
  const readStateBlock = block('// --- Okundu takibi', 'function applyReadState()');
  const favoritesBlock = block('// --- Favori yazarlar: kalpler localStorage', 'let readerFontSize =');
  const shuffleBlock = block('// --- Ana ekran: karıştırma (favori daireler + yazı listesi) ---', '// --- /ANA EKRAN SIRASI ---');
  // Düğme/anahtar bağlantıları: tıklama davranışı gerçek dinleyicilerle sınanır
  const shuffleEvents = block('// Ana ekran: iki "Karıştır" düğmesi', "document.getElementById('settings-reset-btn')");
  const fns = ['applyFilters', 'renderArticles', 'filterCategory', 'setTab',
    'toggleFavoriteWriter', 'findFavoriteWriter', 'isFavoriteWriter', 'sameSource', 'favKeyName',
    'deaccentTr', 'favoriteArticles', 'findWriterPhoto', 'renderFavorites', 'escapeHtml', 'normalizeTr',
    'formatAuthorName', 'initialAvatar', 'applyReadState', 'markArticleRead', 'isAuthorFullyRead',
    'cleanWriterName', 'isPersonName', 'cleanWriters', 'isPassiveWriter', 'passiveEntry', 'sameWriterEntry',
    'isHiddenWriter', 'isHiddenPaper', 'renderManageCards', 'renderAuthorAvatars', 'paintToggle',
    'renderSettings', 'saveSettings'];

  window.lucide = { createIcons() {} };
  window.articles = JSON.parse(JSON.stringify(ARTS));
  window.initialArticles = [];
  window.currentFilteredCategory = 'Tümü';
  window.expandedPapers = new Set();
  window.currentTab = 'feed';
  window.writersData = null;
  window.writersLoaded = false;   // Keşfet henüz yüklenmedi (favori kalbi çizimi bu koşumun konusu değil)
  window.renderVoiceOptions = () => {};   // ses seçimi listesi bu koşumun konusu değil
  window.loadWriters = () => {};          // Keşfet çağrıları bu koşumun konusu değil
  const domIds = {
    authorsAvatarTrack: 'authors-avatar-track', articlesListEl: 'articles-list',
    writersListEl: 'writers-list', writersMetaEl: 'writers-meta', writersLoadingEl: 'writers-loading',
    writersEmptyEl: 'writers-empty', writersSearchInput: 'writers-search', searchInput: 'search-input',
    syncTimeEl: 'sync-time', feedAuthorsSection: 'feed-authors-section',
    feedCategoriesSection: 'feed-categories-section', syncBannerEl: 'sync-banner',
    writersViewEl: 'writers-view', settingsViewEl: 'settings-view', authorTooltipEl: 'author-tooltip',
    favoritesViewEl: 'favorites-view', favoritesListEl: 'favorites-list',
    favoritesMetaEl: 'favorites-meta', favoritesEmptyEl: 'favorites-empty',
    writersManageEl: 'writers-manage',
  };
  for (const [k, id] of Object.entries(domIds)) window[k] = doc.getElementById(id);
  window.Element.prototype.scrollTo = () => {};   // jsdom'da yok; sekme geçişleri bunu kullanır
  window.localStorage.setItem('kose-favorite-writers', JSON.stringify(FAVS));
  window.localStorage.setItem('kose-read-articles', JSON.stringify(READ_SEED));
  for (const [k, v] of Object.entries(extra)) window.localStorage.setItem(k, v);
  // let/const bağlamaları ayrı eval çağrıları arasında paylaşılmadığı için, durumu
  // dışarı açan küçük yardımcılar aynı eval bloğunun sonuna eklenir (yalnızca test).
  const harness = `
    window.__t = {
      shuffleOn: () => appSettings.shuffle,
      favNames: () => favoriteWriters.map(f => f.name),
      displayOrder: () => orderedFavoriteWriters().map(f => f.name),
      feedOrder: () => orderedArticles(articles).map(articleSortKey),
      articleKeyOfId: (id) => articleSortKey(articles.find(a => a.id === id)),
      setFavs: (list) => { favoriteWriters = list.slice(); saveFavoriteWriters(); renderAuthorAvatars(); },
      renderFeed: () => applyFilters()
    };`;
  window.eval([...srcConsts, settingsBlock, readStateBlock, favoritesBlock, shuffleBlock,
    ...fns.map(extract), shuffleEvents, harness].join('\n'));
  // Karıştırma her koşumda aynı çıksın: Fisher-Yates'te j=0 (diziyi bir kaydırır)
  window.Math.random = () => 0;
  return { window, doc };
}

let { window, doc } = boot();
const circleNames = () => [...doc.querySelectorAll('#authors-avatar-track > div[data-name]')].map(el => el.dataset.name);
// Akıştaki kartların sırasını, kartın openReader(<id>) bağlantısından okuyup anahtara çevirir
const feedKeys = () => [...doc.querySelectorAll('#articles-list article')]
  .map(a => Number(String(a.getAttribute('onclick')).match(/openReader\((\d+)\)/)[1]))
  .map(id => window.__t.articleKeyOfId(id));
const naturalFeedKeys = () => window.articles.map(a => window.__t.articleKeyOfId(a.id));
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const favBtn = doc.getElementById('shuffle-authors-btn');
const feedBtn = doc.getElementById('shuffle-feed-btn');
const storedOrder = k => JSON.parse(window.localStorage.getItem(k) || '[]');
const settingsSaved = () => JSON.parse(window.localStorage.getItem('kose-settings') || '{}');

console.log('\n[C] KARIŞTIRMA KAPALI: OKUDUĞUM FAVORİLER SONA, AKIŞ DOĞAL SIRADA');
window.renderAuthorAvatars();
window.__t.renderFeed();
const order0 = circleNames();
ok(order0.join('|') === ['Ali Bir', 'Can Üç', 'Deniz Dört', 'Fatih Altı', 'Ayşe İki', 'Ece Beş'].join('|'),
  'daireler: okunmamışlar önde, okunanlar sonda', order0.join(', '));
ok(window.__t.shuffleOn() === false, 'karıştırma varsayılan olarak kapalı');
ok(feedKeys().join('|') === naturalFeedKeys().join('|'), 'akış doğal (veri) sırasında');
ok(favBtn.getAttribute('aria-pressed') === 'false' && favBtn.textContent.trim() === 'Karıştır',
  'favori düğmesi kapalı: aria-pressed=false, etiket "Karıştır"');
ok(feedBtn.getAttribute('aria-pressed') === 'false', 'yazı düğmesi kapalı görünüyor');
ok(feedBtn.style.display !== 'none', 'yazı düğmesi görünür (yazılar yüklü)');

console.log('\n[D] KATEGORİ SATIRINDAKİ DÜĞME: İKİ LİSTE BİRDEN KARIŞIYOR');
click(feedBtn);
const order1 = circleNames();
const feed1 = feedKeys();
ok(window.__t.shuffleOn() === true, 'karıştırma açıldı (appSettings.shuffle)');
ok(settingsSaved().shuffle === true, 'seçim Ayarlar’a (localStorage) yazıldı');
ok(!('shuffleAuthors' in settingsSaved()), 'eski ayar anahtarı kayıtta kalmıyor');
ok(storedOrder('kose-author-shuffle-order').length === FAVS.length, 'favori sırası kaydedildi',
  `${storedOrder('kose-author-shuffle-order').length} anahtar`);
ok(storedOrder('kose-article-shuffle-order').length === ARTS.length, 'yazı sırası kaydedildi',
  `${storedOrder('kose-article-shuffle-order').length} anahtar`);
ok(order1.slice(0, 4).slice().sort().join('|') === order0.slice(0, 4).slice().sort().join('|') &&
  order1.slice(0, 4).join('|') !== order0.slice(0, 4).join('|'),
  'okunmamış daireler karıştı (okunanlar yerinde)', order1.join(', '));
ok(order1.slice(4).join('|') === READ_NAMES.join('|'), 'okunanlar yine sonda', order1.slice(4).join(', '));
const storedFeed = storedOrder('kose-article-shuffle-order');
ok(feed1.join('|') === storedFeed.join('|'), 'akış tam olarak kayıtlı karışık sırada çizildi');
ok(feed1.join('|') !== naturalFeedKeys().join('|'), 'akış sırası gerçekten değişti');
ok(feedBtn.getAttribute('aria-pressed') === 'true' && /bg-accent/.test(feedBtn.className),
  'yazı düğmesi açık: aria-pressed=true, turuncu');
ok(favBtn.textContent.trim() === 'Karışık' && favBtn.getAttribute('aria-pressed') === 'true',
  'favori düğmesi de açık duruma geçti (senkron)');
window.__t.renderFeed();
ok(feedKeys().join('|') === feed1.join('|'), 'karışık sıra kararlı: ikinci çizimde değişmiyor');
window.renderAuthorAvatars();
ok(circleNames().join('|') === order1.join('|'), 'dairelerin karışık sırası da kararlı');

console.log('\n[E] YENİ YAZI BAŞA · YENİ FAVORİ SONA');
const NEW_URL = 'https://gazete.test/yeni-yazi';
window.articles.push({ id: 5999, author: 'Gizem Yedi', source: 'Gazete A', avatar: '', category: 'Gündem',
  title: 'Yepyeni yazı', snippet: 'y', readTime: '1 dk', date: 'Bugün', isBookmarked: false, isLive: true,
  url: NEW_URL, fullContent: '<p>y</p>' });
window.__t.renderFeed();
const feed2 = feedKeys();
ok(feed2[0] === NEW_URL, 'sonradan gelen yeni yazı karışık listenin başında', feed2[0]);
ok(feed2.slice(1).join('|') === feed1.join('|'), 'mevcut yazıların karışık sırası korundu');
window.toggleFavoriteWriter({ name: 'Gizem Yedi', source: 'Gazete A' });
window.renderAuthorAvatars();
const order2 = circleNames();
ok(order2.indexOf('Gizem Yedi') === 4, 'yeni favori karışık grubun sonuna eklendi', order2.join(', '));
window.markArticleRead(ARTS[0].id);   // Ali Bir okundu -> sona geçer
window.renderAuthorAvatars();
const order3 = circleNames();
ok(order3.slice(-3).join('|') === 'Ayşe İki|Ece Beş|Ali Bir', 'okunan yazar sona geçti', order3.slice(-3).join(', '));

console.log('\n[F] AYARLAR ANAHTARI + KAPATINCA DOĞAL SIRA');
click(doc.getElementById('set-shuffle'));
ok(window.__t.shuffleOn() === false, 'Ayarlar’dan kapatılabiliyor');
ok(storedOrder('kose-article-shuffle-order').length === 0 && storedOrder('kose-author-shuffle-order').length === 0,
  'iki karışık sıra da temizlendi');
const feed3 = feedKeys();
ok(feed3.join('|') === window.articles.map(a => window.__t.articleKeyOfId(a.id)).join('|'),
  'akış veri sırasına döndü', feed3.slice(0, 3).join(', '));
ok(feed3[0] !== NEW_URL, 'yeni yazı artık başta değil (doğal sırada sonunda)');
const order4 = circleNames();
ok(order4.join('|') === ['Can Üç', 'Deniz Dört', 'Fatih Altı', 'Gizem Yedi', 'Ali Bir', 'Ayşe İki', 'Ece Beş'].join('|'),
  'daireler favoriye eklenme sırasına döndü (okunanlar sonda)', order4.join(', '));
ok(feedBtn.getAttribute('aria-pressed') === 'false' && favBtn.getAttribute('aria-pressed') === 'false',
  'iki düğme de kapalı gösteriyor');
ok(doc.getElementById('set-shuffle').getAttribute('aria-checked') === 'false', 'Ayarlar anahtarı kapalı');

console.log('\n[G] FAVORİ BAŞLIĞINDAKİ DÜĞME + GÖRÜNÜRLÜK');
click(favBtn);
ok(window.__t.shuffleOn() === true, 'favori düğmesi de karıştırmayı açıyor (aynı ayar)');
ok(feedBtn.getAttribute('aria-pressed') === 'true', 'yazı düğmesi senkron');
window.__t.setFavs([]);
ok(favBtn.style.display === 'none', 'favori yokken başlıktaki düğme gizli');
ok(feedBtn.style.display !== 'none', 'yazı düğmesi yine görünür (yazılar var)');
window.__t.setFavs(FAVS);
ok(favBtn.style.display !== 'none' && circleNames().length === FAVS.length, 'favori eklenince düğme geri geldi');

console.log('\n[H] YAZI DÜĞMESİ YALNIZCA AKIŞ SEKMESİNDE');
window.setTab('saved');
ok(feedBtn.style.display === 'none', 'Kaydedilen sekmesinde yazı karıştırma düğmesi gizli');
ok(doc.getElementById('articles-list') !== null, 'Kaydedilen listesi yine çiziliyor');
window.setTab('feed');
ok(feedBtn.style.display !== 'none', 'Akış sekmesine dönünce düğme geri geliyor');
window.setTab('discover');
ok(feedBtn.style.display === 'none', 'Keşfet sekmesinde yazı düğmesi gizli (kategori satırı görünmüyor)');
ok(favBtn.style.display !== 'none', 'Keşfet sekmesinde favori düğmesi yerinde kalıyor');
window.setTab('feed');

console.log('\n[I] SIRA ÜRETİLMEMİŞKEN KARIŞTIRMA AÇIK (tembel üretim)');
window.close();
const lazy = boot({ 'kose-settings': JSON.stringify({ shuffle: true }) });   // kayıtlı sıra YOK
lazy.window.renderAuthorAvatars();
lazy.window.__t.renderFeed();
ok(lazy.window.__t.shuffleOn() === true, 'ayar kayıttan açık geldi');
ok(JSON.parse(lazy.window.localStorage.getItem('kose-article-shuffle-order') || '[]').length === ARTS.length,
  'yazı sırası ilk çizimde üretilip kaydedildi');
ok(JSON.parse(lazy.window.localStorage.getItem('kose-author-shuffle-order') || '[]').length === FAVS.length,
  'favori sırası ilk çizimde üretilip kaydedildi');
const lazyFeed = [...lazy.doc.querySelectorAll('#articles-list article')]
  .map(a => Number(String(a.getAttribute('onclick')).match(/openReader\((\d+)\)/)[1]))
  .map(id => lazy.window.__t.articleKeyOfId(id));
ok(lazyFeed.join('|') !== ARTS.map(a => a.url).join('|'), 'akış ilk çizimde karışık geldi', lazyFeed.slice(0, 3).join(', '));
const lazyCircles = [...lazy.doc.querySelectorAll('#authors-avatar-track > div[data-name]')].map(el => el.dataset.name);
ok(lazyCircles.slice(0, 4).join('|') !== ['Ali Bir', 'Can Üç', 'Deniz Dört', 'Fatih Altı'].join('|'),
  'daireler de ilk çizimde karışık geldi', lazyCircles.slice(0, 4).join(', '));
ok(lazyCircles.slice(-2).join('|') === READ_NAMES.join('|'), 'okunanlar yine sonda');
lazy.window.close();

console.log('\n[J] KALICILIK (sayfa yeniden açılışı)');
const authorRaw = window.localStorage.getItem('kose-author-shuffle-order');
const articleRaw = window.localStorage.getItem('kose-article-shuffle-order');
const settingsRaw = window.localStorage.getItem('kose-settings');
const favRaw = window.localStorage.getItem('kose-favorite-writers');
window.close();
const reborn = boot({ 'kose-settings': settingsRaw, 'kose-author-shuffle-order': authorRaw,
  'kose-article-shuffle-order': articleRaw, 'kose-favorite-writers': favRaw });
reborn.window.renderAuthorAvatars();
reborn.window.__t.renderFeed();
const rebornFavs = [...reborn.doc.querySelectorAll('#authors-avatar-track > div[data-name]')].map(el => el.dataset.name);
const rebornFeed = [...reborn.doc.querySelectorAll('#articles-list article')]
  .map(a => Number(String(a.getAttribute('onclick')).match(/openReader\((\d+)\)/)[1]))
  .map(id => reborn.window.__t.articleKeyOfId(id));
ok(reborn.window.__t.shuffleOn() === true, 'yeniden açılışta karıştırma açık kalıyor');
ok(reborn.doc.getElementById('shuffle-feed-btn').getAttribute('aria-pressed') === 'true' &&
  reborn.doc.getElementById('shuffle-authors-btn').getAttribute('aria-pressed') === 'true',
  'iki düğme de açık durumda geri geliyor');
const savedArticleOrder = JSON.parse(articleRaw);
const firstBatch = window.articles.slice(0, 6).map(a => window.__t.articleKeyOfId(a.id));
ok(rebornFeed.slice(0, 6).join('|') === savedArticleOrder.filter(k => firstBatch.includes(k)).join('|'),
  'kayıtlı karışık yazı sırası yeniden uygulanıyor', rebornFeed.slice(0, 3).join(', '));
ok(rebornFavs.slice(-2).join('|') === READ_NAMES.join('|'), 'okunan favoriler yeniden açılışta da sonda');
reborn.window.close();

console.log('');
if (fails.length) {
  console.log(`KALAN ${fails.length} MADDE:`);
  fails.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
console.log('TÜM KARIŞTIRMA TESTLERİ GEÇTİ (favoriler + yazı listesi)');
