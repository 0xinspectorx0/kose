// Yönetici API'si (api/yonetim.js) — yerel Upstash taklidiyle uçtan uca denetim.
// Çalıştırma: node patches/uitest/verify-yonetim-api.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { baslat } = require('./yonetim-yerel-sunucu.cjs');
const ic = require('../../api/yonetim.js')._ic;

let hata = 0;
let gecen = 0;
function check(ad, kosul, ayrinti = '') {
  if (kosul) { gecen++; console.log(`  ✓ ${ad}`); }
  else { hata++; console.log(`  ✗ ${ad}${ayrinti ? ` — ${ayrinti}` : ''}`); }
}

const SIFRE = 'dogru-sifre-123';
const s = await baslat({ sifre: SIFRE });
const API = `${s.taban}/api/yonetim`;

async function api(islem, { method = 'GET', govde, token, ip = '10.0.0.1', ham, sorgu = '' } = {}) {
  const headers = { 'X-Forwarded-For': ip };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (govde !== undefined || ham !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}?islem=${islem}${sorgu}`, {
    method, headers, body: ham !== undefined ? ham : (govde !== undefined ? JSON.stringify(govde) : undefined),
  });
  let veri = null;
  try { veri = await res.json(); } catch (e) { veri = null; }
  return { durum: res.status, veri, basliklar: res.headers };
}

try {
  console.log('1) Kurulum denetimi');
  {
    const sifre = process.env.ADMIN_PASSWORD;
    delete process.env.ADMIN_PASSWORD;
    let r = await api('saglik');
    check('şifre yokken saglik ok:false ve eksik listesi', r.durum === 200 && r.veri.ok === false && r.veri.eksik.some(e => e.includes('ADMIN_PASSWORD')), JSON.stringify(r.veri));
    r = await api('durum');
    check('şifre yokken durum 503/kurulum', r.durum === 503 && r.veri.kod === 'kurulum', JSON.stringify(r.veri));
    r = await api('kaynaklar');
    check('şifre yokken de kaynaklar (herkese açık) çalışır', r.durum === 200 && r.veri.ok === true, JSON.stringify(r.veri));
    process.env.ADMIN_PASSWORD = 'kisa';
    r = await api('giris', { method: 'POST', govde: { sifre: 'kisa' } });
    check('8 karakterden kısa şifre reddedilir (503)', r.durum === 503 && /8 karakter/.test(r.veri.hata), JSON.stringify(r.veri));
    process.env.ADMIN_PASSWORD = sifre;
    const url = process.env.KV_REST_API_URL; const tok = process.env.KV_REST_API_TOKEN;
    delete process.env.KV_REST_API_URL; delete process.env.KV_REST_API_TOKEN;
    r = await api('kaynaklar');
    check('Redis yokken kaynaklar 503', r.durum === 503 && r.veri.kod === 'kurulum', JSON.stringify(r.veri));
    process.env.UPSTASH_REDIS_REST_URL = url; process.env.UPSTASH_REDIS_REST_TOKEN = tok;
    r = await api('saglik');
    check('UPSTASH_REDIS_REST_URL/TOKEN adları da kabul edilir', r.veri.ok === true && r.veri.kurulum.redis === true, JSON.stringify(r.veri));
    delete process.env.UPSTASH_REDIS_REST_URL; delete process.env.UPSTASH_REDIS_REST_TOKEN;
    process.env.KV_REST_API_URL = url; process.env.KV_REST_API_TOKEN = tok;
    r = await api('saglik');
    check('kurulum tamam: saglik ok:true', r.veri.ok === true && r.veri.eksik.length === 0);
    check('yanıtlar önbelleğe alınmaz (no-store)', r.basliklar.get('cache-control') === 'no-store');
  }

  console.log('2) Rota ve gövde denetimleri');
  {
    let r = await api('yok-boyle');
    check('bilinmeyen işlem 404', r.durum === 404 && r.veri.kod === 'bilinmeyen');
    r = await api('giris');
    check('GET giris 405', r.durum === 405 && r.veri.kod === 'yontem');
    r = await api('giris', { method: 'POST', ham: '{bozuk' });
    check('bozuk JSON 400', r.durum === 400 && r.veri.kod === 'gecersiz', JSON.stringify(r.veri));
    r = await api('giris', { method: 'POST', ham: JSON.stringify({ sifre: 'x'.repeat(700 * 1024) }) });
    check('çok büyük gövde 413', r.durum === 413 && r.veri.kod === 'buyuk', JSON.stringify(r.veri).slice(0, 120));
  }

  console.log('3) Giriş ve kaba kuvvet sınırı');
  let token;
  {
    let r = await api('giris', { method: 'POST', govde: { sifre: 'yanlis' }, ip: '10.0.0.2' });
    check('yanlış şifre 401/sifre', r.durum === 401 && r.veri.kod === 'sifre', JSON.stringify(r.veri));
    r = await api('giris', { method: 'POST', govde: {}, ip: '10.0.0.2' });
    check('boş şifre 400', r.durum === 400);
    r = await api('giris', { method: 'POST', govde: { sifre: SIFRE }, ip: '10.0.0.2' });
    check('doğru şifre token verir', r.durum === 200 && typeof r.veri.token === 'string' && r.veri.token.includes('.'), JSON.stringify(r.veri));
    check('token bitişi ~180 gün sonra', Math.abs(new Date(r.veri.bitis) - Date.now() - 180 * 864e5) < 60e3);
    token = r.veri.token;
    // Başarılı giriş sayacı sıfırlar; ayrı bir IP'den 10 yanlış denemeden sonra kilit
    let son;
    for (let i = 0; i < 10; i++) son = await api('giris', { method: 'POST', govde: { sifre: `yanlis${i}` }, ip: '10.9.9.9' });
    check('10. yanlış denemede "deneme hakkı kaldı" uyarısı', son.durum === 401 && /0 deneme/.test(son.veri.hata), JSON.stringify(son.veri));
    son = await api('giris', { method: 'POST', govde: { sifre: SIFRE }, ip: '10.9.9.9' });
    check('11. denemede doğru şifre bile 429 (kilit)', son.durum === 429 && son.veri.kod === 'cok-deneme', JSON.stringify(son.veri));
    const r2 = await api('giris', { method: 'POST', govde: { sifre: SIFRE }, ip: '10.0.0.3' });
    check('başka IP etkilenmez', r2.durum === 200);
    const kayit = [...s.redis.veri.keys()].filter(k => k.startsWith('kose:giris:ip:'));
    check('IP adresi ham saklanmaz (özet)', kayit.length > 0 && kayit.every(k => !k.includes('10.9.9.9')), kayit.join(','));
  }

  console.log('4) Oturum doğrulama');
  {
    let r = await api('durum');
    check('token yoksa 401', r.durum === 401 && r.veri.kod === 'yetki');
    const [govde, imza] = token.split('.');
    const sahte = Buffer.from(JSON.stringify({ v: 1, n: 0, e: Date.now() + 1e9, r: 'x' })).toString('base64url');
    r = await api('durum', { token: `${sahte}.${imza}` });
    check('imzası tutmayan token 401', r.durum === 401);
    r = await api('durum', { token: `${govde}.${imza.slice(0, -2)}AA` });
    check('kurcalanmış imza 401', r.durum === 401);
    const ayar = { sir: process.env.KV_REST_API_TOKEN, sifre: SIFRE };
    const gercekNow = Date.now;
    Date.now = () => gercekNow() - 181 * 864e5;
    const eski = ic.tokenUret(ayar, 0).token;
    Date.now = gercekNow;
    r = await api('durum', { token: eski });
    check('süresi dolmuş token 401', r.durum === 401, JSON.stringify(r.veri));
    r = await api('durum', { token });
    check('geçerli token ile durum 200', r.durum === 200 && r.veri.ok === true, JSON.stringify(r.veri));
    check('boş düzen: sayaçlar 0', r.veri.surum.y === 0 && r.veri.surum.k === 0);
    process.env.ADMIN_PASSWORD = 'yeni-sifre-456';
    r = await api('durum', { token });
    check('şifre değişince eski oturum düşer', r.durum === 401);
    process.env.ADMIN_PASSWORD = SIFRE;
    r = await api('durum', { token });
    check('eski şifreye dönünce token yine geçerli (imza şifreye bağlı)', r.durum === 200);
  }

  console.log('5) Kişisel düzen işlemleri');
  {
    const metin = '<p>Uzun bir köşe yazısı gövdesi.</p>';
    let r = await api('uygula', {
      method: 'POST', token, govde: {
        islemler: [
          { tur: 'fav.ekle', anahtar: 'ahmet hakan|hurriyet', veri: { name: 'Ahmet HAKAN', source: 'Hürriyet', photo: 'https://img.example/a.jpg', url: 'javascript:alert(1)' } },
          { tur: 'fav.ekle', anahtar: 'nagehan alci|sozcu', veri: { name: 'Nagehan Alçı', source: 'Sözcü' } },
          { tur: 'kayit.ekle', uid: 'hurriyet-416eff4a', veri: { title: 'Başlık\u0000<b>', author: 'Ahmet HAKAN', source: 'Hürriyet', url: 'https://www.hurriyet.com.tr/x', sourceKey: 'hurriyet' }, metin },
          { tur: 'okundu.ekle', uid: 'hurriyet-416eff4a', t: Date.now() - 1000 },
          { tur: 'okundu.ekle', uid: 'sozcu-1a2b3c4d' },
          { tur: 'ayar.yaz', ad: 'readerFont', deger: 19 },
          { tur: 'ayar.yaz', ad: 'tooltip', deger: true },
          { tur: 'ayar.yaz', ad: 'shuffle', deger: true },
          { tur: 'gizli.ekle', anahtar: 'y:yilmaz ozdil', veri: { tur: 'yazar', ad: 'Yılmaz Özdil' } },
          { tur: 'gizli.ekle', anahtar: 'g:sabah', veri: { tur: 'gazete', ad: 'Sabah' } },
        ],
      },
    });
    check('10 işlem uygulandı, red yok', r.durum === 200 && r.veri.uygulanan === 10 && r.veri.reddedilen.length === 0, JSON.stringify(r.veri));
    check('kişisel sayaç tek artış (1), kaynak sayacı 0', r.veri.surum.y === 1 && r.veri.surum.k === 0, JSON.stringify(r.veri.surum));
    r = await api('durum', { token });
    const k = r.veri.kisisel;
    check('2 favori, ekleme sırasıyla', k.fav.length === 2 && k.fav[0].name === 'Ahmet HAKAN' && k.fav[0].anahtar === 'ahmet hakan|hurriyet', JSON.stringify(k.fav));
    check('javascript: bağlantısı temizlendi', k.fav[0].url === '' && k.fav[0].photo === 'https://img.example/a.jpg');
    check('kayıt özeti saklandı, denetim karakteri temizlendi', k.kayit.length === 1 && k.kayit[0].title === 'Başlık <b>' && k.kayit[0].uid === 'hurriyet-416eff4a', JSON.stringify(k.kayit));
    check('durum yanıtında tam metin YOK (istek üzerine gelir)', !JSON.stringify(r.veri).includes('Uzun bir köşe'));
    check('okundu listesi [uid, zaman]', k.okundu.length === 2 && k.okundu.every(o => typeof o[1] === 'number' && o[1] > 1.5e12), JSON.stringify(k.okundu));
    check('ayarlar (karıştır dahil)', k.ayar.readerFont === 19 && k.ayar.tooltip === true && k.ayar.shuffle === true, JSON.stringify(k.ayar));
    check('gizlenenler', k.gizli.length === 2 && k.gizli.some(g => g.anahtar === 'g:sabah' && g.tur === 'gazete'), JSON.stringify(k.gizli));
    r = await api('metin', { token, sorgu: '&uid=hurriyet-416eff4a' });
    check('metin uç noktası gövdeyi döndürür', r.veri.metin === metin, JSON.stringify(r.veri));
    r = await api('metin', { token, sorgu: '&uid=../../etc' });
    check('geçersiz uid 400', r.durum === 400);

    r = await api('uygula', {
      method: 'POST', token, govde: {
        islemler: [
          { tur: 'fav.sil', anahtar: 'nagehan alci|sozcu' },
          { tur: 'kayit.sil', uid: 'hurriyet-416eff4a' },
          { tur: 'okundu.sil', uid: 'sozcu-1a2b3c4d' },
          { tur: 'gizli.sil', anahtar: 'g:sabah' },
          { tur: 'ayar.yaz', ad: 'ttsVoice', deger: 'Yelda' },
          { tur: 'ayar.yaz', ad: 'readerFont', deger: 99 },
          { tur: 'uydurma' },
          { tur: 'kayit.ekle', uid: 'x y', veri: { title: 't' } },
          null,
        ],
      },
    });
    check('4 geçerli işlem uygulandı, 5 red (sebepli)', r.veri.uygulanan === 4 && r.veri.reddedilen.length === 5 && r.veri.reddedilen.every(x => x.neden), JSON.stringify(r.veri));
    check('cihaza özgü ttsVoice reddedildi', r.veri.reddedilen.some(x => /ttsVoice/.test(x.neden)));
    r = await api('durum', { token });
    check('silmeler yansıdı', r.veri.kisisel.fav.length === 1 && r.veri.kisisel.kayit.length === 0 && r.veri.kisisel.okundu.length === 1 && r.veri.kisisel.gizli.length === 1, JSON.stringify(r.veri.kisisel));
    r = await api('metin', { token, sorgu: '&uid=hurriyet-416eff4a' });
    check('kayıt silinince tam metni de silindi', r.veri.metin === '');
    r = await api('surum', { token });
    check('surum uç noktası', r.veri.surum.y === 2 && r.veri.surum.k === 0, JSON.stringify(r.veri));
    r = await api('uygula', { method: 'POST', token, govde: { islemler: Array.from({ length: 201 }, () => ({ tur: 'okundu.temizle' })) } });
    check('201 işlem 413', r.durum === 413);
    r = await api('uygula', { method: 'POST', token, govde: { islem: [] } });
    check('islemler dizisi yoksa 400', r.durum === 400);
  }

  console.log('6) Okundu listesi en yeni 3000 kayıtla sınırlı');
  {
    const t0 = Date.now() - 4e6;
    for (let b = 0; b < 16; b++) {
      const islemler = Array.from({ length: 200 }, (_, i) => ({ tur: 'okundu.ekle', uid: `kaynak-${String(b * 200 + i).padStart(8, '0')}`, t: t0 + b * 200 + i }));
      await api('uygula', { method: 'POST', token, govde: { islemler } });
    }
    const r = await api('durum', { token });
    const ok = r.veri.kisisel.okundu;
    check('3000 kayıt kaldı', ok.length === 3000, String(ok.length));
    check('en eskiler atıldı, en yeniler kaldı', !ok.some(o => o[0] === 'kaynak-00000000') && ok.some(o => o[0] === 'kaynak-00003199'));
    await api('uygula', { method: 'POST', token, govde: { islemler: [{ tur: 'okundu.temizle' }] } });
    const r2 = await api('durum', { token });
    check('okundu.temizle hepsini siler', r2.veri.kisisel.okundu.length === 0);
  }

  console.log('7) Kaynak kuralları (çekim listesi)');
  {
    let r = await api('uygula', {
      method: 'POST', token, govde: {
        islemler: [
          { tur: 'kaynak.pasif', anahtar: 'k:sabah', veri: { tur: 'kaynak', ad: 'Sabah', key: 'sabah' } },
          { tur: 'kaynak.pasif', anahtar: 'y:ahmet hakan|hurriyet', veri: { tur: 'yazar', ad: 'Ahmet HAKAN', kaynak: 'Hürriyet', url: 'https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/' } },
          { tur: 'ek.ekle', veri: { name: 'Örnek Blog', author: 'Ayşe Yazar', category: 'Ekonomi', feed: 'https://ornek.blog/feed/' } },
          { tur: 'ek.ekle', veri: { name: 'İç ağ', feed: 'http://127.0.0.1:8080/feed' } },
          { tur: 'ek.ekle', veri: { name: 'Bulut meta', feed: 'http://169.254.169.254/latest' } },
          { tur: 'ek.ekle', veri: { name: 'FTP', feed: 'ftp://ornek.org/rss' } },
          { tur: 'kaynak.pasif', anahtar: 'k:Sabah Gazetesi', veri: { tur: 'kaynak', ad: 'x' } },
          { tur: 'ek.ekle', veri: { name: 'Kategorisiz', feed: 'https://b.example/rss', category: 'Magazin' } },
        ],
      },
    });
    check('4 kabul, 4 red (iç ağ/meta/ftp/biçim)', r.veri.uygulanan === 4 && r.veri.reddedilen.length === 4, JSON.stringify(r.veri));
    check('kaynak sayacı arttı', r.veri.surum.k === 1 && r.veri.surum.y >= 2, JSON.stringify(r.veri.surum));
    check('eklenen akışın anahtarı döner (ek-xxxxxxxx)', r.veri.eklenenler.length === 2 && r.veri.eklenenler.every(e => /^ek-[0-9a-f]{8}$/.test(e.key)), JSON.stringify(r.veri.eklenenler));
    r = await api('kaynaklar');
    const kk = r.veri;
    check('herkese açık kaynaklar: pasif kaynak', kk.pasif.kaynaklar.length === 1 && kk.pasif.kaynaklar[0].key === 'sabah', JSON.stringify(kk.pasif));
    check('herkese açık kaynaklar: pasif yazar (gazete + profil adresiyle)', kk.pasif.yazarlar.length === 1 && kk.pasif.yazarlar[0].ad === 'Ahmet HAKAN'
      && kk.pasif.yazarlar[0].kaynak === 'Hürriyet' && kk.pasif.yazarlar[0].url === 'https://www.hurriyet.com.tr/yazarlar/ahmet-hakan/', JSON.stringify(kk.pasif.yazarlar));
    check('eklenen akışlar (bilinmeyen kategori -> Gündem)', kk.ek.length === 2 && kk.ek[0].name === 'Örnek Blog' && kk.ek[0].category === 'Ekonomi' && kk.ek[1].category === 'Gündem', JSON.stringify(kk.ek));
    check('surum ve guncellendi', kk.surum === 1 && !Number.isNaN(Date.parse(kk.guncellendi)));
    check('herkese açık yanıtta kişisel veri yok', !JSON.stringify(kk).includes('Yılmaz'));
    const ekKey = kk.ek[0].key;
    await api('uygula', { method: 'POST', token, govde: { islemler: [{ tur: 'kaynak.pasif', anahtar: `k:${ekKey}`, veri: { tur: 'kaynak', ad: 'Örnek Blog', key: ekKey } }] } });
    r = await api('kaynaklar');
    check('eklenen akış da pasife alınabilir', r.veri.pasif.kaynaklar.some(p => p.key === ekKey));
    await api('uygula', { method: 'POST', token, govde: { islemler: [{ tur: 'ek.sil', key: ekKey }, { tur: 'kaynak.aktif', anahtar: 'k:sabah' }] } });
    r = await api('kaynaklar');
    check('ek.sil akışı ve pasif kaydını birlikte siler; aktif et çalışır', r.veri.ek.length === 1 && !r.veri.pasif.kaynaklar.length && r.veri.surum === 3, JSON.stringify(r.veri));
    const islemler = Array.from({ length: 45 }, (_, i) => ({ tur: 'ek.ekle', veri: { name: `Blog ${i}`, feed: `https://blog${i}.example/feed` } }));
    r = await api('uygula', { method: 'POST', token, govde: { islemler } });
    check('en çok 40 eklenen akış', r.veri.reddedilen.length === 6 && r.veri.reddedilen.every(x => /sınır/.test(x.neden)), JSON.stringify(r.veri.reddedilen.slice(0, 2)));
  }

  console.log('8) Tüm cihazlardan çıkış');
  {
    const r1 = await api('giris', { method: 'POST', govde: { sifre: SIFRE }, ip: '10.0.0.4' });
    const ikinci = r1.veri.token;
    let r = await api('cikis', { method: 'POST', token, govde: { hepsi: false } });
    check('tek cihaz çıkışı sunucuda bir şey değiştirmez', r.veri.hepsi === false && (await api('durum', { token: ikinci })).durum === 200);
    r = await api('cikis', { method: 'POST', token, govde: { hepsi: true } });
    check('hepsi:true kabul edildi', r.durum === 200 && r.veri.hepsi === true);
    check('ilk cihaz düştü', (await api('durum', { token })).durum === 401);
    check('ikinci cihaz da düştü', (await api('durum', { token: ikinci })).durum === 401);
    const r3 = await api('giris', { method: 'POST', govde: { sifre: SIFRE }, ip: '10.0.0.5' });
    check('yeniden giriş yeni nesil token verir', (await api('durum', { token: r3.veri.token })).durum === 200);
    token = r3.veri.token;
  }

  console.log('9) Veritabanı arızası');
  {
    s.redis.arizaAyarla(true);
    const r = await api('durum', { token });
    check('Upstash hatası 502/redis (sır sızdırmadan)', r.durum === 502 && r.veri.kod === 'redis' && !JSON.stringify(r.veri).includes(process.env.KV_REST_API_TOKEN), JSON.stringify(r.veri));
    s.redis.arizaAyarla(false);
  }

  console.log('10) İç yardımcılar');
  {
    check('özel adresler', ['localhost', '127.0.0.1', '10.1.2.3', '192.168.1.1', '172.20.0.1', '169.254.169.254', '::1', 'fd00::1', 'x.internal'].every(ic.ozelAdresMi));
    check('genel adresler', !['example.com', 'fcbarcelona.com', '172.32.0.1', 'fd.example.org', '8.8.8.8'].some(ic.ozelAdresMi));
    check('akış anahtarı kararlı ve büyük/küçük harf duyarsız', ic.akisAnahtari('https://A.example/feed') === ic.akisAnahtari('https://a.example/feed'));
  }
} finally {
  await s.kapat();
}

console.log(`\n${gecen} denetim geçti, ${hata} başarısız`);
if (hata) { console.log('YÖNETİCİ API TESTLERİ BAŞARISIZ'); process.exit(1); }
console.log('TÜM YÖNETİCİ API TESTLERİ GEÇTİ');
