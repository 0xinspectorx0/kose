// Ana ekran: "Yazarları karıştır" seçeneği + okuduğum favorilerin sona geçmesi
//   1) okunmuş favori yazarlar her zaman listenin sonunda (karıştırma kapalıyken de)
//   2) "Karıştır" düğmesi (ve Ayarlar'daki anahtar) açınca okunmamışlar karışık sırada
//   3) karışık sıra kalıcı ve kararlı (her çizimde yeniden karışmaz)
//   4) yeni favori / okunan yazar doğru gruba girer; kapatınca favoriye eklenme sırası döner
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
ok(/id="shuffle-authors-btn"/.test(html), 'ana ekranda #shuffle-authors-btn var');
ok(html.indexOf('id="shuffle-authors-btn"') < html.indexOf('id="authors-avatar-track"'),
  'düğme dairelerin (avatar şeridinin) içinde değil, başlık satırında');
ok(/id="set-shuffle"[^>]*role="switch"/.test(html), 'Ayarlar’da #set-shuffle anahtarı var');
ok(/shuffleAuthors: false/.test(html), 'varsayılan: karıştırma kapalı (shuffleAuthors: false)');
ok(html.includes("const AUTHOR_ORDER_KEY = 'kose-author-shuffle-order'"), 'karışık sıra localStorage anahtarı tanımlı');
ok(/data-lucide="shuffle"/.test(html), 'shuffle simgesi kullanılıyor');
for (const fn of ['orderedFavoriteWriters', 'setAuthorShuffle', 'paintShuffleControls', 'shuffleArray',
  'favSortKey', 'isFavoriteAuthorRead', 'loadAuthorShuffleOrder', 'saveAuthorShuffleOrder']) {
  ok(new RegExp(`function ${fn}\\(`).test(html), `${fn}() tanımlı`);
}
ok(/orderedFavoriteWriters\(\)\.map/.test(html), 'renderAuthorAvatars sıralamayı orderedFavoriteWriters’tan alıyor');

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
  isBookmarked: false, isLive: true, url: '', fullContent: '<p>x</p>',
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
  const shuffleBlock = block('// --- Ana ekran: favori yazar dairelerinin sırası ---', '// --- /ANA EKRAN SIRASI ---');
  // Düğme/anahtar bağlantıları: tıklama davranışı gerçek dinleyicilerle sınanır
  const shuffleEvents = block('// Ana ekran: "Karıştır" düğmesi', "document.getElementById('settings-reset-btn')");
  const fns = ['applyFilters', 'renderArticles', 'filterCategory',
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
  window.localStorage.setItem('kose-favorite-writers', JSON.stringify(FAVS));
  window.localStorage.setItem('kose-read-articles', JSON.stringify(READ_SEED));
  for (const [k, v] of Object.entries(extra)) window.localStorage.setItem(k, v);
  // let/const bağlamaları ayrı eval çağrıları arasında paylaşılmadığı için, durumu
  // dışarı açan küçük yardımcılar aynı eval bloğunun sonuna eklenir (yalnızca test).
  const harness = `
    window.__t = {
      shuffleOn: () => appSettings.shuffleAuthors,
      favNames: () => favoriteWriters.map(f => f.name),
      displayOrder: () => orderedFavoriteWriters().map(f => f.name),
      readIds: () => [...readArticles],
      setFavs: (list) => { favoriteWriters = list.slice(); saveFavoriteWriters(); renderAuthorAvatars(); },
      keyOf: (name, source) => favSortKey({ name, source: source || 'Gazete A' })
    };`;
  window.eval([...srcConsts, settingsBlock, readStateBlock, favoritesBlock, shuffleBlock,
    ...fns.map(extract), shuffleEvents, harness].join('\n'));
  // Karıştırma her koşumda aynı çıksın: Fisher-Yates'te j=0 (diziyi bir kaydırır)
  window.Math.random = () => 0;
  return { window, doc };
}

let { window, doc } = boot();
const circleNames = () => [...doc.querySelectorAll('#authors-avatar-track > div[data-name]')].map(el => el.dataset.name);
const btn = doc.getElementById('shuffle-authors-btn');
const storedOrder = () => JSON.parse(window.localStorage.getItem('kose-author-shuffle-order') || '[]');
const settingsSaved = () => JSON.parse(window.localStorage.getItem('kose-settings') || '{}');
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

console.log('\n[C] OKUDUĞUM FAVORİLER SONA (karıştırma kapalı)');
window.renderAuthorAvatars();
const order0 = circleNames();
ok(order0.join('|') === ['Ali Bir', 'Can Üç', 'Deniz Dört', 'Fatih Altı', 'Ayşe İki', 'Ece Beş'].join('|'),
  'sıra: okunmamışlar önde, okunanlar sonda', order0.join(', '));
ok(window.__t.shuffleOn() === false, 'karıştırma varsayılan olarak kapalı');
ok(btn.getAttribute('aria-pressed') === 'false' && btn.textContent.trim() === 'Karıştır',
  'düğme kapalı durumda: aria-pressed=false, etiket "Karıştır"');
ok(btn.style.display !== 'none', 'favori varken düğme görünür');
ok(window.__t.displayOrder().join('|') === order0.join('|'), 'çizilen sıra = orderedFavoriteWriters()');

console.log('\n[D] "KARIŞTIR" AÇIK');
click(btn);
const order1 = circleNames();
ok(window.__t.shuffleOn() === true, 'karıştırma açıldı (appSettings)');
ok(btn.getAttribute('aria-pressed') === 'true' && btn.textContent.trim() === 'Karışık',
  'düğme açık durumda: aria-pressed=true, etiket "Karışık"');
ok(/bg-accent/.test(btn.className), 'düğme turuncu (aktif) tonda');
ok(settingsSaved().shuffleAuthors === true, 'seçim Ayarlar’a (localStorage) yazıldı');
ok(storedOrder().length === FAVS.length, 'karışık sıra kaydedildi', `${storedOrder().length} anahtar`);
const unreadShuffled = order1.slice(0, 4);
const readPart = order1.slice(4);
ok(unreadShuffled.slice().sort().join('|') === order0.slice(0, 4).slice().sort().join('|'),
  'karıştırma yalnızca okunmamışları yer değiştirdi', unreadShuffled.join(', '));
ok(unreadShuffled.join('|') !== order0.slice(0, 4).join('|'), 'okunmamışların sırası gerçekten karıştı');
ok(readPart.join('|') === READ_NAMES.join('|'), 'okunanlar yine sonda ve kendi içinde sıralı', readPart.join(', '));
window.renderAuthorAvatars();
ok(circleNames().join('|') === order1.join('|'), 'karışık sıra kararlı: ikinci çizimde değişmiyor');

console.log('\n[E] SONRADAN EKLENEN FAVORİ / OKUNAN YAZAR');
window.toggleFavoriteWriter({ name: 'Gizem Yedi', source: 'Gazete A' });
window.articles.push({ id: 5999, author: 'Gizem Yedi', source: 'Gazete A', avatar: '', category: 'Gündem',
  title: 'Gizem yazısı', snippet: 'x', readTime: '2 dk', date: 'Bugün', isBookmarked: false, isLive: true,
  url: '', fullContent: '<p>x</p>' });
window.renderAuthorAvatars();
const order2 = circleNames();
ok(order2[4] === 'Gizem Yedi', 'yeni favori okunmamış grubun sonuna eklendi', order2.join(', '));
ok(order2.slice(5).join('|') === READ_NAMES.join('|'), 'okunanlar hâlâ sonda');
window.markArticleRead(ARTS[0].id);   // Ali Bir’in yazısı okundu
window.renderAuthorAvatars();
const order3 = circleNames();
ok(order3.indexOf('Ali Bir') >= order3.indexOf('Gizem Yedi'),
  'okunan yazar (Ali Bir) karışık gruptan çıkıp sona geçti', order3.join(', '));
ok(order3.slice(-3).join('|') === 'Ayşe İki|Ece Beş|Ali Bir', 'okunanlar sonda kendi sırasıyla', order3.slice(-3).join(', '));

console.log('\n[F] KAPATINCA FAVORİYE EKLENME SIRASI DÖNER');
click(btn);
const order4 = circleNames();
ok(window.__t.shuffleOn() === false && btn.getAttribute('aria-pressed') === 'false', 'karıştırma kapandı');
ok(storedOrder().length === 0, 'kayıtlı karışık sıra temizlendi');
ok(order4.join('|') === ['Can Üç', 'Deniz Dört', 'Fatih Altı', 'Gizem Yedi', 'Ali Bir', 'Ayşe İki', 'Ece Beş'].join('|'),
  'favoriye eklenme sırasına dönüldü (okunanlar yine sonda)', order4.join(', '));
ok(order4.slice(-3).join('|') === ['Ali Bir', 'Ayşe İki', 'Ece Beş'].join('|'),
  'okunan grup kendi içinde favoriye eklenme sırasında', order4.slice(-3).join(', '));

console.log('\n[G] AYARLAR ANAHTARI + GÖRÜNÜRLÜK');
click(doc.getElementById('set-shuffle'));
ok(window.__t.shuffleOn() === true, 'Ayarlar’dan açılabiliyor');
ok(doc.getElementById('set-shuffle').getAttribute('aria-checked') === 'true', 'anahtar işaretlendi (aria-checked)');
ok(btn.textContent.trim() === 'Karışık', 'ana ekran düğmesi de güncellendi');
window.renderSettings();
ok(doc.getElementById('set-shuffle').getAttribute('aria-checked') === 'true', 'renderSettings sonrası anahtar açık');
window.__t.setFavs([]);
ok(btn.style.display === 'none', 'favori yokken "Karıştır" düğmesi gizli');
window.__t.setFavs(FAVS);
ok(btn.style.display !== 'none' && circleNames().length === FAVS.length, 'favori eklenince düğme geri geldi');

console.log('\n[H] KALICILIK (sayfa yeniden açılışı)');
const orderRaw = window.localStorage.getItem('kose-author-shuffle-order');
const settingsRaw = window.localStorage.getItem('kose-settings');
const favRaw = window.localStorage.getItem('kose-favorite-writers');
window.close();
const reborn = boot({ 'kose-settings': settingsRaw, 'kose-author-shuffle-order': orderRaw, 'kose-favorite-writers': favRaw });
reborn.window.renderAuthorAvatars();
const rebornOrder = [...reborn.doc.querySelectorAll('#authors-avatar-track > div[data-name]')].map(el => el.dataset.name);
ok(reborn.window.__t.shuffleOn() === true, 'yeniden açılışta karıştırma açık kalıyor');
ok(reborn.doc.getElementById('shuffle-authors-btn').getAttribute('aria-pressed') === 'true',
  'düğme açık durumda geri geliyor');
const nameByKey = Object.fromEntries(FAVS.map(f => [reborn.window.__t.keyOf(f.name, f.source), f.name]));
const storedNames = JSON.parse(orderRaw).map(k => nameByKey[k]).filter(Boolean);
const expectedReborn = [...storedNames.filter(n => !READ_NAMES.includes(n)),
                        ...storedNames.filter(n => READ_NAMES.includes(n))];
ok(rebornOrder.join('|') === expectedReborn.join('|'),
  'kayıtlı karışık sıra yeniden uygulanıyor (okunanlar sonda)', rebornOrder.join(', '));
ok(rebornOrder.slice(-2).join('|') === READ_NAMES.join('|'), 'okunanlar yeniden açılışta da sonda');
reborn.window.close();

console.log('');
if (fails.length) {
  console.log(`KALAN ${fails.length} MADDE:`);
  fails.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
console.log('TÜM KARIŞTIRMA / OKUNAN-SONDA TESTLERİ GEÇTİ');
