// Seslendirme: Web Speech API yolu + hız denetimi (mock speechSynthesis ile gerçek kod)
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
const shuffleBlock = block('// --- Ana ekran: favori yazar dairelerinin sırası ---', '// --- /ANA EKRAN SIRASI ---');

const srcConsts = ['DAILY_FEED_URL','WRITERS_URL','isoDayKey','FEED_RECHECK_MS','STALE_AFTER_HOURS'].map(extractConst);
const settingsBlock = block('const SETTINGS_KEY', "let currentFilteredCategory = 'Tümü';");
const audioBlock = block('// --- Seslendirme (Web Speech API', '// --- Canlı Akışı Yenile');
const readerBlock = block('// --- Okuyucu puntosu: A- / A+ ---', '// --- Seslendirme (Web Speech API');
const closeBlock = block("closeReaderBtn.addEventListener('click', () => {", '// --- Reading Progress Bar Indicator ---');
const fns = ['toggleFavoriteFromCard','updateReaderFavoriteIcon','saveFavoriteWriters','removeFavoriteWriter','openFavoriteWriterArticles','toggleFavoriteWriter','findFavoriteWriter','isFavoriteWriter','sameSource','favKeyName','deaccentTr','favoriteArticles','findWriterPhoto','renderFavorites','escapeHtml','htmlToSpeechText','chunkSpeechText','pickTtsVoice','speakNextChunk','restartCurrentChunk',
  'finishSpeech','showAndPlayAudio','togglePlayPause','resetAudio','updateAudioUI','currentTtsRate','formatTtsRate','applyTtsRate',
  'saveSettings','paintToggle','renderSettings','setTab','applyFilters','renderArticles','renderWriters','writersSummary','filterWriters','cleanWriters','cleanWriterName','isPersonName','buildWriterPopularity','writerScore','normalizeTr','formatAuthorName','markArticleRead','applyReadState','isAuthorFullyRead','renderAuthorAvatars','initialAvatar','togglePaper','openReader','updateReaderBookmarkIcon','updateScrollTopBtn'];

const domIds = { authorsAvatarTrack:'authors-avatar-track', audioStrip:'audio-player-strip', miniAudioToggle:'mini-audio-toggle', listenArticleBtn:'listen-article-btn',
  closeReaderBtn:'close-reader-btn', externalLinkBtn:'external-link-btn', readerScrollable:'reader-scrollable',
  readerProgressBar:'reader-progress', articleReader:'article-reader', mainScrollEl:'main-scroll',
  scrollTopBtn:'scroll-top-btn', fontDecBtn:'font-dec-btn', fontIncBtn:'font-inc-btn',
  readerBookmarkBtn:'reader-bookmark-btn', readerFavoriteBtn:'reader-favorite-btn',
  favoritesViewEl:'favorites-view', favoritesListEl:'favorites-list',
  favoritesMetaEl:'favorites-meta', favoritesEmptyEl:'favorites-empty', authorTooltipEl:'author-tooltip', miniPlayerEl:'mini-player',
  feedAuthorsSection:'feed-authors-section', feedCategoriesSection:'feed-categories-section', syncBannerEl:'sync-banner',
  articlesListEl:'articles-list', writersViewEl:'writers-view', settingsViewEl:'settings-view',
  writersListEl:'writers-list', writersMetaEl:'writers-meta', writersLoadingEl:'writers-loading',
  writersEmptyEl:'writers-empty', writersSearchInput:'writers-search', searchInput:'search-input' };

function boot(withTts, presetSettings) {
  const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const doc = window.document;
  window.lucide = { createIcons() {} };
  window.articles = [];
  window.currentFilteredCategory = 'Tümü';
  window.readerFontSize = 16;
  for (const [k, id] of Object.entries(domIds)) window[k] = doc.getElementById(id);
  window.mainScrollEl.scrollTo = () => {};
  window.writersLoaded = true;
  window.loadWriters = () => {};
  window.writersData = null;
  window.expandedPapers = new Set();
  window.currentTab = 'feed';
  if (presetSettings) window.localStorage.setItem('kose-settings', JSON.stringify(presetSettings));

  const spoken = [];
  const calls = { cancel: 0, pause: 0, resume: 0 };
  if (withTts) {
    window.SpeechSynthesisUtterance = class {
      constructor(text) { this.text = text; this.lang = ''; this.voice = null; this.rate = 1; this.pitch = 1; this.onend = null; this.onerror = null; }
    };
    window.__tts = {
      voices: [
        { name: 'Alex', lang: 'en-US' },
        { name: 'Google Türkçe', lang: 'tr-TR' },
        { name: 'Microsoft Emel Online (Natural) - Turkish (Turkey)', lang: 'tr-TR' },
        { name: 'Yelda Premium', lang: 'tr-TR' },
      ],
      listeners: {},
    };
    window.speechSynthesis = {
      getVoices: () => window.__tts.voices,
      speak: u => spoken.push(u),
      cancel: () => { calls.cancel++; },
      pause: () => { calls.pause++; },
      resume: () => { calls.resume++; },
      addEventListener: (t, f) => { (window.__tts.listeners[t] ||= []).push(f); },
    };
  }
  window.eval([...srcConsts, settingsBlock, readStateBlock, favoritesBlock, shuffleBlock, ...fns.map(extract), audioBlock, readerBlock, closeBlock].join('\n'));
  return { window, doc, spoken, calls };
}

const d = JSON.parse(readFileSync('/home/user/kose/data/daily.json', 'utf8'));
const art = d.articles.find(a => (a.fullContent || '').length > 1200);
const click = (doc, window, id) => doc.getElementById(id).dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const label = doc => doc.getElementById('tts-rate-label').textContent;

console.log('\n[1] SESLENDİRMEYİ BAŞLAT');
let { window, doc, spoken, calls } = boot(true);
window.articles = [art];
window.openReader(art.id);
console.log('  okuyucu açılınca şerit görünür:', !doc.getElementById('audio-player-strip').classList.contains('hidden'), '| durum:', doc.getElementById('audio-status').textContent);
click(doc, window, 'listen-article-btn');
console.log('  durum:', doc.getElementById('audio-status').textContent, '| ses:', doc.getElementById('audio-voice').textContent);
console.log('  utterance:', spoken.length, '| lang:', spoken[0].lang, '| hız:', spoken[0].rate);
console.log('  ilk parça:', JSON.stringify(spoken[0].text.slice(0, 52)));

console.log('\n[2] BÖLÜMLER BOYUNCA İLERLİYOR');
const widths = [];
let guard = 0;
while (spoken.length && guard++ < 200) {
  const u = spoken.shift();
  widths.push(doc.getElementById('audio-progress').style.width);
  u.onend();
}
console.log('  okunan bölüm:', guard, '| ilerleme:', widths.slice(0, 4).join(' -> '), '...');
console.log('  bitince durum:', doc.getElementById('audio-status').textContent, '| şerit açık kaldı:', !doc.getElementById('audio-player-strip').classList.contains('hidden'));

console.log('\n[3] HIZ: HIZLANDIR / YAVAŞLAT');
({ window, doc, spoken, calls } = boot(true));
window.articles = [art];
window.openReader(art.id);
console.log('  başlangıç etiketi:', label(doc), '| currentTtsRate:', window.currentTtsRate());
click(doc, window, 'tts-faster-btn'); click(doc, window, 'tts-faster-btn');
console.log('  2×hızlandır ->', label(doc), '| ayar:', JSON.parse(window.localStorage.getItem('kose-settings')).ttsRate);
click(doc, window, 'listen-article-btn');
console.log('  konuşma başladı, utterance hızı:', spoken[0].rate, '| durum:', doc.getElementById('audio-status').textContent);
const beforeCancel = calls.cancel;
click(doc, window, 'tts-faster-btn');
console.log('  konuşurken hızlandır -> cancel:', calls.cancel - beforeCancel, '| yeni hız:', spoken[spoken.length - 1].rate, '| aynı bölüm mü:', doc.getElementById('audio-status').textContent);
for (let i = 0; i < 6; i++) click(doc, window, 'tts-slower-btn');
console.log('  6×yavaşlat ->', label(doc), '(alt sınır) | düğme pasif:', doc.getElementById('tts-slower-btn').disabled);
for (let i = 0; i < 12; i++) click(doc, window, 'tts-faster-btn');
console.log('  12×hızlandır ->', label(doc), '(üst sınır) | düğme pasif:', doc.getElementById('tts-faster-btn').disabled);
console.log('  son utterance hızı:', spoken[spoken.length - 1].rate, '| kayıtlı ayar:', window.localStorage.getItem('kose-settings'));

console.log('\n[4] HIZ KALICI MI (yeni açılış)');
const saved = JSON.parse(window.localStorage.getItem('kose-settings'));
const reborn = boot(true, saved);
reborn.window.articles = [art];
reborn.window.openReader(art.id);
console.log('  kayıttan gelen hız:', reborn.window.currentTtsRate(), '| etiket:', label(reborn.doc));
click(reborn.doc, reborn.window, 'listen-article-btn');
console.log('  utterance hızı:', reborn.spoken[0].rate);
const fresh = boot(true);
console.log('  kaydı olmayan kullanıcı ->', fresh.window.currentTtsRate(), '| etiket:', label(fresh.doc));

console.log('\n[5] OKUYUCU BAŞLIĞINDAKİ OYNAT/DURAKLAT');
({ window, doc, spoken, calls } = boot(true));
window.articles = [art];
window.openReader(art.id);
const headerBtn = () => doc.getElementById('listen-article-btn').querySelector('i').getAttribute('data-lucide');
console.log('  başlangıç simgesi:', headerBtn(), '| başlık:', doc.getElementById('listen-article-btn').title);
click(doc, window, 'listen-article-btn');
console.log('  tıklayınca:', headerBtn(), '| durum:', doc.getElementById('audio-status').textContent);
click(doc, window, 'listen-article-btn');
console.log('  tekrar tıklayınca:', headerBtn(), '| durum:', doc.getElementById('audio-status').textContent);
click(doc, window, 'listen-article-btn');

console.log('\n[6] OKUYUCUYU KAPATINCA MİNİ OYNATICI');
const cancelBefore = calls.cancel;
click(doc, window, 'close-reader-btn');
console.log('  okuyucu kapalı:', doc.getElementById('article-reader').classList.contains('translate-y-full'));
console.log('  mini oynatıcı görünür:', !doc.getElementById('mini-player').classList.contains('hidden'));
console.log('  yazar:', doc.getElementById('mini-player-author').textContent, '| yazı:', doc.getElementById('mini-player-title').textContent.slice(0, 40));
console.log('  bölüm sayacı:', doc.getElementById('mini-player-status').textContent, '| ilerleme:', doc.getElementById('mini-player-progress').style.width);
console.log('  ses kesilmedi (cancel artmadı):', calls.cancel === cancelBefore, '| konuşuyor:', doc.getElementById('mini-player-icon').getAttribute('data-lucide'));
click(doc, window, 'mini-player-toggle');
console.log('  mini oynatıcıdan duraklat ->', calls.pause, '| simge:', doc.getElementById('mini-player-icon').getAttribute('data-lucide'));
click(doc, window, 'mini-player-toggle');
console.log('  mini oynatıcıdan sürdür ->', calls.resume, '| simge:', doc.getElementById('mini-player-icon').getAttribute('data-lucide'));

console.log('\n[7] YUKARI ÇIK DÜĞMESİ ÇAKIŞMIYOR');
window.mainScrollEl.scrollTop = 900;
window.updateScrollTopBtn();
console.log('  mini oynatıcı varken FAB gizli:', doc.getElementById('scroll-top-btn').classList.contains('hidden'));

console.log('\n[8] MİNİ OYNATICIDAN YAZIYA DÖN / KAPAT');
click(doc, window, 'mini-player-open');
console.log('  yazıya dönünce okuyucu açık:', !doc.getElementById('article-reader').classList.contains('translate-y-full'), '| mini gizli:', doc.getElementById('mini-player').classList.contains('hidden'));
click(doc, window, 'listen-article-btn');
click(doc, window, 'close-reader-btn');
const cancelBefore2 = calls.cancel;
click(doc, window, 'mini-player-close');
console.log('  kapat düğmesi -> cancel:', calls.cancel - cancelBefore2, '| mini gizli:', doc.getElementById('mini-player').classList.contains('hidden'), '| şerit gizli:', doc.getElementById('audio-player-strip').classList.contains('hidden'));

console.log('\n[9] SEKME DEĞİŞİNCE MİNİ OYNATICI DURUYOR');
click(doc, window, 'listen-article-btn');
click(doc, window, 'close-reader-btn');
window.setTab('discover');
console.log('  Keşfet\'te mini oynatıcı görünür:', !doc.getElementById('mini-player').classList.contains('hidden'));
window.setTab('feed');
console.log('  Akış\'ta mini oynatıcı görünür:', !doc.getElementById('mini-player').classList.contains('hidden'));
click(doc, window, 'mini-player-close');

console.log('\n[10] DESTEKLEMEYEN TARAYICI');
const legacy = boot(false);
legacy.window.articles = [art];
legacy.window.openReader(art.id);
click(legacy.doc, legacy.window, 'listen-article-btn');
console.log('  durum:', legacy.doc.getElementById('audio-status').textContent, '| açıklama:', legacy.doc.getElementById('audio-voice').textContent);
console.log('  hız düğmeleri duruyor:', !!legacy.doc.getElementById('tts-slower-btn'), '| etiket:', label(legacy.doc));

console.log('\n[11] SES SEÇİMİ');
({ window, doc, spoken, calls } = boot(true));
window.articles = [art];
window.openReader(art.id);
click(doc, window, 'listen-article-btn');
console.log('  otomatik seçim:', spoken[0].voice.name, '| şerit:', doc.getElementById('audio-voice').textContent);
const sel = doc.getElementById('set-tts-voice');
window.renderSettings();
const opts = [...sel.options].map(o => o.value);
console.log('  listedeki seçenek:', opts.length, '| gruplar:', [...sel.querySelectorAll('optgroup')].map(g => g.label).join(','));
console.log('  Türkçe sesler listede:', opts.filter(v => v.includes('Türkçe') || v.includes('Turkish') || v.includes('Yelda')).length, '| otomatik satırı:', opts[0]);
const natural = 'Microsoft Emel Online (Natural) - Turkish (Turkey)';
const cancelBefore3 = calls.cancel;
const spokenBefore = spoken.length;
sel.value = natural;
sel.dispatchEvent(new window.Event('change', { bubbles: true }));
console.log('  seçim kaydı:', JSON.parse(window.localStorage.getItem('kose-settings')).ttsVoice.slice(0, 30) + '…');
console.log('  konuşurken ses değişti -> cancel:', calls.cancel - cancelBefore3, '| yeniden okunan bölüm:', spoken.length - spokenBefore, '| yeni ses:', spoken[spoken.length - 1].voice.name, '| bölüm:', doc.getElementById('audio-status').textContent);
console.log('  şerit etiketi:', doc.getElementById('audio-voice').textContent.slice(0, 50));

console.log('\n[12] SES SEÇİMİ KALICI MI');
const savedVoice = JSON.parse(window.localStorage.getItem('kose-settings'));
const again = boot(true, savedVoice);
again.window.articles = [art];
again.window.openReader(art.id);
click(again.doc, again.window, 'listen-article-btn');
console.log('  yeniden açılışta kullanılan ses:', again.spoken[0].voice.name);
again.window.renderSettings();
console.log('  listede seçili görünen:', again.doc.getElementById('set-tts-voice').value.slice(0, 30) + '…');

console.log('\n[13] SESLER SONRADAN YÜKLENİRSE (voiceschanged)');
const late = boot(true);
late.window.__tts.voices = [];
late.window.pickTtsVoice();
late.window.renderVoiceOptions();
console.log('  ses yokken etiket:', late.doc.getElementById('audio-voice').textContent, '| seçenek:', late.doc.getElementById('set-tts-voice').options.length);
late.window.__tts.voices = [{ name: 'Filiz (Premium)', lang: 'tr-TR' }];
(late.window.__tts.listeners.voiceschanged || []).forEach(f => f());
console.log('  yüklendikten sonra etiket:', late.doc.getElementById('audio-voice').textContent, '| seçenek:', late.doc.getElementById('set-tts-voice').options.length);
console.log('  not satırı:', late.doc.getElementById('set-tts-voice-note').textContent.slice(0, 60) + '…');
