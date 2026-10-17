// Uçtan uca: gerçek index.html jsdom'da açılır; yerel sunucu statik dosyaları,
// GERÇEK /api/yonetim fonksiyonunu ve Upstash taklidini sunar. Ziyaretçi düzeni,
// iki yönetici cihazı arasında eşitleme, kaynak kuralları, çevrimdışı kuyruk ve
// oturum kapatma denetlenir.
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

try {
  // ---------------------------------------------------------------------------
  console.log('A) Ziyaretçi: kalıcı kaydedilenler, kalıcı okundu, gizleme — ağa istek yok');
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
  const okunan = JSON.parse(v1.w.localStorage.getItem('kose-read-v2') || '[]');
  check('okundu kalıcı uid ile yazıldı (kose-read-v2)', okunan.some(r => r[0] === ikinciUid));
  // Okuyucu ⋮ menüsü: yazarı gizle
  const yazar = v1.ev(`findArticle(${ikinciId}).author`);
  v1.d.getElementById('reader-more-btn').click();
  const menuMaddeleri = [...v1.d.querySelectorAll('#reader-more-menu [data-reader-act]')].map(b => b.dataset.readerAct);
  check('ziyaretçi menüsünde yalnızca kişisel gizleme var', menuMaddeleri.join(',') === 'hide-writer,hide-source', menuMaddeleri.join(','));
  v1.d.querySelector('[data-reader-act="hide-writer"]').click();
  v1.d.getElementById('close-reader-btn').click();
  const kalan = v1.ev(`articles.filter(a => favKeyName(a.author) === favKeyName(${JSON.stringify(yazar)})).length`);
  check(`"${yazar}" akıştan gizlendi`, kalan === 0 && v1.ev('allArticles.length') > v1.ev('articles.length'));
  check('geri al bildirimi göründü', !v1.d.getElementById('toast').classList.contains('hidden') && v1.d.getElementById('toast-action').textContent === 'Geri al');
  v1.sekme('settings');
  check('Ayarlar: Gizlenenler kartı görünür', !v1.d.getElementById('hidden-card').classList.contains('hidden') && v1.d.querySelectorAll('#hidden-list [data-unhide]').length === 1);
  check('Ayarlar: yönetici giriş formu', Boolean(v1.d.getElementById('admin-login-form')));
  check('ziyaretçi akışında /api/yonetim\'e HİÇ istek yok', apiIstekleri(v1).length === 0, apiIstekleri(v1).join(' | '));
  const depo1 = v1.depo();
  v1.kapat();

  const v2 = cihaz('ziyaretçi (yeniden açılış)', depo1);
  await until(() => v2.kartlar().length > 20, 6000, 'kartlar 2');
  check('yeniden açılışta aynı yazı aynı sayısal kimliği alır', v2.ev(`findArticle(${ilkId}) && findArticle(${ilkId}).uid`) === ilkUid);
  v2.sekme('saved');
  check('Kaydedilen sekmesi yer imini hatırlıyor', v2.kartlar().length === 1 && v2.kartId(v2.kartlar()[0]) === ilkId);
  check('okundu işareti yeniden açılışta duruyor', v2.ev(`findArticle(${ikinciId}) ? findArticle(${ikinciId}).isRead : 'gizli'`) !== false);
  check('gizleme kalıcı', v2.ev(`articles.some(a => favKeyName(a.author) === favKeyName(${JSON.stringify(yazar)}))`) === false);
  v2.d.querySelector('[data-unhide]') || v2.sekme('settings');
  v2.sekme('settings');
  v2.d.querySelector('#hidden-list [data-unhide]').click();
  check('Gizlenenler kartından yeniden gösterilir', v2.ev(`articles.some(a => favKeyName(a.author) === favKeyName(${JSON.stringify(yazar)}))`) === true);
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
  console.log('B) Yönetici — cihaz A: giriş, birleştirme, ayar/favori eşitlemesi');
  const A = cihaz('A', depoArsiv);
  await until(() => A.kartlar().length > 20, 6000, 'A kartlar');
  A.kartlar()[3].querySelector('button[onclick^="toggleFavoriteFromCard"]').click();
  A.kartlar()[1].querySelector('button[onclick^="toggleBookmark"]').click(); // canlı bir yazı da kaydedilir
  check('A girişten önce 2 kayıt tutuyor (canlı + arşiv)', A.ev('savedArticles.size') === 2);
  const favYerel = A.ev('favoriteWriters.map(f => f.name)');
  A.sekme('settings');
  A.d.getElementById('admin-password').value = 'yanlis-sifre';
  A.d.getElementById('admin-login-form').dispatchEvent(new A.w.Event('submit', { cancelable: true, bubbles: true }));
  check('yanlış şifre hata mesajı', await until(() => /Şifre yanlış/.test(A.d.getElementById('admin-card').textContent), 3000, 'hata'), A.d.getElementById('admin-card').textContent.trim().slice(0, 200));
  A.d.getElementById('admin-password').value = SIFRE;
  A.d.getElementById('admin-login-form').dispatchEvent(new A.w.Event('submit', { cancelable: true, bubbles: true }));
  check('doğru şifreyle giriş', await until(() => A.ev('isAdmin()') && /eşitleme açık/.test(A.d.getElementById('admin-card').textContent), 5000, 'giriş'));
  await until(() => A.ev('adminQueue.length') === 0 && !A.ev('adminUi.busy'), 5000, 'A kuyruk');
  const token = A.w.localStorage.getItem('kose-admin-token');
  let sv = await api('durum', { token });
  check('yerel favori sunucuya birleştirildi', sv.kisisel.fav.length === 1 && sv.kisisel.fav[0].name === favYerel[0], JSON.stringify(sv.kisisel.fav));
  check('yerel kayıtlar (canlı + arşiv) sunucuya birleştirildi', sv.kisisel.kayit.length === 2 && sv.kisisel.kayit.some(k => k.uid === 'eski-0badc0de'), JSON.stringify(sv.kisisel.kayit.map(k => k.uid)));
  check('ayarlar ilk girişte sunucuya yüklendi', sv.kisisel.ayar.readerFont === 16 && sv.kisisel.ayar.autoRefresh === true, JSON.stringify(sv.kisisel.ayar));
  check('cihaza özgü ses ayarı sunucuya gitmedi', !('ttsVoice' in sv.kisisel.ayar));
  // Ayar değiştir (Büyük punto) ve okundu işareti
  A.d.querySelector('#settings-font-group button[data-font="19"]').click();
  A.sekme('feed');
  const aOkunan = A.kartId(A.kartlar()[5]);
  A.ev(`openReader(${aOkunan})`);
  A.d.getElementById('close-reader-btn').click();
  const aOkunanUid = A.ev(`findArticle(${aOkunan}).uid`);
  await until(async () => { const x = await api('durum', { token }); return x.kisisel.ayar.readerFont === 19 && x.kisisel.okundu.some(o => o[0] === aOkunanUid); }, 4000, 'ayar+okundu');
  sv = await api('durum', { token });
  check('punto değişikliği sunucuda (19)', sv.kisisel.ayar.readerFont === 19);
  check('okundu işareti sunucuda', sv.kisisel.okundu.some(o => o[0] === aOkunanUid));

  console.log('C) Yönetici — kaynak kuralları (panel)');
  A.sekme('settings');
  A.d.querySelector('[data-admin-action="panel"]').click();
  check('yönetim paneli açıldı (Ayarlar sekmesi seçili kalır)', !A.d.getElementById('admin-view').classList.contains('hidden') && A.d.querySelector('.nav-btn[data-tab="settings"]').classList.contains('text-accent'));
  await until(() => A.d.querySelectorAll('#admin-source-rows [data-source-toggle]').length >= 10, 4000, 'kaynak satırları');
  const satirlar = [...A.d.querySelectorAll('#admin-source-rows [data-source-toggle]')];
  check('kaynak listesi (katalog yoksa dizin + akıştan)', satirlar.length >= 15, String(satirlar.length));
  const hedef = satirlar.find(b => A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(b.dataset.sourceToggle)}).length`) > 0);
  const hedefKey = hedef.dataset.sourceToggle;
  const oncekiSayi = A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`);
  hedef.click();
  check(`"${hedefKey}" (${oncekiSayi} yazı) yöneticinin akışından hemen kalktı`, A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`) === 0);
  A.d.getElementById('admin-source-search').value = hedef.dataset.sourceName.slice(0, 4);
  A.d.getElementById('admin-source-search').dispatchEvent(new A.w.Event('input', { bubbles: true }));
  check('kaynak araması listeyi süzer', A.d.querySelectorAll('#admin-source-rows [data-source-toggle]').length < satirlar.length);
  // Yeni kaynak ekle
  A.d.getElementById('admin-feed-url').value = 'ornekblog.com.tr/feed';
  A.d.getElementById('admin-feed-name').value = 'Örnek Blog';
  A.d.getElementById('admin-feed-author').value = 'Ayşe Yazar';
  A.d.getElementById('admin-feed-category').value = 'Ekonomi';
  A.d.getElementById('admin-feed-form').dispatchEvent(new A.w.Event('submit', { cancelable: true, bubbles: true }));
  // YouTube kanal adresi doğrudan akışa çevrilir
  A.d.getElementById('admin-feed-url').value = 'https://www.youtube.com/channel/UCQmDWRUf_X8BSrrDOSZA-NA';
  A.d.getElementById('admin-feed-name').value = 'Kanal';
  A.d.getElementById('admin-feed-form').dispatchEvent(new A.w.Event('submit', { cancelable: true, bubbles: true }));
  // Yazar çekimden çıkar
  const pasifYazar = A.ev('articles[0].author');
  A.d.getElementById('admin-writer-input').value = pasifYazar;
  A.d.getElementById('admin-writer-form').dispatchEvent(new A.w.Event('submit', { cancelable: true, bubbles: true }));
  await until(async () => { const x = await api('kaynaklar'); return x.ek.length === 2 && x.pasif.yazarlar.length === 1 && x.pasif.kaynaklar.length === 1; }, 5000, 'kaynak kuralları');
  let kr = await api('kaynaklar');
  check('sunucu: kaynak pasif', kr.pasif.kaynaklar.some(p => p.key === hedefKey), JSON.stringify(kr.pasif));
  check('sunucu: yazar pasif', kr.pasif.yazarlar.length === 1 && kr.pasif.yazarlar[0].anahtar === `y:${A.ev(`favKeyName(${JSON.stringify(pasifYazar)})`)}`);
  check('sunucu: 2 eklenen kaynak (https eklendi, YouTube akışa çevrildi)',
    kr.ek.some(e => e.feed === 'https://ornekblog.com.tr/feed' && e.category === 'Ekonomi' && e.author === 'Ayşe Yazar')
    && kr.ek.some(e => e.feed === 'https://www.youtube.com/feeds/videos.xml?channel_id=UCQmDWRUf_X8BSrrDOSZA-NA'), JSON.stringify(kr.ek));
  await until(() => A.ev('ensureKaynakMeta().ek.every(e => /^ek-/.test(e.key))'), 4000, 'geçici anahtarlar');
  check('panelde geçici anahtarlar sunucu anahtarıyla değişti', A.ev('ensureKaynakMeta().ek.map(e => e.key).join(",")').split(',').every(k => /^ek-[0-9a-f]{8}$/.test(k)));
  check('pasif yazar yöneticinin akışında görünmez', A.ev(`articles.some(a => favKeyName(a.author) === favKeyName(${JSON.stringify(pasifYazar)}))`) === false);
  // Eklenen kaynağı sil
  const silBtn = [...A.d.querySelectorAll('[data-ek-delete]')].find(b => b.dataset.ekName === 'Kanal');
  silBtn.click();
  await until(async () => (await api('kaynaklar')).ek.length === 1, 4000, 'ek sil');
  kr = await api('kaynaklar');
  check('eklenen kaynak silindi', kr.ek.length === 1 && kr.ek[0].name === 'Örnek Blog');
  check('herkese açık kaynaklar yanıtı kişisel veri içermez', !JSON.stringify(kr).includes(favYerel[0]));

  console.log('D) Yönetici — cihaz B: aynı düzen, değişiklikler iki yönlü');
  const B = cihaz('B');
  await until(() => B.kartlar().length > 20, 6000, 'B kartlar');
  B.sekme('settings');
  B.d.getElementById('admin-password').value = SIFRE;
  B.d.getElementById('admin-login-form').dispatchEvent(new B.w.Event('submit', { cancelable: true, bubbles: true }));
  await until(() => B.ev('isAdmin()') && B.ev('adminMeta.lastSync') > 0 && !B.ev('adminUi.busy'), 5000, 'B giriş');
  check('B: favoriler A ile aynı', JSON.stringify(B.ev('favoriteWriters.map(f => f.name)')) === JSON.stringify(favYerel));
  check('B: punto ayarı 19 geldi', B.ev('appSettings.readerFont') === 19);
  check('B: okundu işareti geldi', B.ev(`readMap.has(${JSON.stringify(aOkunanUid)})`));
  check('B: kaydedilenler geldi (2: canlı + arşiv)', B.ev('savedArticles.size') === 2, String(B.ev('savedArticles.size')));
  check('B: kaynak kuralı akışa uygulandı', B.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`) === 0);
  // B'de arşiv yazısını aç: tam metin sunucudan gelir
  B.sekme('saved');
  const bArsiv = B.kartlar().find(k => k.textContent.includes('ARŞİV'));
  check('B: arşiv yazısı listede', Boolean(bArsiv));
  B.ev(`openReader(${B.kartId(bArsiv)})`);
  check('B: arşiv yazısının tam metni sunucudan getirildi', await until(() => B.d.getElementById('reader-body').textContent.includes('Arşivdeki tam metin'), 3000, 'metin'));
  B.d.getElementById('close-reader-btn').click();
  // A favoriyi kaldırır -> B sekmeye dönünce görür
  A.sekme('favorites');
  A.d.querySelector('#favorites-list [data-remove-fav]').click();
  await until(() => A.ev('adminQueue.length') === 0 && !A.ev('adminUi.busy'), 4000, 'A fav sil');
  B.d.dispatchEvent(new B.w.Event('visibilitychange'));
  check('B: A\'nın kaldırdığı favori sekmeye dönünce kalktı', await until(() => B.ev('favoriteWriters.length') === 0, 4000, 'B fav'));
  // B yazar gizler -> A'da da gizlenir
  const bGizle = B.ev('articles[2].author');
  B.ev(`setHidden('yazar', ${JSON.stringify(bGizle)}, true)`);
  await until(() => B.ev('adminQueue.length') === 0 && !B.ev('adminUi.busy'), 4000, 'B gizle');
  A.d.dispatchEvent(new A.w.Event('visibilitychange'));
  check('A: B\'nin gizlediği yazar A\'da da gizli', await until(() => A.ev(`isHidden('yazar', ${JSON.stringify(bGizle)})`), 4000, 'A gizli'));

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
  check('B: yerel kopya cihazda kaldı', B.ev('savedArticles.size') >= 2);
  A.d.dispatchEvent(new A.w.Event('visibilitychange'));
  check('A: oturumu da düştü (401) ve kibarca çıkış yaptı', await until(() => !A.ev('isAdmin()'), 4000, 'A düştü'));
  check('A: kullanıcıya sebep gösterildi', /oturum/i.test(A.d.getElementById('toast-text').textContent), A.d.getElementById('toast-text').textContent);
  check('A: yönetici kuralları (pasif kaynak) artık ziyaretçi gibi uygulanmaz', A.ev(`articles.filter(a => sourceKeyOf(a) === ${JSON.stringify(hedefKey)}).length`) > 0);

  console.log('G) Kurulum eksikken giriş');
  delete process.env.ADMIN_PASSWORD;
  const C = cihaz('C');
  await until(() => C.kartlar().length > 20, 6000, 'C kartlar');
  C.sekme('settings');
  C.d.getElementById('admin-password').value = 'herhangi-bir';
  C.d.getElementById('admin-login-form').dispatchEvent(new C.w.Event('submit', { cancelable: true, bubbles: true }));
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
