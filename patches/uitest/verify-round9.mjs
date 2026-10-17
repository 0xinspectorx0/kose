import { readFileSync } from 'node:fs';
import { JSDOM } from '/tmp/uitest/node_modules/jsdom/lib/api.js';

const html = readFileSync('/home/user/kose/index.html', 'utf8');

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
// Kalıcılık/yönetici durum bloğu (allArticles, kaydedilenler, gizlenenler, yönetici oturumu).
// `let articles` çıkarılır: düzenek akışı window.articles üzerinden izler.
const stateBlock = block('// allArticles: yüklenen TÜM yazılar', '// --- Canlı Günlük Akış').replace('let articles = [];', '');
const readStateBlock = block('// --- Okundu takibi', 'function applyReadState()');
// Favori yazarlar: kalp düğmeleri ve Favoriler sekmesi yardımcıları kaynak HTML'den alınır
const favoritesBlock = block('// --- Favori yazarlar: kalpler localStorage', 'let readerFontSize =');

const fns = ['toggleFavoriteFromCard','updateReaderFavoriteIcon','saveFavoriteWriters','removeFavoriteWriter','openFavoriteWriterArticles','toggleFavoriteWriter','findFavoriteWriter','isFavoriteWriter','sameSource','favKeyName','deaccentTr','favoriteArticles','findWriterPhoto','renderFavorites','escapeHtml','normalizeTr','formatAuthorName','initialAvatar','mapLiveArticle','formatSyncTime','renderAuthorAvatars',
  'applyReadState','markArticleRead','isAuthorFullyRead','quickOpenByAuthor',
  'renderArticles','applyFilters','filterCategory','loadDailyFeed','writersSummary','filterWriters',
  'buildWriterPopularity','writerScore','cleanWriterName','isPersonName','cleanWriters','renderWriters',
  'togglePaper','openWriter','renderWriterNotFound','paintToggle','renderSettings','saveSettings',
  'showAuthorTooltip','hideAuthorTooltip','setTab'];

const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
const doc = window.document;
// Okuyucu/ayarların çağırdığı yeni arayüz yardımcıları (⋮ menüsü, Gizlenenler, Yönetici kartı, bildirim)
const uiFns = ['closeReaderMenu', 'renderHiddenCard', 'hiddenListHtml', 'renderAdminCard', 'adminStatusText', 'renderAdminStatus', 'showToast', 'hideToast'];
const srcConsts = ['DAILY_FEED_URL','WRITERS_URL','isoDayKey','FEED_RECHECK_MS','STALE_AFTER_HOURS'].map(extractConst);
const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
const writersEvents = block('// Keşfet: yazar adına tıklayınca akışta o yazarın yazıları listelenir', '// --- Bottom Tab Router');

window.lucide = { createIcons() {} };
window.articles = [];
window.initialArticles = [];
window.currentFilteredCategory = 'Tümü';
window.expandedPapers = new Set();
window.currentTab = 'feed';
window.readerFontSize = 16;
window.writersLoaded = true;
window.loadWriters = () => {};
const ids = { authorsAvatarTrack:'authors-avatar-track', articlesListEl:'articles-list', writersListEl:'writers-list',
  writersMetaEl:'writers-meta', writersLoadingEl:'writers-loading', writersEmptyEl:'writers-empty',
  writersSearchInput:'writers-search', searchInput:'search-input', syncTimeEl:'sync-time',
  feedAuthorsSection:'feed-authors-section', feedCategoriesSection:'feed-categories-section', syncBannerEl:'sync-banner',
  writersViewEl:'writers-view', settingsViewEl:'settings-view', articleReader:'article-reader',
  mainScrollEl:'main-scroll', scrollTopBtn:'scroll-top-btn', authorTooltipEl:'author-tooltip',
  favoritesViewEl:'favorites-view', favoritesListEl:'favorites-list',
  favoritesMetaEl:'favorites-meta', favoritesEmptyEl:'favorites-empty' };
window.localStorage.setItem('kose-favorite-writers', favoriteSeedFromDaily('/home/user/kose/data/daily.json'));
for (const [k, id] of Object.entries(ids)) window[k] = doc.getElementById(id);
window.mainScrollEl.scrollTo = () => {};
window.eval([stateBlock, ...srcConsts, settingsBlock, readStateBlock, favoritesBlock, ...fns.map(extract), ...uiFns.map(extract), writersEvents].join('\n'));
// Ana sayfadaki daireler artık yalnızca favori yazarları gösterir: test,
// günlük akıştaki yazarların tamamını eval'den ÖNCE localStorage üzerinden
// favori olarak tohumlar (favoriteWriters bu kayıttan okunur).
function favoriteSeedFromDaily(dailyPath) {
  const dd = JSON.parse(readFileSync(dailyPath, 'utf8'));
  const seen = new Set();
  const favs = [];
  (dd.articles || []).forEach(a => {
    const k = String(a.author || '').toLocaleLowerCase('tr-TR').trim();
    if (!k || seen.has(k)) return;
    seen.add(k);
    favs.push({ name: a.author, source: a.source, photo: '', url: '' });
  });
  return JSON.stringify(favs);
}

const d = JSON.parse(readFileSync('/home/user/kose/data/daily.json', 'utf8'));
const w = JSON.parse(readFileSync('/home/user/kose/data/writers.json', 'utf8'));
window.writersData = w;
window.fetch = async () => ({ ok: true, json: async () => d });
await window.loadDailyFeed(false);

const norm = s => String(s ?? '').toLocaleLowerCase('tr-TR').trim();
const todayBy = {};
d.articles.forEach(a => { (todayBy[norm(a.source)] ||= new Set()).add(norm(a.author)); });

console.log('\n[1] ÇİPLERDE YALNIZCA İSİM');
window.writersSearchInput.value = '';
window.renderWriters();
const paperRow = name => [...doc.querySelectorAll('#writers-list > div')].find(r => r.querySelector('h3').textContent === name);
window.togglePaper('hurriyet');
const chips = [...paperRow('Hürriyet').querySelectorAll('button[data-writer]')];
console.log('  Hürriyet çip sayısı:', chips.length, '| <i> simgesi olan çip:', chips.filter(c => c.querySelector('i')).length);
console.log('  başka öğe taşıyan çip:', chips.filter(c => c.children.length > 0).length);
console.log('  örnek 5 çip:', chips.slice(0, 5).map(c => `"${c.textContent}"`).join(' '));
console.log('  görünen ad biçimli (data-writer ham kalıyor):', chips.every(c => c.textContent === window.formatAuthorName(c.dataset.writer)));
console.log('  target=_blank bağlantı kaldı mı:', paperRow('Hürriyet').querySelectorAll('a[target="_blank"]').length === 0);

console.log('\n[1b] AD TEMİZLİĞİ');
const rawAll = w.papers.flatMap(p => p.writers.map(x => x.name));
const cleanAll = w.papers.flatMap(p => window.cleanWriters(p.writers).map(x => x.name));
console.log('  ham roster adı:', rawAll.length, '| çip:', cleanAll.length, '| elenen:', rawAll.length - cleanAll.length);
console.log('  "Yazı" ile biten:', cleanAll.filter(n => /\d+\s+(Adet\s+)?Yazı$/i.test(n)).length,
  '| rakamla başlayan:', cleanAll.filter(n => /^\d/.test(n)).length,
  '| "|" içeren:', cleanAll.filter(n => n.includes('|')).length);
console.log('  örnek:', window.cleanWriterName('İlke Gürsoy 15 Yazı'), '/', window.cleanWriterName('Adnan Ekinci | Hukuk Ombudsmanı'),
  '| korunan:', window.cleanWriterName('M. Serdar Kuzuloğlu'));

console.log('\n[2] POPÜLER BAŞ YAZARLAR ÖNDE');
for (const [pname, key] of [['Hürriyet','hurriyet'], ['Karar','karar'], ['Posta','posta']]) {
  window.expandedPapers = new Set([key]);
  window.renderWriters();
  const cs = [...paperRow(pname).querySelectorAll('button[data-writer]')].map(c => c.dataset.writer);
  const roster = window.cleanWriters(w.papers.find(p => p.name === pname).writers).map(x => x.name);
  const today = todayBy[norm(pname)] || new Set();
  const todayIdx = roster.map((n, i) => today.has(norm(n)) ? i : -1).filter(i => i >= 0);
  const head = cs.slice(0, todayIdx.length).map(norm);
  console.log(`  ${pname}: ${todayIdx.length}/${roster.length} bugün yazan -> hepsi başta: ${head.every(n => today.has(n))}` +
    ` | kendi aralarında gazete sırası: ${JSON.stringify(head) === JSON.stringify(todayIdx.map(i => norm(roster[i])))}` +
    ` | kalanlar gazete sırasında: ${JSON.stringify(cs.slice(todayIdx.length).map(norm)) === JSON.stringify(roster.filter((n, i) => !todayIdx.includes(i)).map(norm))}`);
}
window.expandedPapers = new Set();
window.renderWriters();
const rows = [...doc.querySelectorAll('#writers-list > div h3')].map(h => h.textContent);
console.log('  gazete sırası alfabetik:', JSON.stringify(rows) === JSON.stringify([...rows].sort((a, b) => a.localeCompare(b, 'tr'))));

console.log('\n[3] YAZARA TIKLAYINCA');
window.togglePaper('hurriyet');
const target = [...paperRow('Hürriyet').querySelectorAll('button[data-writer]')][0];
const tName = target.dataset.writer;
const expected = d.articles.filter(a => norm(a.source) === 'hürriyet' && norm(a.author) === norm(tName));
target.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
console.log('  tıklanan yazar:', tName, '| arama kutusu:', JSON.stringify(window.searchInput.value), '| kategori:', window.currentFilteredCategory);
console.log('  Keşfet gizli:', window.writersViewEl.classList.contains('hidden'), '| akış görünür:', !window.articlesListEl.classList.contains('hidden'));
const cards = [...window.articlesListEl.children];
console.log(`  kart: ${cards.length} (bugünkü ${tName} yazısı: ${expected.length}) | hepsi bu yazara ait:`,
  cards.every(c => c.textContent.toLocaleLowerCase('tr-TR').includes(norm(tName))));

console.log('\n[4] BUGÜN YAZISI OLMAYAN YAZAR');
window.setTab('discover');
window.expandedPapers = new Set([w.papers.find(p => p.name === 'T24').key]);
window.renderWriters();
const t24chip = [...paperRow('T24').querySelectorAll('button[data-writer]')][0];
t24chip.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
console.log('  yazar:', t24chip.dataset.writer);
console.log('  mesaj:', window.articlesListEl.textContent.replace(/\s+/g, ' ').trim().slice(0, 60));
const link = window.articlesListEl.querySelector('a[target="_blank"]');
console.log('  gazete sayfası bağlantısı doğru mu:', link ? link.getAttribute('href') === t24chip.dataset.url : false);
