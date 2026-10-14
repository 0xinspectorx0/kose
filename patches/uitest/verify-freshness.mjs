// verify-freshness.mjs — günlük güncellemenin uygulama tarafı denetimi
//   [1] bugünün verisi geldiyse etiket/saklanan gün doğru, boşuna yeniden çekilmiyor
//   [2] günün verisi geciktiyse (07:00'den sonra) "Bugünün verisi bekleniyor" + amber banner
//       ve autoDailyCheck yeniden deniyor (bayat veri "bugün geldi" sayılıp unutulmuyor)
//   [3] sabahın erken saatlerinde (ilk koşu 06:13 TSİ) dünün verisi panik yaratmıyor
//   [4] üç kaynak yoklanıyor (raw + jsDelivr CDN + yerel kopya) ve en taze olan kazanıyor
// Koşum: node verify-freshness.mjs   (jsdom /tmp/uitest/node_modules altından içe aktarılır)
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

const { window } = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
const doc = window.document;
const RealDate = window.Date;
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Uygulamanın saati testten yönetiliyor: saat diliminden bağımsız, deterministik.
function setClock(y, m, d, hh, mm) {
  const fixed = new RealDate(y, m - 1, d, hh, mm, 0, 0).getTime();
  class FixedDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(fixed); }
    static now() { return fixed; }
  }
  window.Date = FixedDate;
  return { fixed, todayISO: iso(new RealDate(fixed)), yesterdayISO: iso(new RealDate(fixed - 86400000)) };
}

window.lucide = { createIcons() {} };
window.articles = [];
window.initialArticles = [];
window.appSettings = { samples: true, autoRefresh: true };
window.renderAuthorAvatars = () => {};   // bu testin konusu değil
window.applyFilters = () => {};
window.syncTimeEl = doc.getElementById('sync-time');
window.articlesListEl = doc.getElementById('articles-list');

const srcConsts = ['DAILY_FEED_URL', 'WRITERS_URL', 'isoDayKey'].map(extractConst);
window.eval([...srcConsts,
  extract('mapLiveArticle'), extract('formatSyncTime'),
  extract('loadDailyFeed'), extract('autoDailyCheck')].join('\n'));

const payload = (date, fetchedAt, n = 12) => ({
  fetchedAt, date, count: n, papers: 4, writers: 900,
  articles: Array.from({ length: n }, (_, i) => ({
    id: `t-${i}`, author: 'Deneme Yazar', source: 'Deneme Gazetesi', title: `Yazı ${i} ${date}`,
    url: `https://example.com/${i}`, date: 'Bugün 08:00', category: 'Gündem', readTime: '2 dk',
    snippet: 'özet', fullContent: '<p>metin</p>', photo: '', avatar: '', isLive: true,
  })),
});

let requests = [];
let responder = () => null;
window.fetch = async (url) => {
  const clean = String(url).split('?')[0];
  requests.push(clean);
  const body = responder(clean);
  return body ? { ok: true, json: async () => body } : { ok: false };
};

let fails = 0;
const check = (label, cond, detail = '') => {
  console.log(`  ${cond ? 'GEÇTİ' : 'KALDI'}  ${label}${detail ? ' — ' + detail : ''}`);
  if (!cond) fails++;
};
const label = () => doc.getElementById('sync-label').textContent.replace(/\s+/g, ' ').trim();
const banner = () => doc.getElementById('sync-banner').className;
const stored = () => window.localStorage.getItem('kose-feed-date');

console.log('\n[1] BUGÜNÜN VERİSİ GELDİ');
let c = setClock(2026, 10, 14, 9, 30);
responder = () => payload(c.todayISO, new RealDate(c.fixed - 45 * 60000).toISOString());
requests = [];
await window.loadDailyFeed(false);
check('etiket normal senkronizasyon', label().startsWith('Gazetelerden senkronize edildi'), label().slice(0, 60));
check('banner yeşil (bayat değil)', banner().includes('bg-emerald-50'));
check('saklanan gün = verinin günü (bugün)', stored() === c.todayISO, stored());
check('akış yüklendi', window.articles.length === 12, `${window.articles.length} yazı`);
const before = requests.length;
requests = [];
window.autoDailyCheck();
await new Promise(r => setTimeout(r, 30));
check('veri bugününse boşuna yeniden çekilmiyor', requests.length === 0, `${requests.length} istek (önceki ${before})`);

console.log('\n[2] GÜNÜN VERİSİ GECİKTİ (09:30, son veri dün 20:08)');
c = setClock(2026, 10, 14, 9, 30);
responder = () => payload(c.yesterdayISO, new RealDate(c.fixed - 13 * 3600000).toISOString());
requests = [];
await window.loadDailyFeed(false);
check('etiket "Bugünün verisi bekleniyor"', label().startsWith('Bugünün verisi bekleniyor'), label().slice(0, 70));
check('banner amber (gecikme görünür)', banner().includes('bg-amber-50'));
check('saklanan gün = dünün verisi (bugün değil)', stored() === c.yesterdayISO, stored());
requests = [];
window.autoDailyCheck();
await new Promise(r => setTimeout(r, 30));
check('autoDailyCheck günün verisi gelene kadar yeniden deniyor', requests.length > 0, `${requests.length} istek`);

console.log('\n[2b] GECİKME DEVAM EDERSE: yeni veri gelince etiket düzeliyor');
responder = () => payload(c.todayISO, new RealDate(c.fixed - 5 * 60000).toISOString());
await window.autoDailyCheck();
await new Promise(r => setTimeout(r, 60));
check('günün verisi gelince saklanan gün bugün oluyor', stored() === c.todayISO, stored());
check('etiket normale dönüyor', label().startsWith('Gazetelerden senkronize edildi'), label().slice(0, 60));
check('banner yeşile dönüyor', banner().includes('bg-emerald-50'));

console.log('\n[3] SABAHIN ERKEN SAATİ (05:00 — ilk koşu 06:13 TSİ)');
c = setClock(2026, 10, 14, 5, 0);
responder = () => payload(c.yesterdayISO, new RealDate(c.fixed - 8 * 3600000).toISOString());
await window.loadDailyFeed(false);
check('erken saatte dünün verisi "gecikti" sayılmıyor', !label().startsWith('Bugünün verisi bekleniyor'), label().slice(0, 60));
check('banner amber değil', !banner().includes('bg-amber-50'));
check('yine de bugünün verisi bekleniyor olarak saklanmıyor', stored() === c.yesterdayISO, stored());

console.log('\n[4] ÇOK KAYNAKLI YOKLAMA (raw + jsDelivr + yerel)');
c = setClock(2026, 10, 14, 12, 0);
const rawP = payload(c.todayISO, new RealDate(c.fixed - 5 * 3600000).toISOString(), 10);
const cdnP = payload(c.todayISO, new RealDate(c.fixed - 30 * 60000).toISOString(), 14);
responder = (url) => {
  if (url.includes('raw.githubusercontent.com')) return rawP;
  if (url.includes('cdn.jsdelivr.net')) return cdnP;
  if (url.includes('data/daily.json')) return rawP;
  return null;
};
requests = [];
await window.loadDailyFeed(false);
check('raw.githubusercontent yoklanıyor', requests.some(u => u.includes('raw.githubusercontent.com')));
check('jsDelivr CDN yedeği yoklanıyor', requests.some(u => u.includes('cdn.jsdelivr.net')));
check('yerel kopya yoklanıyor', requests.some(u => u.endsWith('data/daily.json')));
check('en taze kaynak kazanıyor (CDN 30 dk önce)', window.articles.length === 14, `${window.articles.length} yazı`);

console.log('\n[5] OTOMATİK YENİLEME KAPALIYKEN');
window.appSettings.autoRefresh = false;
requests = [];
window.autoDailyCheck();
await new Promise(r => setTimeout(r, 30));
check('ayar kapalıyken kendiliğinden çekmiyor', requests.length === 0, `${requests.length} istek`);
window.appSettings.autoRefresh = true;

console.log();
if (fails) { console.log(`${fails} MADDE KALDI`); process.exit(1); }
console.log('TÜM TAZELİK TESTLERİ GEÇTİ');
