'use strict';
/**
 * Mürekkep — yönetici API'si (Vercel Node.js fonksiyonu, bağımlılıksız)
 * ====================================================================
 * Yöneticinin (site sahibinin) kişisel düzeni ve kaynak kuralları Upstash
 * Redis'te durur; böylece her cihazdan aynı favoriler, kaydedilenler, okundu
 * işaretleri, ayarlar, gizlenenler ve kaynak kuralları görünür. Ziyaretçiler
 * bu API'yi hiç kullanmaz (onların düzeni yalnızca kendi tarayıcılarında kalır).
 *
 * Kurulum (Vercel):
 *   1. Storage -> Upstash for Redis (ücretsiz) -> projeye bağla. Entegrasyon
 *      KV_REST_API_URL / KV_REST_API_TOKEN ortam değişkenlerini ekler
 *      (UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN da kabul edilir).
 *   2. Settings -> Environment Variables -> ADMIN_PASSWORD (en az 8 karakter).
 *   3. Yeniden dağıt (Redeploy).
 *
 * Uç noktalar (hepsi /api/yonetim?islem=...):
 *   GET  saglik     herkese açık — kurulum tamam mı (sır içermez)
 *   GET  kaynaklar  herkese açık — çekim kuralları (pasif kaynak/yazar, eklenen
 *                   akışlar); GitHub Actions'taki kazıyıcı ve röle okur
 *   POST giris      {sifre} -> {token}; IP başına 15 dakikada 10 deneme
 *   GET  durum      (yetkili) kişisel düzen + kaynak kuralları
 *   GET  surum      (yetkili) değişiklik sayaçları — ucuz "yeni bir şey var mı?"
 *   POST uygula     (yetkili) {islemler: [...]} — ekle/sil/yaz işlemleri
 *   GET  metin      (yetkili) &uid=... kaydedilen yazının tam metni
 *   POST cikis      (yetkili) {hepsi: true} -> tüm cihazlardaki oturumları kapatır
 *
 * Oturum anahtarı: HMAC-SHA256 imzalı, 180 gün geçerli. İmza anahtarı şifreden
 * türetilir; ADMIN_PASSWORD değişince tüm oturumlar kendiliğinden düşer.
 */
const crypto = require('crypto');

const ON_EK = 'kose:';
const ANAHTAR = {
  fav: `${ON_EK}y:fav`,               // HASH  anahtar -> {name, source, photo, url, t}
  kayit: `${ON_EK}y:kayit`,           // HASH  uid -> yazı özeti (başlık, yazar, ...)
  metin: `${ON_EK}y:kayit-metin`,     // HASH  uid -> yazının HTML gövdesi (istek üzerine)
  okundu: `${ON_EK}y:okundu`,         // ZSET  uid (puan: okunma zamanı, ms)
  ayar: `${ON_EK}y:ayar`,             // HASH  ayar adı -> JSON değer
  gizli: `${ON_EK}y:gizli`,           // HASH  "y:yazar" / "g:gazete" -> {tur, ad, kaynak, t}
  ySurum: `${ON_EK}y:surum`,          // sayaç: kişisel düzen her değiştiğinde +1
  pasif: `${ON_EK}k:pasif`,           // HASH  "k:kaynak" / "y:yazar|gazete" -> {tur, ad, key | kaynak+url, t}
  ek: `${ON_EK}k:ek`,                 // HASH  key -> eklenen akış {key, name, author, category, feed, t}
  kSurum: `${ON_EK}k:surum`,          // sayaç: kaynak kuralları her değiştiğinde +1
  kZaman: `${ON_EK}k:guncellendi`,    // kaynak kurallarının son değişme anı (ISO)
  nesil: `${ON_EK}oturum:nesil`,      // "tüm cihazlardan çıkış" sayacı
  giris: `${ON_EK}giris:`,            // giriş denemesi sayaçları (TTL'li)
};

const SINIR = {
  govde: 600 * 1024,  // istek gövdesi (bayt)
  islem: 200,         // tek istekte en çok işlem
  fav: 500,
  kayit: 300,
  okundu: 3000,
  gizli: 500,
  pasif: 500,
  ek: 40,
  metin: 80000,       // kaydedilen yazı gövdesi (karakter)
};
const OTURUM_OMRU_MS = 180 * 24 * 3600 * 1000;
const GIRIS_PENCERE_SN = 15 * 60;
const GIRIS_IP_SINIRI = 10;
const GIRIS_GENEL_SINIR = 60;
const KATEGORILER = ['Gündem', 'Ekonomi', 'Teknoloji', 'Kültür-Sanat'];
// Cihazlar arasında taşınan ayarlar. Seslendirme sesi (ttsVoice) bilinçli olarak
// yok: sesler cihaza özgü, telefondaki ses dizüstünde bulunmayabilir.
const AYARLAR = {
  readerFont: v => typeof v === 'number' && Number.isFinite(v) && v >= 13 && v <= 24,
  tooltip: v => typeof v === 'boolean',
  samples: v => typeof v === 'boolean',
  autoRefresh: v => typeof v === 'boolean',
  ttsRate: v => typeof v === 'number' && Number.isFinite(v) && v >= 0.5 && v <= 2,
  shuffle: v => typeof v === 'boolean', // karıştırma açık/kapalı (karışık sıra her cihazda ayrı)
};

class ApiHatasi extends Error {
  constructor(durum, kod, mesaj, ek) {
    super(mesaj);
    this.durum = durum;
    this.kod = kod;
    this.ek = ek || null;
  }
}

// ---------------------------------------------------------------------------
// Kurulum ve Upstash REST istemcisi (fetch; SDK gerekmez)
// ---------------------------------------------------------------------------
function kurulum() {
  const env = process.env;
  const url = String(env.KV_REST_API_URL || env.UPSTASH_REDIS_REST_URL || '').trim();
  const token = String(env.KV_REST_API_TOKEN || env.UPSTASH_REDIS_REST_TOKEN || '').trim();
  const sifre = String(env.ADMIN_PASSWORD || '');
  const eksik = [];
  if (!url || !token) eksik.push('Upstash Redis bağlantısı (KV_REST_API_URL / KV_REST_API_TOKEN)');
  if (!sifre) eksik.push('ADMIN_PASSWORD ortam değişkeni');
  else if (sifre.length < 8) eksik.push('ADMIN_PASSWORD en az 8 karakter olmalı');
  return {
    redis: url && token ? { url: url.replace(/\/+$/, ''), token } : null,
    sifre: sifre.length >= 8 ? sifre : '',
    sir: String(env.ADMIN_SECRET || '') || token,
    eksik,
  };
}

async function upstash(redis, yol, govde) {
  let res;
  try {
    res = await fetch(redis.url + yol, {
      method: 'POST',
      headers: { Authorization: `Bearer ${redis.token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(govde),
      signal: AbortSignal.timeout(9000),
    });
  } catch (e) {
    throw new ApiHatasi(502, 'redis', `Veritabanına ulaşılamadı: ${e && e.message ? e.message : e}`);
  }
  const ham = await res.text();
  let veri;
  try { veri = JSON.parse(ham); } catch (e) { veri = null; }
  if (!res.ok || veri === null) {
    const neden = (veri && veri.error) || ham.slice(0, 200) || `HTTP ${res.status}`;
    throw new ApiHatasi(502, 'redis', `Veritabanı hatası: ${neden}`);
  }
  return veri;
}

// Komutları sırayla çalıştırır (tek HTTP isteği); her komutun sonucunu döndürür.
async function hatAkisi(redis, komutlar) {
  if (!komutlar.length) return [];
  const sonuc = await upstash(redis, '/pipeline', komutlar);
  return sonuc.map((r) => {
    if (r && r.error) throw new ApiHatasi(502, 'redis', `Veritabanı komutu reddedildi: ${r.error}`);
    return r ? r.result : null;
  });
}

// Komutları tek işlem (MULTI/EXEC) olarak çalıştırır: ya hepsi ya hiçbiri.
async function islemBlogu(redis, komutlar) {
  if (!komutlar.length) return [];
  const sonuc = await upstash(redis, '/multi-exec', komutlar);
  if (!Array.isArray(sonuc)) throw new ApiHatasi(502, 'redis', 'Veritabanı işlem bloğu beklenmeyen yanıt verdi');
  return sonuc.map((r) => {
    if (r && r.error) throw new ApiHatasi(502, 'redis', `Veritabanı komutu reddedildi: ${r.error}`);
    return r ? r.result : null;
  });
}

// ---------------------------------------------------------------------------
// Oturum anahtarı (imzalı, durumsuz) ve şifre karşılaştırma
// ---------------------------------------------------------------------------
function imzaAnahtari(ayar) {
  return crypto.createHmac('sha256', ayar.sir).update(`kose-yonetici-v1|${ayar.sifre}`).digest();
}

function tokenUret(ayar, nesil) {
  const yuk = { v: 1, n: Number(nesil) || 0, e: Date.now() + OTURUM_OMRU_MS, r: crypto.randomBytes(9).toString('base64url') };
  const govde = Buffer.from(JSON.stringify(yuk)).toString('base64url');
  const imza = crypto.createHmac('sha256', imzaAnahtari(ayar)).update(govde).digest('base64url');
  return { token: `${govde}.${imza}`, bitis: new Date(yuk.e).toISOString() };
}

function tokenCoz(ayar, token) {
  if (typeof token !== 'string' || token.length > 512) return null;
  const parca = token.split('.');
  if (parca.length !== 2) return null;
  const beklenen = crypto.createHmac('sha256', imzaAnahtari(ayar)).update(parca[0]).digest();
  let gelen;
  try { gelen = Buffer.from(parca[1], 'base64url'); } catch (e) { return null; }
  if (gelen.length !== beklenen.length || !crypto.timingSafeEqual(gelen, beklenen)) return null;
  try {
    const yuk = JSON.parse(Buffer.from(parca[0], 'base64url').toString('utf8'));
    return yuk && yuk.v === 1 ? yuk : null;
  } catch (e) {
    return null;
  }
}

function sifreDogru(girilen, gercek) {
  // Sabit süreli karşılaştırma: uzunluk farkı bile zamanlamadan sızmasın diye özetler kıyaslanır
  const a = crypto.createHash('sha256').update(String(girilen)).digest();
  const b = crypto.createHash('sha256').update(String(gercek)).digest();
  return crypto.timingSafeEqual(a, b);
}

async function yetkiDenetle(req, ayar) {
  const baslik = String((req.headers && (req.headers.authorization || req.headers.Authorization)) || '');
  const m = /^Bearer\s+(\S+)$/i.exec(baslik);
  const yuk = m ? tokenCoz(ayar, m[1]) : null;
  if (!yuk || !(Number(yuk.e) > Date.now())) {
    throw new ApiHatasi(401, 'yetki', 'Oturum geçersiz ya da süresi doldu — yeniden giriş yapın.');
  }
  const [nesil] = await hatAkisi(ayar.redis, [['GET', ANAHTAR.nesil]]);
  if (Number(nesil || 0) !== Number(yuk.n)) {
    throw new ApiHatasi(401, 'yetki', 'Bu cihazın oturumu kapatıldı — yeniden giriş yapın.');
  }
  return yuk;
}

// ---------------------------------------------------------------------------
// Girdi doğrulama yardımcıları
// ---------------------------------------------------------------------------
function yazi(v, max) {
  if (typeof v !== 'string' && typeof v !== 'number') return '';
  // eslint-disable-next-line no-control-regex
  return String(v).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
}

function ozelAdresMi(host) {
  const h = String(host || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (!h) return true;
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal')) return true;
  if (/^(127|10|0)\./.test(h) || /^169\.254\./.test(h) || /^192\.168\./.test(h)) return true;
  const m = /^172\.(\d+)\./.exec(h);
  if (m && Number(m[1]) >= 16 && Number(m[1]) <= 31) return true;
  if (h.includes(':')) return h === '::1' || h === '::' || /^(fc|fd|fe8|fe9|fea|feb)/.test(h);
  return false;
}

function adres(v, { ozelEngelle = false } = {}) {
  const s = yazi(v, 600);
  if (!s) return '';
  try {
    const u = new URL(s);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return '';
    if (u.username || u.password) return '';
    if (ozelEngelle && ozelAdresMi(u.hostname)) return '';
    return u.href.slice(0, 600);
  } catch (e) {
    return '';
  }
}

function anahtar(v, max = 250) {
  const s = typeof v === 'string' ? v.trim() : '';
  // eslint-disable-next-line no-control-regex
  if (!s || s.length > max || /[\u0000-\u001f\u007f]/.test(s)) return '';
  return s;
}

const UID_RX = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;
const KAYNAK_KEY_RX = /^[a-z0-9][a-z0-9-]{0,40}$/;

function zaman(v) {
  const n = Number(v);
  const simdi = Date.now();
  // Saati kaymış cihazlar geleceğe yazmasın; çok eski/bozuk değerler "şimdi" sayılır
  return Number.isFinite(n) && n > 1.5e12 && n <= simdi + 5 * 60 * 1000 ? Math.round(n) : simdi;
}

function akisAnahtari(feed) {
  return `ek-${crypto.createHash('sha256').update(String(feed).toLowerCase()).digest('hex').slice(0, 8)}`;
}

// Tek bir işlemi doğrular ve Redis komutlarına çevirir.
// Dönüş: { komutlar, alan: 'y' (kişisel) | 'k' (kaynak), hash?: eklenen alanın sınırı denetlenecek HASH }
function islemiCevir(op) {
  if (!op || typeof op !== 'object') return { hata: 'işlem bir nesne olmalı' };
  const tur = typeof op.tur === 'string' ? op.tur : '';
  const veri = op.veri && typeof op.veri === 'object' ? op.veri : {};
  switch (tur) {
    case 'fav.ekle': {
      const a = anahtar(op.anahtar);
      const name = yazi(veri.name, 120);
      if (!a || !name) return { hata: 'favori için anahtar ve yazar adı gerekli' };
      const kayit = { name, source: yazi(veri.source, 120), photo: adres(veri.photo), url: adres(veri.url), t: zaman(op.t) };
      return { alan: 'y', hash: 'fav', komutlar: [['HSET', ANAHTAR.fav, a, JSON.stringify(kayit)]] };
    }
    case 'fav.sil': {
      const a = anahtar(op.anahtar);
      if (!a) return { hata: 'favori anahtarı gerekli' };
      return { alan: 'y', komutlar: [['HDEL', ANAHTAR.fav, a]] };
    }
    case 'kayit.ekle': {
      const uid = typeof op.uid === 'string' && UID_RX.test(op.uid) ? op.uid : '';
      const title = yazi(veri.title, 300);
      if (!uid || !title) return { hata: 'kayıt için uid ve başlık gerekli' };
      const ozet = {
        uid,
        title,
        author: yazi(veri.author, 120),
        source: yazi(veri.source, 120),
        sourceKey: KAYNAK_KEY_RX.test(String(veri.sourceKey || '')) ? veri.sourceKey : '',
        category: yazi(veri.category, 40),
        url: adres(veri.url),
        date: yazi(veri.date, 60),
        readTime: yazi(veri.readTime, 20),
        snippet: yazi(veri.snippet, 600),
        avatar: adres(veri.avatar),
        savedAt: zaman(veri.savedAt || op.t),
      };
      const komutlar = [['HSET', ANAHTAR.kayit, uid, JSON.stringify(ozet)]];
      if (typeof op.metin === 'string' && op.metin.trim()) {
        komutlar.push(['HSET', ANAHTAR.metin, uid, op.metin.slice(0, SINIR.metin)]);
      }
      return { alan: 'y', hash: 'kayit', komutlar };
    }
    case 'kayit.sil': {
      const uid = typeof op.uid === 'string' && UID_RX.test(op.uid) ? op.uid : '';
      if (!uid) return { hata: 'kayıt uid gerekli' };
      return { alan: 'y', komutlar: [['HDEL', ANAHTAR.kayit, uid], ['HDEL', ANAHTAR.metin, uid]] };
    }
    case 'okundu.ekle': {
      const uid = typeof op.uid === 'string' && UID_RX.test(op.uid) ? op.uid : '';
      if (!uid) return { hata: 'okundu uid gerekli' };
      return { alan: 'y', okundu: true, komutlar: [['ZADD', ANAHTAR.okundu, String(zaman(op.t)), uid]] };
    }
    case 'okundu.sil': {
      const uid = typeof op.uid === 'string' && UID_RX.test(op.uid) ? op.uid : '';
      if (!uid) return { hata: 'okundu uid gerekli' };
      return { alan: 'y', komutlar: [['ZREM', ANAHTAR.okundu, uid]] };
    }
    case 'okundu.temizle':
      return { alan: 'y', komutlar: [['DEL', ANAHTAR.okundu]] };
    case 'ayar.yaz': {
      const ad = typeof op.ad === 'string' ? op.ad : '';
      if (!Object.prototype.hasOwnProperty.call(AYARLAR, ad)) return { hata: `bilinmeyen ayar: ${ad || '?'}` };
      if (!AYARLAR[ad](op.deger)) return { hata: `geçersiz değer: ${ad}` };
      return { alan: 'y', komutlar: [['HSET', ANAHTAR.ayar, ad, JSON.stringify(op.deger)]] };
    }
    case 'gizli.ekle': {
      const a = anahtar(op.anahtar, 200);
      const tip = veri.tur === 'gazete' ? 'gazete' : veri.tur === 'yazar' ? 'yazar' : '';
      const ad = yazi(veri.ad, 120);
      if (!a || !/^[yg]:/.test(a) || !tip || !ad) return { hata: 'gizleme için anahtar (y:/g:), tür ve ad gerekli' };
      const kayit = { tur: tip, ad, kaynak: yazi(veri.kaynak, 120), t: zaman(op.t) };
      return { alan: 'y', hash: 'gizli', komutlar: [['HSET', ANAHTAR.gizli, a, JSON.stringify(kayit)]] };
    }
    case 'gizli.sil': {
      const a = anahtar(op.anahtar, 200);
      if (!a) return { hata: 'gizleme anahtarı gerekli' };
      return { alan: 'y', komutlar: [['HDEL', ANAHTAR.gizli, a]] };
    }
    case 'kaynak.pasif': {
      const a = anahtar(op.anahtar, 200);
      const tip = veri.tur === 'kaynak' ? 'kaynak' : veri.tur === 'yazar' ? 'yazar' : '';
      const ad = yazi(veri.ad, 120);
      if (!a || !tip || !ad) return { hata: 'pasife alma için anahtar, tür ve ad gerekli' };
      let key = '';
      if (tip === 'kaynak') {
        key = String(veri.key || a.replace(/^k:/, ''));
        if (a !== `k:${key}` || !KAYNAK_KEY_RX.test(key)) return { hata: 'kaynak anahtarı "k:<anahtar>" biçiminde olmalı' };
      } else if (!/^y:./.test(a)) {
        return { hata: 'yazar anahtarı "y:<ad>" biçiminde olmalı' };
      }
      const kayit = { tur: tip, ad, key, t: zaman(op.t) };
      if (tip === 'yazar') {
        // Pasif yazar (yazıları güncellenmez): gazete ve profil adresi eşleşmeye yardım eder
        kayit.kaynak = yazi(veri.kaynak, 120);
        kayit.url = adres(veri.url);
        delete kayit.key;
      }
      return { alan: 'k', hash: 'pasif', komutlar: [['HSET', ANAHTAR.pasif, a, JSON.stringify(kayit)]] };
    }
    case 'kaynak.aktif': {
      const a = anahtar(op.anahtar, 200);
      if (!a) return { hata: 'kaynak/yazar anahtarı gerekli' };
      return { alan: 'k', komutlar: [['HDEL', ANAHTAR.pasif, a]] };
    }
    case 'ek.ekle': {
      const feed = adres(veri.feed, { ozelEngelle: true });
      const name = yazi(veri.name, 80);
      if (!feed) return { hata: 'geçerli bir http(s) akış/site adresi gerekli' };
      if (!name) return { hata: 'kaynak adı gerekli' };
      const category = KATEGORILER.includes(veri.category) ? veri.category : 'Gündem';
      const key = akisAnahtari(feed);
      const kayit = { key, name, author: yazi(veri.author, 80) || name, category, feed, t: zaman(op.t) };
      return { alan: 'k', hash: 'ek', key, komutlar: [['HSET', ANAHTAR.ek, key, JSON.stringify(kayit)]] };
    }
    case 'ek.sil': {
      const key = typeof op.key === 'string' && /^ek-[0-9a-f]{8}$/.test(op.key) ? op.key : '';
      if (!key) return { hata: 'eklenen kaynak anahtarı (ek-xxxxxxxx) gerekli' };
      return { alan: 'k', komutlar: [['HDEL', ANAHTAR.ek, key], ['HDEL', ANAHTAR.pasif, `k:${key}`]] };
    }
    default:
      return { hata: `bilinmeyen işlem türü: ${tur || '?'}` };
  }
}

// ---------------------------------------------------------------------------
// Yanıt dönüştürücüler
// ---------------------------------------------------------------------------
function hashListesi(duz, anahtarAdi = 'anahtar') {
  const out = [];
  if (!Array.isArray(duz)) return out;
  for (let i = 0; i + 1 < duz.length; i += 2) {
    try {
      const v = JSON.parse(duz[i + 1]);
      if (v && typeof v === 'object') out.push({ [anahtarAdi]: duz[i], ...v });
    } catch (e) { /* bozuk kayıt atlanır */ }
  }
  return out;
}

function ayarNesnesi(duz) {
  const out = {};
  if (!Array.isArray(duz)) return out;
  for (let i = 0; i + 1 < duz.length; i += 2) {
    try {
      const v = JSON.parse(duz[i + 1]);
      if (AYARLAR[duz[i]] && AYARLAR[duz[i]](v)) out[duz[i]] = v;
    } catch (e) { /* atla */ }
  }
  return out;
}

function kaynakKurallari(pasifDuz, ekDuz, surum, guncellendi) {
  const pasif = hashListesi(pasifDuz);
  const ek = hashListesi(ekDuz, 'key').map(e => ({
    key: e.key, name: e.name, author: e.author, category: e.category, feed: e.feed, t: e.t,
  }));
  return {
    surum: Number(surum || 0),
    guncellendi: guncellendi || null,
    pasif: {
      kaynaklar: pasif.filter(p => p.tur === 'kaynak').map(p => ({ key: p.key, ad: p.ad, t: p.t })),
      yazarlar: pasif.filter(p => p.tur === 'yazar').map(p => ({ anahtar: p.anahtar, ad: p.ad, kaynak: p.kaynak || '', url: p.url || '', t: p.t })),
    },
    ek: ek.sort((a, b) => (a.t || 0) - (b.t || 0)),
  };
}

// ---------------------------------------------------------------------------
// İşleyiciler
// ---------------------------------------------------------------------------
async function saglik(req, ayar) {
  return {
    ok: ayar.eksik.length === 0,
    kurulum: { redis: Boolean(ayar.redis), sifre: Boolean(ayar.sifre) },
    eksik: ayar.eksik,
  };
}

async function kaynaklar(req, ayar) {
  const [pasif, ek, surum, guncellendi] = await hatAkisi(ayar.redis, [
    ['HGETALL', ANAHTAR.pasif], ['HGETALL', ANAHTAR.ek], ['GET', ANAHTAR.kSurum], ['GET', ANAHTAR.kZaman],
  ]);
  return { ok: true, ...kaynakKurallari(pasif, ek, surum, guncellendi) };
}

function istemciIp(req) {
  const h = req.headers || {};
  const ileri = String(h['x-forwarded-for'] || '').split(',')[0].trim();
  return ileri || String(h['x-real-ip'] || '') || (req.socket && req.socket.remoteAddress) || 'bilinmiyor';
}

async function giris(req, ayar, govde) {
  const sifre = typeof govde.sifre === 'string' ? govde.sifre : '';
  if (!sifre || sifre.length > 512) throw new ApiHatasi(400, 'gecersiz', 'Şifre gerekli.');
  const ipAnahtari = `${ANAHTAR.giris}ip:${crypto.createHash('sha256').update(istemciIp(req)).digest('hex').slice(0, 16)}`;
  const genelAnahtar = `${ANAHTAR.giris}genel`;
  const p = String(GIRIS_PENCERE_SN);
  const [, ipSayi, , genelSayi, ipTtl] = await hatAkisi(ayar.redis, [
    ['SET', ipAnahtari, '0', 'EX', p, 'NX'], ['INCR', ipAnahtari],
    ['SET', genelAnahtar, '0', 'EX', p, 'NX'], ['INCR', genelAnahtar],
    ['TTL', ipAnahtari],
  ]);
  if (Number(ipSayi) > GIRIS_IP_SINIRI || Number(genelSayi) > GIRIS_GENEL_SINIR) {
    const dk = Math.max(1, Math.ceil(Number(ipTtl > 0 ? ipTtl : GIRIS_PENCERE_SN) / 60));
    throw new ApiHatasi(429, 'cok-deneme', `Çok fazla hatalı deneme — yaklaşık ${dk} dakika sonra yeniden deneyin.`);
  }
  if (!sifreDogru(sifre, ayar.sifre)) {
    const kalan = Math.max(0, GIRIS_IP_SINIRI - Number(ipSayi));
    throw new ApiHatasi(401, 'sifre', `Şifre yanlış.${kalan <= 3 ? ` (${kalan} deneme hakkı kaldı)` : ''}`);
  }
  const [, nesil] = await hatAkisi(ayar.redis, [['DEL', ipAnahtari], ['GET', ANAHTAR.nesil]]);
  return { ok: true, ...tokenUret(ayar, nesil) };
}

async function durum(req, ayar) {
  await yetkiDenetle(req, ayar);
  const [fav, kayit, okundu, ayarDuz, gizli, ySurum, pasif, ek, kSurum, kZaman] = await hatAkisi(ayar.redis, [
    ['HGETALL', ANAHTAR.fav],
    ['HGETALL', ANAHTAR.kayit],
    ['ZRANGE', ANAHTAR.okundu, '0', '-1', 'WITHSCORES'],
    ['HGETALL', ANAHTAR.ayar],
    ['HGETALL', ANAHTAR.gizli],
    ['GET', ANAHTAR.ySurum],
    ['HGETALL', ANAHTAR.pasif],
    ['HGETALL', ANAHTAR.ek],
    ['GET', ANAHTAR.kSurum],
    ['GET', ANAHTAR.kZaman],
  ]);
  const okunanlar = [];
  if (Array.isArray(okundu)) {
    for (let i = 0; i + 1 < okundu.length; i += 2) okunanlar.push([okundu[i], Number(okundu[i + 1]) || 0]);
  }
  const kaynak = kaynakKurallari(pasif, ek, kSurum, kZaman);
  return {
    ok: true,
    surum: { y: Number(ySurum || 0), k: kaynak.surum },
    sunucuZamani: new Date().toISOString(),
    kisisel: {
      fav: hashListesi(fav).sort((a, b) => (a.t || 0) - (b.t || 0)),
      kayit: hashListesi(kayit, 'uid').sort((a, b) => (b.savedAt || 0) - (a.savedAt || 0)),
      okundu: okunanlar,
      ayar: ayarNesnesi(ayarDuz),
      gizli: hashListesi(gizli).sort((a, b) => (a.t || 0) - (b.t || 0)),
    },
    kaynak,
  };
}

async function surum(req, ayar) {
  await yetkiDenetle(req, ayar);
  const [y, k] = await hatAkisi(ayar.redis, [['GET', ANAHTAR.ySurum], ['GET', ANAHTAR.kSurum]]);
  return { ok: true, surum: { y: Number(y || 0), k: Number(k || 0) } };
}

async function uygula(req, ayar, govde) {
  await yetkiDenetle(req, ayar);
  const islemler = Array.isArray(govde.islemler) ? govde.islemler : null;
  if (!islemler) throw new ApiHatasi(400, 'gecersiz', '"islemler" dizisi gerekli.');
  if (islemler.length > SINIR.islem) throw new ApiHatasi(413, 'buyuk', `Tek istekte en çok ${SINIR.islem} işlem gönderilebilir.`);

  const cevrilen = islemler.map(islemiCevir);
  // Sınır denetimi: yalnızca ekleme yapılan HASH'lerin boyuna bakılır (tek istek)
  const sinirli = [...new Set(cevrilen.filter(c => c.hash).map(c => c.hash))];
  const boylar = {};
  if (sinirli.length) {
    const sonuc = await hatAkisi(ayar.redis, sinirli.map(h => ['HLEN', ANAHTAR[h]]));
    sinirli.forEach((h, i) => { boylar[h] = Number(sonuc[i] || 0); });
  }
  const komutlar = [];
  const reddedilen = [];
  let kisisel = false;
  let kaynak = false;
  let okunduVar = false;
  const eklenenler = [];
  cevrilen.forEach((c, sira) => {
    if (c.hata) { reddedilen.push({ sira, tur: islemler[sira] && islemler[sira].tur, neden: c.hata }); return; }
    if (c.hash && boylar[c.hash] >= SINIR[c.hash]) {
      reddedilen.push({ sira, tur: islemler[sira].tur, neden: `sınır doldu (en çok ${SINIR[c.hash]})` });
      return;
    }
    if (c.hash) boylar[c.hash] += 1;
    komutlar.push(...c.komutlar);
    if (c.alan === 'k') kaynak = true; else kisisel = true;
    if (c.okundu) okunduVar = true;
    if (c.key) eklenenler.push({ sira, key: c.key });
  });
  if (okunduVar) komutlar.push(['ZREMRANGEBYRANK', ANAHTAR.okundu, '0', String(-(SINIR.okundu + 1))]);
  if (kisisel) komutlar.push(['INCR', ANAHTAR.ySurum]);
  if (kaynak) komutlar.push(['INCR', ANAHTAR.kSurum], ['SET', ANAHTAR.kZaman, new Date().toISOString()]);
  komutlar.push(['GET', ANAHTAR.ySurum], ['GET', ANAHTAR.kSurum]);
  const sonuc = await islemBlogu(ayar.redis, komutlar);
  const k = sonuc[sonuc.length - 1];
  const y = sonuc[sonuc.length - 2];
  return {
    ok: true,
    uygulanan: islemler.length - reddedilen.length,
    reddedilen,
    eklenenler,
    surum: { y: Number(y || 0), k: Number(k || 0) },
  };
}

async function metinGetir(req, ayar, govde, sorgu) {
  await yetkiDenetle(req, ayar);
  const uid = String(sorgu.get('uid') || '');
  if (!UID_RX.test(uid)) throw new ApiHatasi(400, 'gecersiz', 'Geçerli bir uid gerekli.');
  const [html] = await hatAkisi(ayar.redis, [['HGET', ANAHTAR.metin, uid]]);
  return { ok: true, uid, metin: typeof html === 'string' ? html : '' };
}

async function cikis(req, ayar, govde) {
  await yetkiDenetle(req, ayar);
  if (govde && govde.hepsi === true) {
    await hatAkisi(ayar.redis, [['INCR', ANAHTAR.nesil]]);
    return { ok: true, hepsi: true };
  }
  return { ok: true, hepsi: false };
}

const ROTALAR = {
  saglik: { yontem: 'GET', fn: saglik, kurulumGerekmez: true },
  kaynaklar: { yontem: 'GET', fn: kaynaklar, sifreGerekmez: true },
  giris: { yontem: 'POST', fn: giris },
  durum: { yontem: 'GET', fn: durum },
  surum: { yontem: 'GET', fn: surum },
  uygula: { yontem: 'POST', fn: uygula },
  metin: { yontem: 'GET', fn: metinGetir },
  cikis: { yontem: 'POST', fn: cikis },
};

// ---------------------------------------------------------------------------
// HTTP katmanı (Vercel Node.js imzası: (req, res); düz Node http ile de çalışır)
// ---------------------------------------------------------------------------
function gonder(res, durumKodu, nesne) {
  res.statusCode = durumKodu;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.end(JSON.stringify(nesne));
}

async function govdeOku(req) {
  const uzunluk = Number((req.headers && req.headers['content-length']) || 0);
  if (uzunluk > SINIR.govde) throw new ApiHatasi(413, 'buyuk', 'İstek gövdesi çok büyük.');
  let govde;
  try {
    govde = req.body; // Vercel yardımcıları JSON gövdeyi önceden çözer
  } catch (e) {
    throw new ApiHatasi(400, 'gecersiz', 'İstek gövdesi geçerli JSON değil.');
  }
  if (govde === null) return {};
  if (govde === undefined) {
    govde = await new Promise((resolve, reject) => {
      let ham = '';
      let boy = 0;
      req.on('data', (parca) => {
        boy += parca.length;
        if (boy > SINIR.govde) { reject(new ApiHatasi(413, 'buyuk', 'İstek gövdesi çok büyük.')); req.destroy(); return; }
        ham += parca;
      });
      req.on('end', () => resolve(ham));
      req.on('error', reject);
    });
  }
  if (Buffer.isBuffer(govde)) govde = govde.toString('utf8');
  if (typeof govde === 'string') {
    if (govde.length > SINIR.govde) throw new ApiHatasi(413, 'buyuk', 'İstek gövdesi çok büyük.');
    if (!govde.trim()) return {};
    try { govde = JSON.parse(govde); } catch (e) { throw new ApiHatasi(400, 'gecersiz', 'İstek gövdesi geçerli JSON değil.'); }
  }
  return govde && typeof govde === 'object' && !Array.isArray(govde) ? govde : {};
}

async function handler(req, res) {
  try {
    const sorgu = new URL(req.url || '/', 'http://yerel').searchParams;
    const islem = String((req.query && req.query.islem) || sorgu.get('islem') || '');
    const rota = Object.prototype.hasOwnProperty.call(ROTALAR, islem) ? ROTALAR[islem] : null;
    if (!rota) throw new ApiHatasi(404, 'bilinmeyen', `Bilinmeyen işlem: ${islem || '(boş)'}`);
    if (req.method === 'OPTIONS') { res.statusCode = 204; res.setHeader('Allow', `${rota.yontem}, OPTIONS`); res.end(); return; }
    if (req.method !== rota.yontem && !(rota.yontem === 'GET' && req.method === 'HEAD')) {
      res.setHeader('Allow', `${rota.yontem}, OPTIONS`);
      throw new ApiHatasi(405, 'yontem', `Bu işlem için ${rota.yontem} kullanın.`);
    }
    const ayar = kurulum();
    if (!rota.kurulumGerekmez) {
      const eksik = rota.sifreGerekmez ? (ayar.redis ? [] : ayar.eksik.filter(e => e.startsWith('Upstash'))) : ayar.eksik;
      if (eksik.length) {
        throw new ApiHatasi(503, 'kurulum', `Sunucu kurulumu eksik: ${eksik.join('; ')}.`, { eksik });
      }
    }
    const govde = rota.yontem === 'POST' ? await govdeOku(req) : {};
    const sonuc = await rota.fn(req, ayar, govde, sorgu);
    gonder(res, 200, sonuc);
  } catch (e) {
    if (e instanceof ApiHatasi) {
      gonder(res, e.durum, { ok: false, kod: e.kod, hata: e.message, ...(e.ek || {}) });
      return;
    }
    console.error('[yonetim] beklenmeyen hata:', e);
    gonder(res, 500, { ok: false, kod: 'sunucu', hata: 'Beklenmeyen sunucu hatası.' });
  }
}

module.exports = handler;
// Testler için iç yardımcılar (Vercel yalnızca varsayılan dışa aktarımı kullanır)
module.exports._ic = { islemiCevir, tokenUret, tokenCoz, sifreDogru, ozelAdresMi, akisAnahtari, kurulum, ANAHTAR, SINIR };
