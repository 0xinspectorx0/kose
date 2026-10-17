// Yazar adı biçimi, okundu halkası, turuncu yukarı-çık, oynatıcı rengi/gradient
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

// Ayarların çağırdığı yönetici kartı yardımcıları
const uiFns = ['renderAdminCard', 'adminStatusText', 'renderAdminStatus'];
const srcConsts = ['DAILY_FEED_URL','WRITERS_URL','isoDayKey','FEED_RECHECK_MS','STALE_AFTER_HOURS'].map(extractConst);
const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
const readerBlock = block('// --- Okuyucu puntosu: A- / A+ ---', '// --- Seslendirme (Web Speech API');
const audioBlock = block('// --- Seslendirme (Web Speech API', '// --- Canlı Akışı Yenile');
const writersEvents = block('// Keşfet: yazar adına tıklayınca akışta o yazarın yazıları listelenir', '// --- Bottom Tab Router');
// Kalıcılık/yönetici durum bloğu (allArticles, kaydedilenler, yönetici oturumu).
// `let articles` çıkarılır: düzenek akışı window.articles üzerinden izler.
const stateBlock = block('// allArticles: yüklenen TÜM yazılar', '// --- Canlı Günlük Akış').replace('let articles = [];', '');
const readStateBlock = block('// --- Okundu takibi', 'function applyReadState()');
// Favori yazarlar: kalp düğmeleri ve Favoriler sekmesi yardımcıları kaynak HTML'den alınır
const favoritesBlock = block('// --- Favori yazarlar: kalpler localStorage', 'let readerFontSize =');
const shuffleBlock = block('// --- Ana ekran: karıştırma (favori daireler + yazı listesi) ---', '// --- /ANA EKRAN SIRASI ---');
const fns = ['toggleFavoriteFromCard','updateReaderFavoriteIcon','saveFavoriteWriters','removeFavoriteWriter','openFavoriteWriterArticles','toggleFavoriteWriter','findFavoriteWriter','isFavoriteWriter','sameSource','favKeyName','deaccentTr','favoriteArticles','findWriterPhoto','renderFavorites','escapeHtml','normalizeTr','formatAuthorName','initialAvatar','mapLiveArticle','formatSyncTime',
  'renderAuthorAvatars','renderArticles','applyFilters','filterCategory','loadDailyFeed','applyReadState',
  'markArticleRead','isAuthorFullyRead','writersSummary','filterWriters','buildWriterPopularity','writerScore',
  'cleanWriterName','isPersonName','cleanWriters','renderWriters','togglePaper','openWriter','renderWriterNotFound',
  'paintToggle','renderSettings','saveSettings','showAuthorTooltip','hideAuthorTooltip','setTab','openReader',
  'updateReaderBookmarkIcon','updateScrollTopBtn','htmlToSpeechText','chunkSpeechText','pickTtsVoice','ttsVoices',
  'renderVoiceOptions','speakNextChunk','restartCurrentChunk','finishSpeech','showAndPlayAudio','togglePlayPause',
  'resetAudio','updateAudioUI','currentTtsRate','formatTtsRate','applyTtsRate'];

const domIds = { authorsAvatarTrack:'authors-avatar-track', articlesListEl:'articles-list', writersListEl:'writers-list',
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

function boot(preset) {
  const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const doc = window.document;
  window.lucide = { createIcons() {} };
  window.articles = [];
  window.initialArticles = [];
  window.currentFilteredCategory = 'Tümü';
  window.expandedPapers = new Set();
  window.currentTab = 'feed';
  window.readerFontSize = 16;
  window.writersLoaded = true;
  window.loadWriters = () => {};
  for (const [k, id] of Object.entries(domIds)) window[k] = doc.getElementById(id);
  window.mainScrollEl.scrollTo = () => {};
  if (preset) window.localStorage.setItem('kose-read-v2', JSON.stringify(preset));
  window.localStorage.setItem('kose-favorite-writers', FAVORITE_SEED);
  window.eval([stateBlock, ...srcConsts, settingsBlock, readStateBlock, favoritesBlock, shuffleBlock, ...fns.map(extract), ...uiFns.map(extract), readerBlock, audioBlock, writersEvents].join('\n'));
  return { window, doc };
}

// Ana sayfadaki daireler artık yalnızca favori yazarları gösterir: test,
// günlük akıştaki yazarların tamamını boot'tan ÖNCE localStorage'a favori
// olarak yazar (favoriteWriters bu kayıttan okunur).
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
const FAVORITE_SEED = favoriteSeedFromDaily('/home/user/kose/data/daily.json');

const d = JSON.parse(readFileSync('/home/user/kose/data/daily.json', 'utf8'));
const w = JSON.parse(readFileSync('/home/user/kose/data/writers.json', 'utf8'));

console.log('\n[1] YAZAR ADI BİÇİMİ');
let { window, doc } = boot();
const cases = ['ahmet hakan','Ahmet HAKAN','m. serdar kuzuloğlu','İbrahim Kiras','ali ıhsan yılmaz','Dr. Ceyda Şener','Fatih Altaylı','Diken'];
cases.forEach(c => console.log(`  ${JSON.stringify(c).padEnd(24)} -> ${window.formatAuthorName(c)}`));
console.log('  Türkçe harfler: "işıl" ->', window.formatAuthorName('işıl öz'), '| "şükrü" ->', window.formatAuthorName('şükrü erbaş'));

window.writersData = w;
window.fetch = async () => ({ ok: true, json: async () => d });
await window.loadDailyFeed(false);
window.renderAuthorAvatars();
const cards = [...doc.querySelectorAll('#articles-list > *')];
const h3 = cards[0].querySelector('h3').textContent;
console.log('  ilk kart yazarı:', JSON.stringify(h3), '| beklenen:', JSON.stringify(window.formatAuthorName(window.articles[0].author)), '| uyuşuyor:', h3 === window.formatAuthorName(window.articles[0].author));
console.log('  tüm kartlar biçimli mi:', cards.every((c, i) => c.querySelector('h3').textContent === window.formatAuthorName(window.articles[i].author)));
const labels = [...doc.querySelectorAll('#authors-avatar-track span')].map(s => s.textContent);
console.log('  ilk 3 daire etiketi:', labels.slice(0, 3).map(l => JSON.stringify(l)).join(' '), '| hepsi biçimli:', labels.every(l => l === window.formatAuthorName(l)));
window.openReader(window.articles[0].id);
console.log('  okuyucudaki ad:', JSON.stringify(doc.getElementById('reader-author-name').textContent));
window.setTab('discover');
window.togglePaper('karar');
const chip = doc.querySelector('#writers-list button[data-writer]');
console.log('  Keşfet çipi: data-writer', JSON.stringify(chip.dataset.writer), '-> görünen', JSON.stringify(chip.textContent));

console.log('\n[2] OKUNDUYSA GRİ HALKA');
({ window, doc } = boot());
window.writersData = w;
window.fetch = async () => ({ ok: true, json: async () => d });
await window.loadDailyFeed(false);
window.renderAuthorAvatars();
const normName = s => String(s ?? '').toLocaleLowerCase('tr-TR').trim();
// veri aynı ismin farklı yazımlarını taşıyabilir ("Abdulkadir SELVİ"/"ABDULKADİR SELVİ");
// daire araması normalizasyonla eşleşir
const circleOf = author => [...doc.querySelectorAll('#authors-avatar-track > div')].find(el => normName(el.dataset.name) === normName(author));
const ringOf = author => circleOf(author).querySelector('div').getAttribute('class');
const single = window.articles.find(a => window.articles.filter(x => x.author === a.author).length === 1);
const multi = window.articles.map(a => a.author).find((v, i, arr) => arr.indexOf(v) !== i);
console.log('  başlangıçta turuncu:', /from-accent/.test(ringOf(single.author)), '| gri var mı:', [...doc.querySelectorAll('#authors-avatar-track > div')].some(el => ringOf(el.dataset.name).includes('bg-stone-300')));
window.openReader(single.id);
console.log(`  "${single.author}" okundu -> gri halka:`, ringOf(single.author).includes('bg-stone-300'), '| etiket:', circleOf(single.author).querySelector('span').getAttribute('class').includes('text-stone-400'), '| title:', circleOf(single.author).querySelector('div').getAttribute('title'));
const two = window.articles.filter(a => a.author === multi);
window.openReader(two[0].id);
console.log(`  "${multi}" (${two.length} yazı) 1. okundu -> hâlâ turuncu:`, /from-accent/.test(ringOf(multi)));
window.openReader(two[1].id);
console.log(`  2. de okundu -> gri:`, ringOf(multi).includes('bg-stone-300'));
const savedRead = JSON.parse(window.localStorage.getItem('kose-read-v2')); // [[uid, zaman], ...]
console.log('  localStorage:', savedRead.length, 'yazı ->', savedRead.slice(0, 3).map(r => r[0]).join(', '));

console.log('\n[3] OKUNDU BİLGİSİ KALICI MI');
const reborn = boot(savedRead);
reborn.window.writersData = w;
reborn.window.fetch = async () => ({ ok: true, json: async () => d });
await reborn.window.loadDailyFeed(false);
const ring2 = a => [...reborn.doc.querySelectorAll('#authors-avatar-track > div')].find(el => normName(el.dataset.name) === normName(a)).querySelector('div').getAttribute('class');
console.log(`  yeniden açılışta "${single.author}" gri:`, ring2(single.author).includes('bg-stone-300'), `| "${multi}" gri:`, ring2(multi).includes('bg-stone-300'));
console.log('  okunmamış bir yazar turuncu:', /from-accent/.test(ring2(window.articles.find(a => !savedRead.some(r => r[0] === a.uid)).author)));

console.log('\n[4] RENKLER');
const fab = doc.getElementById('scroll-top-btn').getAttribute('class');
console.log('  yukarı çık: bg-accent:', fab.includes('bg-accent'), '| siyah kalktı:', !fab.includes('bg-ink-900'), '| hover:', /hover:bg-accent\/85/.test(fab));
console.log('  mini oynatıcı düğmesi:', doc.getElementById('mini-player-toggle').getAttribute('class').includes('bg-accent'));
console.log('  şerit düğmesi:', doc.getElementById('mini-audio-toggle').getAttribute('class').includes('bg-accent'));
const mini = doc.getElementById('mini-player').getAttribute('class');
console.log('  mini oynatıcı gradient:', mini.includes('bg-gradient-to-r'), '| soldan 0 (şeffaf):', mini.includes('from-white/0'), '| sağ:', /to-\[#FFD3A5\]/.test(mini));
console.log('  ilerleme gradient:', doc.getElementById('mini-player-progress').getAttribute('class').includes('bg-gradient-to-r'), '| şerit ilerlemesi:', doc.getElementById('audio-progress').getAttribute('class').includes('bg-gradient-to-r'));
console.log('  accent tanımı:', html.match(/accent: '(#[0-9A-Fa-f]{6})'/)[1]);
