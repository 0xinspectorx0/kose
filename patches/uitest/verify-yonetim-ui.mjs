// Uçtan uca: gerçek index.html jsdom'da açılır; yerel sunucu statik dosyaları,
// GERÇEK /api/yonetim fonksiyonunu ve Upstash taklidini sunar. Ziyaretçi düzeni,
// pasif yazar / Keşfet'ten silme (#14) listelerinin eşitlenmesi, iki yönetici cihazı
// arası eşitleme, kaynak kuralları, çevrimdışı kuyruk ve oturum kapatma denetlenir.
// Çalıştırma (jsdom /tmp/uitest altında kurulu olmalı):
//   cd /tmp/uitest && node /home/user/kose/patches/uitest/verify-yonetim-ui.mjs
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { JSDOM, VirtualConsole } from '/tmp/uitest/node_modules/jsdom/lib/api.js';

const require = createRequire(import.meta.url);
const { baslat } = require('./yonetim-yerel-sunucu.cjs');
const KOK = new URL('../../', import.meta.url).pathname;

let hata = 0;
let gecen = 0;
function check(ad, kosul, ayrinti = '') {
  if (kosul) { gecen++; console.log(`  ✓ ${ad}`); }
  else { hata++; console.log(`  ✗ ${ad}${ayrinti ? ` — ${ayrinti}` : ''}`); }
}
const bekle = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, ms = 4000, ad = 'koşul') {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (await fn()) return true; } catch (e) { /* tekrar dene */ }
    await bekle(25);
  }
  console.log(`    (zaman aşımı: ${ad})`);
  return false;
}

const SIFRE = 'deneme-sifre-42';
const s = await baslat({ sifre: SIFRE });
const daily = JSON.parse(readFileSync(`${KOK}data/daily.json`, 'utf8'));

// CDN betikleri (Tailwind, Lucide) sandbox'ta yok: kaldırılır, yerlerine boş taklit konur
const html = readFileSync(`${KOK}index.html`, 'utf8')
  .replace(/<script src="https:\/\/cdn\.tailwindcss\.com"><\/script>/, '')
  .replace(/<script src="https:\/\/unpkg\.com\/lucide@latest"><\/script>/, '')
  .replace(/<link[^>]+fonts\.(googleapis|gstatic)[^>]*>/g, '');

function cihaz(ad, depo = {}) {
  const istekler = [];
  const hatalar = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => hatalar.push(String(e && (e.stack || e.message) || e)));
  vc.on('error', (...a) => hatalar.push(a.join(' ')));
  vc.on('warn', () => {});
  const dom = new JSDOM(html, {
    url: `${s.taban}/`,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(w) {
      w.lucide = { createIcons() {} };
      w.tailwind = {};
      w.confirm = () => true;
      w.HTMLElement.prototype.scrollTo = function () {};
      w.scrollTo = () => {};
      Object.entries(depo).forEach(([k, v]) => w.localStorage.setItem(k, v));
      w.fetch = (girdi, init = {}) => {
        const url = new URL(String(girdi), w.location.href);
        istekler.push(`${init.method || 'GET'} ${url.pathname}${url.search}`);
        // GitHub raw / jsDelivr sandbox'ta yok: anında "çevrimdışı" (uygulama yerel kopyaya düşer)
        if (url.origin !== new URL(s.taban).origin) return Promise.reject(new TypeError(`çevrimdışı: ${url.host}`));
        return fetch(url.href, { method: init.method || 'GET', headers: init.headers, body: init.body });
      };
    },
  });
  const w = dom.window;
  const d = w.document;
  return {
    ad, dom, w, d, istekler, hatalar,
    depo() { const o = {}; for (let i = 0; i < w.localStorage.length; i++) { const k = w.localStorage.key(i); o[k] = w.localStorage.getItem(k); } return o; },
    ev: kod => w.eval(kod),
    kartlar: () => [...d.querySelectorAll('#articles-list article')],
    kartId: el => Number((el.getAttribute('onclick') || '').match(/openReader\((\d+)\)/)?.[1]),
    sekme: t => d.querySelector(`.nav-btn[data-tab="${t}"]`).click(),
    eylemler: () => [...d.querySelectorAll('#sheet-actions button[data-act]')].map(b => b.dataset.act),
    eylem: act => d.querySelector(`#sheet-actions button[data-act="${act}"]`).click(),
    toast: () => d.getElementById('app-toast').textContent,
    gonder: id => d.getElementById(id).dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true })),
    kapat: () => w.close(),
  };
}
const apiIstekleri = c => c.istekler.filter(x => x.includes('/api/yonetim'));
async function api(islem, { method = 'GET', govde, token } = {}) {
  const headers = { 'X-Forwarded-For': '10.1.1.1' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (govde) headers['Content-Type'] = 'application/json';
  const r = await fetch(`${s.taban}/api/yonetim?islem=${islem}`, { method, headers, body: govde ? JSON.stringify(govde) : undefined });
  return r.json();
}
const bosta = c => until(() => c.ev('adminQueue.length') === 0 && !c.ev('adminUi.busy'), 5000, `${c.ad} kuyruk`);

try {
  // ---------------------------------------------------------------------------
  console.log('A) Ziyaretçi: kalıcı kaydedilenler/okundu, okuyucuda ⋮ (pasife al, Keşfet\'ten sil) — ağa istek yok');
  const v1 = cihaz('ziyaretçi');
  check('canlı yazılar yüklendi (yerel data/daily.json)', await until(() => v1.kartlar().length > 20, 6000, 'kartlar'), `kart: ${v1.kartlar().length}`);
  const ilk = v1.kartlar()[0];
  const ilkId = v1.kartId(ilk);
  const ilkUid = v1.ev(`findArticle(${ilkId}).uid`);
  check('kart kimliği kalıcı uid\'den türetilir (1.000.000+)', ilkId >= 1e6 && /^[a-z0-9-]+-[0-9a-f]{8}$/.test(ilkUid), `${ilkId} ${ilkUid}`);
  check('uid verideki id ile aynı', daily.articles.some(a => a.id === ilkUid));
  ilk.querySelector('button[onclick^="toggleBookmark"]').click();
  const kayitli = JSON.parse(v1.w.localStorage.getItem('kose-saved-v1') || '[]');
  check('yer imi localStorage\'a yazıldı (kose-saved-v1)', kayitli.length === 1 && kayitli[0].uid === ilkUid && kayitli[0].fullContent.length > 50);
  const ikinciId = v1.kartId(v1.kartlar()[1]);
  v1.ev(`openReader(${ikinciId})`);
  const ikinciUid = v1.ev(`findArticle(${ikinciId}).uid`);
  check('okundu kalıcı uid ile yazıldı (kose-read-v2)', JSON.parse(v1.w.localStorage.getItem('kose-read-v2') || '[]').some(r => r[0] === ikinciUid));
  const yazar = v1.ev(`findArticle(${ikinciId}).author`);
  const kaynak = v1.ev(`findArticle(${ikinciId}).source`);
  v1.d.getElementById('reader-more-btn').click();
  check('okuyucudaki ⋮ Keşfet\'teki seçenek sayfasını açar', !v1.d.getElementById('action-sheet').classList.contains('hidden')
    && v1.d.getElementById('sheet-title').textContent === v1.ev(`formatAuthorName(${JSON.stringify(yazar)})`));
  check('ziyaretçide yönetici satırı (kaynağı çekimden çıkar) yok', JSON.stringify(v1.eylemler()) === JSON.stringify(['open', 'fav', 'passivate', 'hide']), v1.eylemler().join(','));
  v1.eylem('passivate');
  check('pasife alındı (#14 listesi, gazetesiyle)', v1.ev(`passiveWriters.length === 1 && passiveWriters[0].source === ${JSON.stringify(kaynak)}`));
  check('pasif yazarın yazısı akıştan SİLİNMEZ, soluk "PASİF YAZAR" etiketiyle kalır',
    v1.ev(`articles.some(a => a.id === ${ikinciId})`) && v1.kartlar().some(k => v1.kartId(k) === ikinciId && /PASİF YAZAR/.test(k.textContent)));
  check('okuyucuda pasif rozeti tazelendi', !v1.d.getElementById('reader-passive-badge').classList.contains('hidden'));
  check('ziyaretçiye depo JSON\'u hatırlatılır', /JSON'u kopyala/.test(v1.toast()), v1.toast());
  v1.d.getElementById('reader-more-btn').click();
  v1.eylem('hide');
  check('Keşfet listesinden silindi (#14 listesi)', v1.ev(`hiddenWriters.length === 1 && favKeyName(hiddenWriters[0].name) === favKeyName(${JSON.stringify(yazar)})`));
  v1.d.getElementById('close-reader-btn').click();
  v1.sekme('settings');
  check('Ayarlar: yönetici giriş formu', Boolean(v1.d.getElementById('admin-login-form')));
  check('Ayarlar: pasif depo kartı; "çevrimiçi" notu ziyaretçide gizli', /1 bu cihazda/.test(v1.d.getElementById('passive-repo-meta').textContent)
    && v1.d.getElementById('passive-online-note').classList.contains('hidden'), v1.d.getElementById('passive-repo-meta').textContent);
  check('ziyaretçi akışında /api/yonetim\'e HİÇ istek yok', apiIstekleri(v1).length === 0, apiIstekleri(v1).join(' | '));
  const depo1 = v1.depo();
  v1.kapat();

  const v2 = cihaz('ziyaretçi (yeniden açılış)', depo1);
  await until(() => v2.kartlar().length > 20, 6000, 'kartlar 2');
  check('yeniden açılışta aynı yazı aynı sayısal kimliği alır', v2.ev(`findArticle(${ilkId}) && findArticle(${ilkId}).uid`) === ilkUid);
  v2.sekme('saved');
  check('Kaydedilen sekmesi yer imini hatırlıyor', v2.kartlar().length === 1 && v2.kartId(v2.kartlar()[0]) === ilkId);
  check('okundu işareti yeniden açılışta duruyor', v2.ev(`findArticle(${ikinciId}).isRead`) === true);
  check('pasif ve Keşfet\'ten silme kalıcı', v2.ev('passiveWriters.length === 1 && hiddenWriters.length === 1'));
  v2.kapat();

  // Akıştan düşmüş kayıtlı yazı + XSS denemesi
  const arsiv = [{
    uid: 'eski-0badc0de', title: '<img src=x onerror="window.__xss=1">Eski yazı', author: 'Arşiv YAZAR', source: 'Eski Gazete',
    category: 'Gündem', url: 'https://ornek.org/eski', date: '3 gün önce', readTime: '4 dk', snippet: 'Özet <b>kalın değil</b>',
    avatar: '" onerror="window.__xss=2', savedAt: Date.now() - 1000, fullContent: '<p>Arşivdeki tam metin.</p>',
  }];
  const v3 = cihaz('ziyaretçi (arşiv)', { 'kose-saved-v1': JSON.stringify(arsiv) });
  await until(() => v3.kartlar().length > 20, 6000, 'kartlar 3');
  v3.sekme('saved');
  const ak = v3.kartlar()[0];
  check('akıştan düşmüş kayıt ARŞİV rozetiyle listelenir', v3.kartlar().length === 1 && ak.textContent.includes('ARŞİV') && ak.textContent.includes('Eski yazı'));
  check('başlık/özet/avatar kaçışlandı (enjekte img yok, betik çalışmadı)', ak.querySelectorAll('h2 img').length === 0 && ak.querySelectorAll('b').length === 0 && v3.w.__xss === undefined);
  v3.ev(`openReader(${v3.kartId(ak)})`);
  check('arşiv yazısı kayıtlı tam metinle açılır', v3.d.getElementById('reader-body').textContent.includes('Arşivdeki tam metin'));
  const depoArsiv = v3.depo();
  v3.kapat();

  // ---------------------------------------------------------------------------
  console.log('B) Yönetici — cihaz A: giriş, birleştirme (pasif + Keşfet\'ten silinenler dahil), ayar eşitlemesi');
  const A = cihaz('A', depoArsiv);
  await until(() => A.kartlar().length > 20, 6000, 'A kartlar');
  A.kartlar()[3].querySelector('button[onclick^="toggleFavoriteFromCard"]').click();
  A.kartlar()[1].querySelector('button[onclick^="toggleBookmark"]').click(); // canlı bir yazı da kaydedilir
  check('A girişten önce 2 kayıt tutuyor (canlı + arşiv)', A.ev('savedArticles.size') === 2);
  const favYerel = A.ev('favoriteWriters.map(f => f.name)');
  const p1 = A.ev('articles[6]');
  A.ev(`setPassiveWriter({ name: ${JSON.stringify(p1.author)}, source: ${JSON.stringify(p1.source)} }, true)`);
  A.ev(`hideWriter({ name: 'Gizli Yazar', source: 'Hürriyet' })`);
  A.ev(`hidePaper('sabah', 'Sabah')`);
  A.sekme('settings');
  A.d.getElementById('admin-password').value = 'yanlis-sifre';
  A.gonder('admin-login-form');
  check('yanlış şifre hata mesajı', await until(() => /Şifre yanlış/.test(A.d.getElementById('admin-card').textContent), 3000, 'hata'));
  A.d.getElementById('admin-password').value = SIFRE;
  A.gonder('admin-login-form');
  check('doğru şifreyle giriş', await until(() => A.ev('isAdmin()') && /eşitleme açık/.test(A.d.getElementById('admin-card').textContent), 5000, 'giriş'));
  await bosta(A);
  const token = A.w.localStorage.getItem('kose-admin-token');
  let sv = await api('durum', { token });
  check('yerel favori sunucuya birleştirildi', sv.kisisel.fav.length === 1 && sv.kisisel.fav[0].name === favYerel[0], JSON.stringify(sv.kisisel.fav));
  check('yerel kayıtlar (canlı + arşiv) sunucuya birleştirildi', sv.kisisel.kayit.length === 2 && sv.kisisel.kayit.some(k => k.uid === 'eski-0badc0de'));
  check('pasif yazar sunucuda (gazetesiyle) — kazıyıcı kural ucundan okur',
    sv.kaynak.pasif.yazarlar.length === 1 && sv.kaynak.pasif.yazarlar[0].ad === A.ev(`cleanWriterName(${JSON.stringify(p1.author)})`) && sv.kaynak.pasif.yazarlar[0].kaynak === p1.source,
    JSON.stringify(sv.kaynak.pasif.yazarlar));
  check('Keşfet\'ten silinen yazar + gazete sunucuda', sv.kisisel.gizli.length === 2
    && sv.kisisel.gizli.some(g => g.tur === 'gazete' && g.kaynak === 'sabah') && sv.kisisel.gizli.some(g => g.tur === 'yazar' && g.ad === 'Gizli Yazar'), JSON.stringify(sv.kisisel.gizli));
  check('ayarlar ilk girişte sunucuya yüklendi (karıştır dahil, ses hariç)', sv.kisisel.ayar.readerFont === 16 && sv.kisisel.ayar.shuffle === false && !('ttsVoice' in sv.kisisel.ayar), JSON.stringify(sv.kisisel.ayar));
  check('Ayarlar: "liste çevrimiçi" notu yöneticide görünür', !A.d.getElementById('passive-online-note').classList.contains('hidden'));
  A.d.querySelector('#settings-font-group button[data-font="19"]').click();
  A.ev('setShuffle(true)');
  A.sekme('feed');
  const aOkunan = A.kartId(A.kartlar()[5]);
  A.ev(`openReader(${aOkunan})`);
  A.d.getElementById('close-reader-btn').click();
  const aOkunanUid = A.ev(`findArticle(${aOkunan}).uid`);
  await until(async () => { const x = await api('durum', { token }); return x.kisisel.ayar.readerFont === 19 && x.kisisel.ayar.shuffle === true && x.kisisel.okundu.some(o => o[0] === aOkunanUid); }, 4000, 'ayar+okundu');
  sv = await api('durum', { token });
  check('punto (19) ve karıştır (açık) sunucuda', sv.kisisel.ayar.readerFont === 19 && sv.kisisel.ayar.shuffle === true, JSON.stringify(sv.kisisel.ayar));
  check('okundu işareti sunucuda', sv.kisisel.okundu.some(o => o[0] === aOkunanUid));

  console.log('C) Yönetici — kaynak kuralları (panel + seçenek sayfası)');
  A.sekme('settings');
  A.d.querySelector('[data-admin-action="panel"]').click();
  check('yönetim paneli açıldı (Ayarlar sekmesi seçili kalır)', !A.d.getElementById('admin-view').classList.contains('hidden') && A.d.querySelector('.nav-btn[data-tab="settings"]').classList.contains('text-accent'));
  await until(() => A.d.querySelectorAll('#admin-source-rows [data-source-toggle]').length >= 10, 4000, 'kaynak satırları');
  const satirlar = [...A.d.querySelectorAll('#admin-source-rows [data-source-toggle]')];
  check('kaynak listesi (katalog yoksa dizin + akıştan)', satirlar.length >= 15, String(satirlar.length));
  check('panelde pasif yazar ve Keşfet\'ten silinenler listeleniyor', A.d.querySelectorAll('[data-admin-unpassive]').length === 1
    && A.d.querySelectorAll('[data-admin-restore-writer]').length === 1 && A.d.querySelectorAll('[data-admin-restore-paper]').length === 1);
  const hedef = satirlar.find(b => A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(b.dataset.sourceToggle)}).length`) > 0);
  const hedefKey = hedef.dataset.sourceToggle;
  const oncekiSayi = A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`);
  hedef.click();
  check(`"${hedefKey}" (${oncekiSayi} yazı) yöneticinin akışından hemen kalktı`, A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`) === 0);
  A.d.getElementById('admin-source-search').value = hedef.dataset.sourceName.slice(0, 4);
  A.d.getElementById('admin-source-search').dispatchEvent(new A.w.Event('input', { bubbles: true }));
  check('kaynak araması listeyi süzer', A.d.querySelectorAll('#admin-source-rows [data-source-toggle]').length < satirlar.length);
  A.d.getElementById('admin-feed-url').value = 'ornekblog.com.tr/feed';
  A.d.getElementById('admin-feed-name').value = 'Örnek Blog';
  A.d.getElementById('admin-feed-author').value = 'Ayşe Yazar';
  A.d.getElementById('admin-feed-category').value = 'Ekonomi';
  A.gonder('admin-feed-form');
  A.d.getElementById('admin-feed-url').value = 'https://www.youtube.com/channel/UCQmDWRUf_X8BSrrDOSZA-NA';
  A.d.getElementById('admin-feed-name').value = 'Kanal';
  A.gonder('admin-feed-form');
  // Panelden pasife alma: öneri listesindeki "Ad · Gazete" biçimi
  const p2 = A.ev('articles.find(a => a.isLive && !isPassiveWriter(a.author, a.source) && a.author !== "Köşe Yazarı")');
  A.d.getElementById('admin-writer-input').value = `${A.ev(`formatAuthorName(${JSON.stringify(p2.author)})`)} · ${p2.source}`;
  A.gonder('admin-writer-form');
  await until(async () => { const x = await api('kaynaklar'); return x.ek.length === 2 && x.pasif.yazarlar.length === 2 && x.pasif.kaynaklar.length === 1; }, 5000, 'kaynak kuralları');
  let kr = await api('kaynaklar');
  check('sunucu: kaynak pasif', kr.pasif.kaynaklar.some(p => p.key === hedefKey), JSON.stringify(kr.pasif.kaynaklar));
  check('sunucu: panelden pasife alınan yazar gazetesiyle', kr.pasif.yazarlar.some(y => y.kaynak === p2.source && A.ev(`favKeyName(${JSON.stringify(y.ad)}) === favKeyName(${JSON.stringify(p2.author)})`)), JSON.stringify(kr.pasif.yazarlar));
  check('sunucu: 2 eklenen kaynak (https eklendi, YouTube akışa çevrildi)',
    kr.ek.some(e => e.feed === 'https://ornekblog.com.tr/feed' && e.category === 'Ekonomi' && e.author === 'Ayşe Yazar')
    && kr.ek.some(e => e.feed === 'https://www.youtube.com/feeds/videos.xml?channel_id=UCQmDWRUf_X8BSrrDOSZA-NA'), JSON.stringify(kr.ek));
  await until(() => A.ev('ensureKaynakMeta().ek.every(e => /^ek-/.test(e.key))'), 4000, 'geçici anahtarlar');
  check('panelde geçici anahtarlar sunucu anahtarıyla değişti', A.ev('ensureKaynakMeta().ek.map(e => e.key).join(",")').split(',').every(k => /^ek-[0-9a-f]{8}$/.test(k)));
  check('pasif yazarın yazıları akışta kalır (soluk), silinmez', A.ev(`articles.some(a => isPassiveWriter(a.author, a.source) && favKeyName(a.author) === favKeyName(${JSON.stringify(p2.author)}))`));
  const silBtn = [...A.d.querySelectorAll('[data-ek-delete]')].find(b => b.dataset.ekName === 'Kanal');
  silBtn.click();
  await until(async () => (await api('kaynaklar')).ek.length === 1, 4000, 'ek sil');
  kr = await api('kaynaklar');
  check('eklenen kaynak silindi', kr.ek.length === 1 && kr.ek[0].name === 'Örnek Blog');
  check('herkese açık kaynaklar yanıtı kişisel veri içermez', !JSON.stringify(kr).includes(favYerel[0]) && !JSON.stringify(kr).includes('Gizli Yazar'));
  // Okuyucudaki ⋮: yöneticide "kaynağı çekimden çıkar" satırı
  A.sekme('feed');
  const baskaKart = A.kartlar().find(k => A.ev(`sourceKeyOf(findArticle(${A.kartId(k)})) !== ${JSON.stringify(hedefKey)}`));
  const baskaKey = A.ev(`sourceKeyOf(findArticle(${A.kartId(baskaKart)}))`);
  A.ev(`openReader(${A.kartId(baskaKart)})`);
  A.d.getElementById('reader-more-btn').click();
  check('yönetici seçenek sayfasında "kaynağı çekimden çıkar" var', A.eylemler().includes('source-off'), A.eylemler().join(','));
  A.eylem('source-off');
  check('okuyucudan kaynak çekimden çıkarıldı (yönetici akışından kalktı)', A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(baskaKey)}).length`) === 0);
  A.d.getElementById('close-reader-btn').click();
  await until(async () => (await api('kaynaklar')).pasif.kaynaklar.length === 2, 4000, 'okuyucudan kaynak');
  check('sunucu: ikinci pasif kaynak', (await api('kaynaklar')).pasif.kaynaklar.some(p => p.key === baskaKey));

  console.log('D) Yönetici — cihaz B: aynı düzen, değişiklikler iki yönlü');
  const B = cihaz('B');
  await until(() => B.kartlar().length > 20, 6000, 'B kartlar');
  B.sekme('settings');
  B.d.getElementById('admin-password').value = SIFRE;
  B.gonder('admin-login-form');
  await until(() => B.ev('isAdmin()') && B.ev('adminMeta.lastSync') > 0 && !B.ev('adminUi.busy'), 5000, 'B giriş');
  check('B: favoriler A ile aynı', JSON.stringify(B.ev('favoriteWriters.map(f => f.name)')) === JSON.stringify(favYerel));
  check('B: punto 19 ve karıştır açık geldi', B.ev('appSettings.readerFont') === 19 && B.ev('appSettings.shuffle') === true);
  check('B: okundu işareti geldi', B.ev(`readMap.has(${JSON.stringify(aOkunanUid)})`));
  check('B: kaydedilenler geldi (2: canlı + arşiv)', B.ev('savedArticles.size') === 2, String(B.ev('savedArticles.size')));
  check('B: pasif yazarlar geldi (gazeteleriyle)', B.ev('passiveWriters.length') === 2 && B.ev(`isPassiveWriter(${JSON.stringify(p1.author)}, ${JSON.stringify(p1.source)})`));
  check('B: Keşfet\'ten silinenler geldi', B.ev('hiddenWriters.length === 1 && hiddenPapers.length === 1 && isHiddenPaper("sabah")'));
  check('B: kaynak kuralları akışa uygulandı', B.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)} || sourceKeyOf(a) === ${JSON.stringify(baskaKey)}).length`) === 0);
  B.sekme('saved');
  const bArsiv = B.kartlar().find(k => k.textContent.includes('ARŞİV'));
  check('B: arşiv yazısı listede', Boolean(bArsiv));
  B.ev(`openReader(${B.kartId(bArsiv)})`);
  check('B: arşiv yazısının tam metni sunucudan getirildi', await until(() => B.d.getElementById('reader-body').textContent.includes('Arşivdeki tam metin'), 3000, 'metin'));
  B.d.getElementById('close-reader-btn').click();
  // A: favori kaldır + pasif yazarı aktif et -> B sekmeye dönünce görür
  A.sekme('favorites');
  A.d.querySelector('#favorites-list [data-remove-fav]').click();
  A.ev(`setPassiveWriter({ name: ${JSON.stringify(p1.author)}, source: ${JSON.stringify(p1.source)} }, false)`);
  await bosta(A);
  B.d.dispatchEvent(new B.w.Event('visibilitychange'));
  check('B: A\'nın kaldırdığı favori kalktı', await until(() => B.ev('favoriteWriters.length') === 0, 4000, 'B fav'));
  check('B: A\'nın aktif ettiği yazar artık pasif değil', await until(() => B.ev(`!isPassiveWriter(${JSON.stringify(p1.author)}, ${JSON.stringify(p1.source)})`) && B.ev('passiveWriters.length') === 1, 4000, 'B pasif'));
  // B: gazeteyi Keşfet'e geri koyar -> A'da da geri gelir
  B.ev(`restorePaper('sabah')`);
  await bosta(B);
  A.d.dispatchEvent(new A.w.Event('visibilitychange'));
  check('A: B\'nin geri koyduğu gazete A\'da da geri geldi', await until(() => A.ev('!isHiddenPaper("sabah")'), 4000, 'A gazete'));

  console.log('E) Çevrimdışı kuyruk ve yeniden deneme');
  s.redis.arizaAyarla(true);
  A.sekme('feed');
  const kayitsizKart = A.kartlar().find(k => A.ev(`!findArticle(${A.kartId(k)}).isBookmarked`));
  kayitsizKart.querySelector('button[onclick^="toggleBookmark"]').click();
  await until(() => A.ev('adminUi.error') !== '', 4000, 'hata');
  check('sunucu hatasında değişiklik kuyrukta bekler (localStorage)', JSON.parse(A.w.localStorage.getItem('kose-admin-queue')).length === 1);
  A.sekme('settings');
  check('durum satırı bekleyen değişikliği gösterir', /Eşitlenemedi — 1 değişiklik bekliyor/.test(A.d.getElementById('admin-status').textContent), A.d.getElementById('admin-status').textContent);
  s.redis.arizaAyarla(false);
  await A.ev('flushAdminQueue()');
  check('bağlantı düzelince kuyruk boşaldı', A.ev('adminQueue.length') === 0 && A.ev('adminUi.error') === '');
  const sayKayit = (await api('durum', { token })).kisisel.kayit.length;
  check('bekleyen kayıt sunucuya ulaştı', sayKayit === 3, String(sayKayit));

  console.log('F) Tüm cihazlardan çıkış');
  B.sekme('settings');
  B.d.querySelector('[data-admin-action="logout-all"]').click();
  await until(() => !B.ev('isAdmin()'), 4000, 'B çıkış');
  check('B çıkış yaptı; giriş formu geri geldi', Boolean(B.d.getElementById('admin-login-form')));
  check('B: yerel kopya cihazda kaldı', B.ev('savedArticles.size') >= 2 && B.ev('passiveWriters.length') === 1);
  A.d.dispatchEvent(new A.w.Event('visibilitychange'));
  check('A: oturumu da düştü (401) ve kibarca çıkış yaptı', await until(() => !A.ev('isAdmin()'), 4000, 'A düştü'));
  check('A: kullanıcıya sebep gösterildi', /oturum/i.test(A.toast()), A.toast());
  check('A: yönetici kuralları (pasif kaynak) artık uygulanmaz', A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`) > 0);

  console.log('G) Kurulum eksikken giriş');
  delete process.env.ADMIN_PASSWORD;
  const C = cihaz('C');
  await until(() => C.kartlar().length > 20, 6000, 'C kartlar');
  C.sekme('settings');
  C.d.getElementById('admin-password').value = 'herhangi-bir';
  C.gonder('admin-login-form');
  check('kurulum eksik mesajı + adımlar', await until(() => /kurulumu eksik/.test(C.d.getElementById('admin-card').textContent) && /Upstash for Redis/.test(C.d.getElementById('admin-card').textContent), 3000, 'kurulum'), C.d.getElementById('admin-card').textContent.trim().slice(0, 240));
  process.env.ADMIN_PASSWORD = SIFRE;

  const tumHatalar = [v1, v2, v3, A, B, C].flatMap(c => c.hatalar.map(h => `[${c.ad}] ${h.split('\n')[0]}`))
    .filter(h => !/Not implemented: (navigation|HTMLMediaElement|window\.scrollTo)/.test(h));
  check('sayfada yakalanmamış JS hatası yok', tumHatalar.length === 0, tumHatalar.slice(0, 5).join(' | '));
  [A, B, C].forEach(c => c.kapat());
} finally {
  await s.kapat();
}

console.log(`\n${gecen} denetim geçti, ${hata} başarısız`);
if (hata) { console.log('YÖNETİCİ ARAYÜZ TESTLERİ BAŞARISIZ'); process.exit(1); }
console.log('TÜM YÖNETİCİ ARAYÜZ TESTLERİ GEÇTİ');
process.exit(0);
