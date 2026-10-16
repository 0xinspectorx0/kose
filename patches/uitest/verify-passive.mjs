// Pasif yazarlar + Keşfet'ten silme regresyonu
//   · Keşfet'te ⋯ → "Pasife al" / "Sil" akışı
//   · pasif yazarın yazısı akışta soluk + "PASİF YAZAR" etiketiyle kalır
//   · "Gizlenenler" kartından geri getirme
//   · depo listesi (data/passive-writers.json) ve Ayarlar'daki JSON çıktısı
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
const ids = ['action-sheet', 'action-sheet-panel', 'sheet-actions', 'sheet-note', 'writers-manage',
  'passive-export', 'passive-copy-btn', 'passive-download-btn', 'app-toast', 'reader-passive-badge'];
ids.forEach(id => ok(new RegExp(`id="${id}"`).test(html), `#${id} var`));
for (const fn of ['setPassiveWriter', 'passiveEntry', 'isPassiveWriter', 'isHiddenWriter', 'isHiddenPaper',
  'hideWriter', 'restoreWriter', 'hidePaper', 'restorePaper', 'renderManageCards', 'buildPassiveConfig',
  'passiveExportJson', 'loadPassiveConfig', 'openWriterSheet', 'renderActionSheet', 'closeActionSheet',
  'reactivatePassiveFromCard', 'showToast', 'afterWriterStateChange']) {
  ok(new RegExp(`function ${fn}\\(`).test(html), `${fn}() tanımlı`);
}
['kose-passive-writers', 'kose-hidden-writers', 'kose-hidden-papers'].forEach(k =>
  ok(html.includes(k), `localStorage anahtarı: ${k}`));
ok(html.includes("const PASSIVE_URL = 'data/passive-writers.json'"), 'depo dosyası yolu data/passive-writers.json');

console.log('\n[B] JSDOM ORTAMI');
const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
const doc = window.document;
const srcConsts = ['DAILY_FEED_URL', 'WRITERS_URL', 'isoDayKey', 'FEED_RECHECK_MS', 'STALE_AFTER_HOURS'].map(extractConst);
const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
const readStateBlock = block('// --- Okundu takibi', 'function applyReadState()');
// Pasif/gizli liste mantığı favori bloğunun içinde yaşıyor (aynı localStorage deseni)
const passiveBlock = block('// --- Favori yazarlar: kalpler localStorage', 'let readerFontSize =');
const shuffleBlock = block('// --- Ana ekran: favori yazar dairelerinin sırası ---', '// --- /ANA EKRAN SIRASI ---');
const writersEvents = block('// Keşfet: yazar adına tıklayınca akışta o yazarın yazıları listelenir', '// --- Bottom Tab Router');
const settingsEvents = block('// --- Ayarlar sekmesi olayları ---', '// Initialize View');
const readerBlock = block('// --- Okuyucu puntosu: A- / A+ ---', '// --- Seslendirme (Web Speech API');
const audioBlock = block('// --- Seslendirme (Web Speech API', '// --- Canlı Akışı Yenile');
const fns = ['toggleFavoriteFromCard', 'updateReaderFavoriteIcon', 'saveFavoriteWriters', 'removeFavoriteWriter',
  'openFavoriteWriterArticles', 'toggleFavoriteWriter', 'findFavoriteWriter', 'isFavoriteWriter', 'sameSource',
  'favKeyName', 'deaccentTr', 'favoriteArticles', 'findWriterPhoto', 'renderFavorites', 'escapeHtml', 'normalizeTr',
  'formatAuthorName', 'initialAvatar', 'mapLiveArticle', 'formatSyncTime', 'renderAuthorAvatars', 'applyReadState',
  'markArticleRead', 'isAuthorFullyRead', 'quickOpenByAuthor', 'renderArticles', 'applyFilters', 'filterCategory',
  'loadDailyFeed', 'writersSummary', 'filterWriters', 'buildWriterPopularity', 'writerScore', 'cleanWriterName',
  'isPersonName', 'cleanWriters', 'renderWriters', 'togglePaper', 'openWriter', 'renderWriterNotFound',
  'paintToggle', 'renderSettings', 'saveSettings', 'showAuthorTooltip', 'hideAuthorTooltip', 'setTab', 'openReader',
  'updateReaderBookmarkIcon', 'updateScrollTopBtn', 'htmlToSpeechText', 'chunkSpeechText', 'pickTtsVoice',
  'ttsVoices', 'renderVoiceOptions', 'speakNextChunk', 'restartCurrentChunk', 'finishSpeech', 'showAndPlayAudio',
  'togglePlayPause', 'resetAudio', 'updateAudioUI', 'currentTtsRate', 'formatTtsRate', 'applyTtsRate',
  'reactivatePassiveFromCard'];

window.lucide = { createIcons() {} };
window.articles = [];
window.initialArticles = [];
window.currentFilteredCategory = 'Tümü';
window.expandedPapers = new Set();
window.currentTab = 'feed';
window.readerFontSize = 16;
window.writersLoaded = true;
window.loadWriters = () => {};
const domIds = {
  authorsAvatarTrack: 'authors-avatar-track', articlesListEl: 'articles-list', writersListEl: 'writers-list',
  writersMetaEl: 'writers-meta', writersLoadingEl: 'writers-loading', writersEmptyEl: 'writers-empty',
  writersSearchInput: 'writers-search', searchInput: 'search-input', syncTimeEl: 'sync-time',
  feedAuthorsSection: 'feed-authors-section', feedCategoriesSection: 'feed-categories-section',
  syncBannerEl: 'sync-banner', writersViewEl: 'writers-view', settingsViewEl: 'settings-view',
  articleReader: 'article-reader', mainScrollEl: 'main-scroll', scrollTopBtn: 'scroll-top-btn',
  authorTooltipEl: 'author-tooltip', favoritesViewEl: 'favorites-view', favoritesListEl: 'favorites-list',
  favoritesMetaEl: 'favorites-meta', favoritesEmptyEl: 'favorites-empty',
  fontDecBtn: 'font-dec-btn', fontIncBtn: 'font-inc-btn', miniPlayerEl: 'mini-player',
  audioStrip: 'audio-player-strip', miniAudioToggle: 'mini-audio-toggle', listenArticleBtn: 'listen-article-btn',
  closeReaderBtn: 'close-reader-btn', externalLinkBtn: 'external-link-btn', readerScrollable: 'reader-scrollable',
  readerProgressBar: 'reader-progress', readerBookmarkBtn: 'reader-bookmark-btn', readerFavoriteBtn: 'reader-favorite-btn',
};
for (const [k, id] of Object.entries(domIds)) window[k] = doc.getElementById(id);
window.mainScrollEl.scrollTo = () => {};

const daily = JSON.parse(readFileSync('/home/user/kose/data/daily.json', 'utf8'));
const writersJson = JSON.parse(readFileSync('/home/user/kose/data/writers.json', 'utf8'));
// İlk yazıyı "pasif/donmuş" işaretle: kazıyıcı pasif yazarın son yazısını bu işaretle bırakır
const frozen = JSON.parse(JSON.stringify(daily.articles[0]));
frozen.passive = true;
const frozenDaily = { ...daily, articles: [frozen, ...daily.articles.slice(1)] };

window.eval([...srcConsts, settingsBlock, readStateBlock, passiveBlock, shuffleBlock, ...fns.map(extract),
  writersEvents, settingsEvents, readerBlock, audioBlock].join('\n'));

// Çevrimdışı: veriler dosyadan gelir; pasif liste ilk turda BOŞ
window.fetch = async (url) => {
  const u = String(url);
  const body = u.includes('passive-writers.json')
    ? { updatedAt: null, writers: [] }
    : u.includes('writers.json') ? writersJson : frozenDaily;
  return { ok: true, json: async () => JSON.parse(JSON.stringify(body)) };
};

window.writersData = writersJson;
window.writersLoaded = true;
await window.loadDailyFeed(false);
console.log('  günlük akış yüklendi:', window.articles.length, 'yazı |',
  'donmuş yazı:', window.articles.filter(a => a.isPassive).length);
ok(window.articles.some(a => a.isPassive), 'mapLiveArticle "passive" işaretini taşıyor (isPassive)');

// --- Yardımcılar ---
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const paperRow = name => [...doc.querySelectorAll('#writers-list > div')].find(r => r.querySelector('h3')?.textContent === name);
const stored = k => JSON.parse(window.localStorage.getItem(k) || '[]');
const sheet = doc.getElementById('action-sheet');
const panel = doc.getElementById('action-sheet-panel');
const sheetAction = act => doc.querySelector(`#sheet-actions button[data-act="${act}"]`);

console.log('\n[C] KEŞFET: ⋯ → PASİFE AL');
window.setTab('discover');
window.writersSearchInput.value = '';
window.renderWriters();
window.expandedPapers = new Set(['hurriyet']);
window.renderWriters();
const hurriyet = paperRow('Hürriyet');
const chip = hurriyet.querySelector('button[data-sheet-writer]');
const target = { name: chip.dataset.sheetWriter, source: chip.dataset.paperName, paper: chip.dataset.paper };
console.log('  hedef yazar:', target.name, '·', target.source);
ok(!!chip, 'çipte ⋯ (seçenekler) düğmesi var');
ok(!!hurriyet.querySelector('button[data-sheet-paper]'), 'gazete satırında ⋯ (gazete seçenekleri) düğmesi var');

click(chip);
ok(!sheet.classList.contains('hidden'), 'alt sayfa açıldı');
ok(doc.getElementById('sheet-title').textContent === window.formatAuthorName(target.name), 'alt sayfada yazar adı doğru');
ok(!!sheetAction('passivate'), '"Pasife al" seçeneği listelendi');
ok(!!sheetAction('hide'), '"Keşfet listesinden sil" seçeneği listelendi');
ok(!!sheetAction('open') && !!sheetAction('fav'), 'yazıları göster + favori seçenekleri var');

click(sheetAction('passivate'));
ok(panel.classList.contains('translate-y-full'), 'işlemden sonra alt sayfa kapandı');
const pasStore = stored('kose-passive-writers');
ok(pasStore.length === 1 && pasStore[0].name === target.name, 'pasif liste localStorage’a yazıldı',
  `${pasStore.length} kayıt: ${pasStore.map(p => p.name).join(', ')}`);
ok(window.isPassiveWriter(target.name, target.source) === true, 'isPassiveWriter doğru cevap veriyor');
ok(!doc.getElementById('app-toast').classList.contains('hidden'), 'bilgi mesajı (toast) göründü');

const passiveChip = [...paperRow('Hürriyet').querySelectorAll('button[data-sheet-writer]')]
  .find(b => b.dataset.sheetWriter === target.name).closest('span');
ok(passiveChip.textContent.includes('pasif'), 'çip "pasif" olarak işaretlendi', `"${passiveChip.textContent.trim().replace(/\s+/g, ' ')}"`);
ok(/FBF6EE|amber/.test(passiveChip.className), 'çip soluk (amber) tonda');

console.log('\n[C2] AKIŞTA PASİF YAZAR');
window.setTab('feed');
window.searchInput.value = target.name;
window.applyFilters();
let cards = [...window.articlesListEl.querySelectorAll('article')];
const pasCard = cards[0];
ok(cards.length > 0, 'akışta yazarın yazısı görünüyor (silinmedi, soluk)');
ok(pasCard.textContent.includes('PASİF YAZAR'), 'kartta "PASİF YAZAR" etiketi var');
ok(pasCard.textContent.includes('Aktif et'), 'kartta "Aktif et" düğmesi var');
ok(/FBF6EE|amber-200/.test(pasCard.className), 'kart soluk (amber) tonda');
ok(!!pasCard.querySelector('button[onclick*="reactivatePassiveFromCard"]'),
  'karttaki düğme reactivatePassiveFromCard\'a bağlı');
// Not: satır içi onclick'ler bu koşumda (runScripts: outside-only) çalışmaz; fonksiyonu doğrudan çağırıyoruz
const cardId = Number(String(pasCard.getAttribute('onclick')).match(/openReader\((\d+)\)/)[1]);
window.reactivatePassiveFromCard({ stopPropagation() {} }, cardId);
ok(stored('kose-passive-writers').length === 0, 'karttan "Aktif et" pasif listesini boşalttı');
window.applyFilters();
ok(![...window.articlesListEl.querySelectorAll('article')][0].textContent.includes('PASİF YAZAR'),
  'aktif edilince etiket kalktı');

console.log('\n[D] KEŞFET: YÖNETİM KARTLARI (pasif liste + gizlenenler)');
window.setTab('discover');
window.setPassiveWriter({ name: target.name, source: target.source }, true);
const manage = doc.getElementById('writers-manage');
ok(!manage.classList.contains('hidden'), 'yönetim kartları göründü');
ok(!!doc.getElementById('passive-card'), '“Pasif yazarlar” kartı var');
ok(manage.textContent.includes(window.formatAuthorName(target.name)), 'pasif yazar kartta listelendi');
click(doc.querySelector('#passive-card button[data-unpassive]'));
ok(stored('kose-passive-writers').length === 0, 'karttan "Aktif et" çalıştı');
ok(doc.getElementById('writers-manage').classList.contains('hidden'), 'liste boşalınca kartlar gizlendi');

console.log('\n[E] KEŞFET: YAZAR SİLME / GERİ GETİRME');
window.expandedPapers = new Set(['hurriyet']);
window.renderWriters();
const chipsOf = () => [...paperRow('Hürriyet').querySelectorAll('button[data-sheet-writer]')];
const beforeChips = chipsOf().length;
const delChip = chipsOf()[0];
const delName = delChip.dataset.sheetWriter;
click(delChip);
click(sheetAction('hide'));
const afterChips = chipsOf();
ok(afterChips.length === beforeChips - 1, 'yazar Keşfet listesinden silindi',
  `${beforeChips} → ${afterChips.length}`);
ok(!afterChips.some(b => b.dataset.sheetWriter === delName), 'silinen yazar listede yok');
ok(stored('kose-hidden-writers').some(h => h.name === delName), 'silme kaydı localStorage’da');
const hiddenCard = doc.getElementById('hidden-card');
ok(!!hiddenCard && hiddenCard.textContent.includes('Gizlenenler'), '“Gizlenenler” kartı çıktı');
click(hiddenCard.querySelector('button[data-restore-writer]'));
ok(stored('kose-hidden-writers').length === 0, '“Geri getir” silme kaydını kaldırdı');
ok(chipsOf().some(b => b.dataset.sheetWriter === delName), 'yazar Keşfet listesine geri geldi');

console.log('\n[F] KEŞFET: GAZETE SİLME / GERİ GETİRME');
window.expandedPapers = new Set();
window.renderWriters();
const paperCount = () => doc.querySelectorAll('#writers-list > div').length;
const beforePapers = paperCount();
click(paperRow('Posta').querySelector('button[data-sheet-paper]'));
ok(doc.getElementById('sheet-sub').textContent.includes('yazar'), 'gazete alt sayfası yazar sayısını gösteriyor');
click(sheetAction('hide-paper'));
ok(paperCount() === beforePapers - 1, 'gazete (tüm grubu) Keşfet listesinden silindi', `${beforePapers} → ${paperCount()}`);
ok(!paperRow('Posta'), 'silinen gazete listede yok');
ok(stored('kose-hidden-papers').some(p => p.key === 'posta'), 'gazete silme kaydı localStorage’da');
click(doc.querySelector('#hidden-card button[data-restore-paper]'));
ok(paperCount() === beforePapers, 'gazete geri geldi');
ok(window.isHiddenPaper('posta') === false, 'isHiddenPaper temizlendi');

console.log('\n[G] DEPO LİSTESİ (data/passive-writers.json)');
const repoWriter = { name: 'Ahmet Hakan', source: 'Hürriyet', url: 'https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/' };
window.fetch = async (url) => {
  const u = String(url);
  const body = u.includes('passive-writers.json')
    ? { updatedAt: '2026-10-15T10:00:00+00:00', writers: [repoWriter] }
    : u.includes('writers.json') ? writersJson : frozenDaily;
  return { ok: true, json: async () => JSON.parse(JSON.stringify(body)) };
};
const loaded = await window.loadPassiveConfig();
ok(loaded === true, 'depo listesi okundu');
ok(window.isPassiveWriter(repoWriter.name, repoWriter.source) === true, 'depo listesindeki yazar pasif sayılıyor');
ok(window.isPassiveWriter(repoWriter.name, 'Posta') === false, 'aynı ad başka gazetede pasif sayılmıyor');
const repoEntry = window.passiveEntry(repoWriter.name, repoWriter.source);
ok(repoEntry && repoEntry.origin === 'repo', 'kaynağı "repo" olarak işaretli');
window.setTab('discover');
window.expandedPapers = new Set(['hurriyet']);
window.renderWriters();
const repoChip = chipsOf().find(b => b.dataset.sheetWriter === repoWriter.name).closest('span');
ok(repoChip.textContent.includes('pasif'), 'depodaki yazar çipte pasif görünüyor');
click(chipsOf().find(b => b.dataset.sheetWriter === repoWriter.name));
ok(!!sheetAction('repo') && sheetAction('repo').disabled === true, 'depo kaydı için işlem pasif (yalnızca bilgi)');
ok(doc.getElementById('sheet-note').textContent.includes('data/passive-writers.json'),
  'alt sayfa notu depo dosyasını işaret ediyor');
window.closeActionSheet();

console.log('\n[H] AYARLAR: PASİF LİSTESİ JSON ÇIKTISI');
window.setTab('settings');
const meta = doc.getElementById('passive-repo-meta').textContent;
ok(/1 depodan/.test(meta), 'Ayarlar pasif liste özeti doğru', meta);
const area = doc.getElementById('passive-export');
const parsed = JSON.parse(area.value);
ok(parsed.writers.length === 1 && parsed.writers[0].name === repoWriter.name, 'JSON çıktısı depo biçiminde');
ok(parsed.writers[0].source === 'Hürriyet' && parsed.writers[0].url.includes('hurriyet.com.tr'),
  'JSON kayıtta gazete + profil bağlantısı var');
window.setPassiveWriter({ name: 'Yeni Pasif', source: 'Hürriyet' }, true);
const parsed2 = JSON.parse(window.passiveExportJson());
ok(parsed2.writers.some(w => w.name === 'Yeni Pasif') && parsed2.writers.some(w => w.name === repoWriter.name),
  'cihazdaki + depodaki kayıtlar tek dosyada birleşiyor', `${parsed2.writers.length} kayıt`);
click(doc.getElementById('passive-copy-btn'));
await new Promise(r => setTimeout(r, 60));
ok(doc.getElementById('passive-copy-note').textContent.includes('kopyala') ||
  doc.getElementById('passive-copy-note').textContent.includes('data/passive-writers.json'),
  'kopyala düğmesi bilgi notu gösteriyor', doc.getElementById('passive-copy-note').textContent);
const areaJson = JSON.parse(doc.getElementById('passive-export').value);
ok(areaJson.writers.length === parsed2.writers.length
  && areaJson.writers.map(w => w.name).join('|') === parsed2.writers.map(w => w.name).join('|'),
  'metin kutusu güncel JSON’u taşıyor (kopyala düğmesi için)', areaJson.writers.map(w => w.name).join(', '));
window.setPassiveWriter({ name: 'Yeni Pasif', source: 'Hürriyet' }, false);

console.log('\n[I] OKUYUCU: PASİF ROZETİ');
const frozenArt = window.articles.find(a => a.isPassive);
window.openReader(frozenArt.id);
ok(!doc.getElementById('reader-passive-badge').classList.contains('hidden'),
  'donmuş (pasif) yazı okuyucuda rozet gösteriyor');
const normalArt = window.articles.find(a => !a.isPassive && !window.isPassiveWriter(a.author, a.source));
window.openReader(normalArt.id);
ok(doc.getElementById('reader-passive-badge').classList.contains('hidden'), 'normal yazıda rozet gizli');

console.log('');
if (fails.length) {
  console.log(`KALAN ${fails.length} MADDE:`);
  fails.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
console.log('TÜM PASİF YAZAR / SİLME TESTLERİ GEÇTİ');
