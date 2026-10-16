// Çekirdek regresyon: akış, alt menü simgeleri, yukarı-çık, A-/A+ punto, Ayarlar
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
const readStateBlock = block('// --- Okundu takibi', 'function applyReadState()');
// Favori yazarlar: kalp düğmeleri ve Favoriler sekmesi yardımcıları kaynak HTML'den alınır
const favoritesBlock = block('// --- Favori yazarlar: kalpler localStorage', 'let readerFontSize =');
const shuffleBlock = block('// --- Ana ekran: karıştırma (favori daireler + yazı listesi) ---', '// --- /ANA EKRAN SIRASI ---');

const fns = ['toggleFavoriteFromCard','updateReaderFavoriteIcon','saveFavoriteWriters','removeFavoriteWriter','openFavoriteWriterArticles','toggleFavoriteWriter','findFavoriteWriter','isFavoriteWriter','sameSource','favKeyName','deaccentTr','favoriteArticles','findWriterPhoto','renderFavorites','escapeHtml','normalizeTr','formatAuthorName','initialAvatar','mapLiveArticle','formatSyncTime','renderAuthorAvatars','applyReadState','isAuthorFullyRead',
  'renderArticles','applyFilters','filterCategory','loadDailyFeed','writersSummary','filterWriters',
  'buildWriterPopularity','writerScore','cleanWriterName','isPersonName','cleanWriters','renderWriters',
  'togglePaper','paintToggle','renderSettings','saveSettings','showAuthorTooltip','hideAuthorTooltip','setTab'];

const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
const doc = window.document;
const srcConsts = ['DAILY_FEED_URL','WRITERS_URL','isoDayKey','FEED_RECHECK_MS','STALE_AFTER_HOURS'].map(extractConst);
const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
const settingsEvents = block('// --- Ayarlar sekmesi olayları ---', '// Initialize View');
const readerBlock = block('// --- Okuyucu puntosu: A- / A+ ---', '// --- Seslendirme (Web Speech API');
const audioBlock = block('// --- Seslendirme (Web Speech API', '// --- Canlı Akışı Yenile');

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
  fontDecBtn:'font-dec-btn', fontIncBtn:'font-inc-btn', miniPlayerEl:'mini-player',
  audioStrip:'audio-player-strip', miniAudioToggle:'mini-audio-toggle', listenArticleBtn:'listen-article-btn',
  closeReaderBtn:'close-reader-btn', externalLinkBtn:'external-link-btn', readerScrollable:'reader-scrollable',
  readerProgressBar:'reader-progress', readerBookmarkBtn:'reader-bookmark-btn', readerFavoriteBtn:'reader-favorite-btn',
  favoritesViewEl:'favorites-view', favoritesListEl:'favorites-list',
  favoritesMetaEl:'favorites-meta', favoritesEmptyEl:'favorites-empty' };
for (const [k, id] of Object.entries(ids)) window[k] = doc.getElementById(id);
window.eval([...srcConsts, settingsBlock, readStateBlock, favoritesBlock, shuffleBlock, ...fns.map(extract), settingsEvents, readerBlock, audioBlock].join('\n'));

const d = JSON.parse(readFileSync('/home/user/kose/data/daily.json', 'utf8'));
window.writersData = JSON.parse(readFileSync('/home/user/kose/data/writers.json', 'utf8'));
window.fetch = async () => ({ ok: true, json: async () => d });

console.log('\n[A] AKIŞ');
await window.loadDailyFeed(false);
console.log('  makale:', window.articles.length, '(daily.json:', d.count + ') | kart:', doc.querySelectorAll('#articles-list > *').length);
console.log('  yazar dairesi:', doc.querySelectorAll('#authors-avatar-track > *').length);
console.log('  isLive=false (örnek yazı):', window.articles.filter(a => !a.isLive).length, '| Zülfü Livaneli var mı:', window.articles.some(a => a.author.includes('Zülfü Livaneli')));
console.log('  banner:', window.syncBannerEl.textContent.replace(/\s+/g, ' ').trim().slice(0, 80));

console.log('\n[B] ALT MENÜ SİMGELERİ');
const navIcons = [...doc.querySelectorAll('.nav-btn i')].map(i => i.getAttribute('class'));
console.log('  sınıflar:', navIcons.join(' | '), '| hepsi aynı:', navIcons.every(c => c === navIcons[0]), '| nav-icon-strong yok:', !html.includes('nav-icon-strong'));

console.log('\n[C] YUKARI ÇIK');
window.updateScrollTopBtn();
const hiddenAtTop = window.scrollTopBtn.classList.contains('hidden');
window.mainScrollEl.scrollTop = 800;
window.mainScrollEl.dispatchEvent(new window.Event('scroll'));
const shown = !window.scrollTopBtn.classList.contains('hidden');
const calls = [];
window.mainScrollEl.scrollTo = o => calls.push(o);
window.scrollTopBtn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
window.articleReader.classList.remove('translate-y-full');
window.updateScrollTopBtn();
const hiddenInReader = window.scrollTopBtn.classList.contains('hidden');
window.articleReader.classList.add('translate-y-full');
window.updateScrollTopBtn();
console.log('  en üstte gizli:', hiddenAtTop, '| 800px sonra görünür:', shown, '| tıklayınca:', JSON.stringify(calls[0]), '| okuyucuda gizli:', hiddenInReader);

console.log('\n[D] A- / A+');
const body = doc.getElementById('reader-body');
const click = id => doc.getElementById(id).dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
click('font-inc-btn'); click('font-inc-btn');
const after2 = body.style.fontSize;
for (let i = 0; i < 10; i++) click('font-dec-btn');
const afterDec = body.style.fontSize;
for (let i = 0; i < 30; i++) click('font-inc-btn');
console.log('  2×A+:', after2, '| 10×A-:', afterDec, '(alt sınır) | 30×A+:', body.style.fontSize, '(üst sınır)');
console.log('  kalıcı ayar:', window.localStorage.getItem('kose-settings'));

console.log('\n[E] AYARLAR SEKMESİ');
window.setTab('settings');
console.log('  görünür:', !window.settingsViewEl.classList.contains('hidden'), '| akış gizli:', window.articlesListEl.classList.contains('hidden'));
console.log('  punto düğmeleri:', [...doc.querySelectorAll('#settings-font-group button')].map(b => b.dataset.font + (b.className.includes('bg-ink-900') ? '(aktif)' : '')).join(' '));
console.log('  veri satırı:', doc.getElementById('settings-data-info').textContent);
doc.querySelector('#settings-font-group button[data-font="19"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
console.log('  19\'a tıklayınca:', window.readerFontSize, body.style.fontSize);
doc.getElementById('set-tooltip').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
console.log('  balon anahtarı:', doc.getElementById('set-tooltip').getAttribute('aria-checked'), '| kayıtlı:', window.localStorage.getItem('kose-settings'));
doc.getElementById('settings-reset-btn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
console.log('  varsayılana dön:', window.localStorage.getItem('kose-settings'));

console.log('\n[F] KEŞFET');
window.setTab('discover');
const rows = [...doc.querySelectorAll('#writers-list > div')];
// Gazete satırı artık [aç/kapa düğmesi + ⋯ düğmesi] şeridi ve çip panelinden oluşur
console.log('  satır:', rows.length, '| hepsi kapalı:', rows.every(r => r.querySelector('[data-chips-panel]').classList.contains('hidden')), '| meta:', window.writersMetaEl.textContent);
const names = rows.map(r => r.querySelector('h3').textContent);
console.log('  alfabetik:', JSON.stringify(names) === JSON.stringify([...names].sort((a, b) => a.localeCompare(b, 'tr'))));
