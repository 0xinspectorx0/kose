#!/usr/bin/env node
'use strict';
/**
 * Yerel deneme sunucusu: uygulamayı (index.html + data/) sunar, /api/yonetim
 * isteklerini Vercel'deki fonksiyonun KENDİSİYLE (api/yonetim.js) karşılar ve
 * Upstash REST API'sinin bellekte çalışan bir taklidini /__upstash altında açar.
 *
 *   node patches/uitest/yonetim-yerel-sunucu.cjs --port 8080 --sifre deneme1234
 *
 * Testler `baslat()` ile içe aktarır. Upstash taklidi yalnızca uygulamanın
 * kullandığı komutları bilir (GET/SET/INCR/DEL/TTL, HSET/HDEL/HGET/HGETALL/HLEN,
 * ZADD/ZREM/ZRANGE/ZREMRANGEBYRANK); /pipeline ve /multi-exec uçları gerçek
 * servisle aynı biçimde yanıt verir.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const KOK = path.resolve(__dirname, '..', '..');
const TURLER = {
  '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};

// ---------------------------------------------------------------------------
// Upstash taklidi (bellek içi mini Redis)
// ---------------------------------------------------------------------------
function sahteRedis() {
  const veri = new Map(); // anahtar -> { tip, deger, bitis }
  const gunluk = [];      // çalıştırılan komutlar (testler için)
  let arizali = false;

  function al(k, tip) {
    const kayit = veri.get(k);
    if (!kayit) return null;
    if (kayit.bitis && kayit.bitis <= Date.now()) { veri.delete(k); return null; }
    if (tip && kayit.tip !== tip) throw new Error('WRONGTYPE Operation against a key holding the wrong kind of value');
    return kayit;
  }
  const sayi = v => {
    const n = Number(v);
    if (!Number.isFinite(n)) throw new Error('ERR value is not an integer or out of range');
    return n;
  };
  function zsirala(m) {
    return [...m.entries()].sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  }
  function aralik(uzunluk, bas, son) {
    let b = Number(bas); let s = Number(son);
    if (b < 0) b = Math.max(0, uzunluk + b);
    if (s < 0) s = uzunluk + s;
    s = Math.min(s, uzunluk - 1);
    return [b, s];
  }

  function calistir(komut) {
    if (!Array.isArray(komut) || !komut.length) throw new Error('ERR empty command');
    const [adHam, ...a] = komut.map(x => (typeof x === 'number' ? String(x) : x));
    const ad = String(adHam).toUpperCase();
    gunluk.push([ad, ...a]);
    switch (ad) {
      case 'GET': { const k = al(a[0], 'string'); return k ? k.deger : null; }
      case 'SET': {
        const [k, v, ...ops] = a;
        let ex = null; let nx = false;
        for (let i = 0; i < ops.length; i++) {
          const o = String(ops[i]).toUpperCase();
          if (o === 'EX') ex = sayi(ops[++i]);
          else if (o === 'NX') nx = true;
        }
        if (nx && al(k)) return null;
        veri.set(k, { tip: 'string', deger: String(v), bitis: ex ? Date.now() + ex * 1000 : 0 });
        return 'OK';
      }
      case 'INCR': {
        const k = al(a[0], 'string');
        const n = (k ? sayi(k.deger) : 0) + 1;
        veri.set(a[0], { tip: 'string', deger: String(n), bitis: k ? k.bitis : 0 });
        return n;
      }
      case 'DEL': { let n = 0; a.forEach((k) => { if (al(k)) { veri.delete(k); n++; } }); return n; }
      case 'TTL': {
        const k = al(a[0]);
        if (!k) return -2;
        return k.bitis ? Math.max(0, Math.ceil((k.bitis - Date.now()) / 1000)) : -1;
      }
      case 'HSET': {
        let k = al(a[0], 'hash');
        if (!k) { k = { tip: 'hash', deger: new Map(), bitis: 0 }; veri.set(a[0], k); }
        let yeni = 0;
        for (let i = 1; i + 1 < a.length; i += 2) { if (!k.deger.has(a[i])) yeni++; k.deger.set(a[i], String(a[i + 1])); }
        return yeni;
      }
      case 'HDEL': {
        const k = al(a[0], 'hash');
        if (!k) return 0;
        let n = 0; a.slice(1).forEach((f) => { if (k.deger.delete(f)) n++; });
        if (!k.deger.size) veri.delete(a[0]);
        return n;
      }
      case 'HGET': { const k = al(a[0], 'hash'); return k && k.deger.has(a[1]) ? k.deger.get(a[1]) : null; }
      case 'HGETALL': { const k = al(a[0], 'hash'); return k ? [...k.deger.entries()].flat() : []; }
      case 'HLEN': { const k = al(a[0], 'hash'); return k ? k.deger.size : 0; }
      case 'ZADD': {
        let k = al(a[0], 'zset');
        if (!k) { k = { tip: 'zset', deger: new Map(), bitis: 0 }; veri.set(a[0], k); }
        let yeni = 0;
        for (let i = 1; i + 1 < a.length; i += 2) { if (!k.deger.has(a[i + 1])) yeni++; k.deger.set(a[i + 1], sayi(a[i])); }
        return yeni;
      }
      case 'ZREM': {
        const k = al(a[0], 'zset');
        if (!k) return 0;
        let n = 0; a.slice(1).forEach((m) => { if (k.deger.delete(m)) n++; });
        if (!k.deger.size) veri.delete(a[0]);
        return n;
      }
      case 'ZRANGE': {
        const k = al(a[0], 'zset');
        if (!k) return [];
        const liste = zsirala(k.deger);
        const [b, s] = aralik(liste.length, a[1], a[2]);
        const dilim = b > s ? [] : liste.slice(b, s + 1);
        const skorlu = a.slice(3).some(x => String(x).toUpperCase() === 'WITHSCORES');
        return skorlu ? dilim.flatMap(([m, p]) => [m, String(p)]) : dilim.map(([m]) => m);
      }
      case 'ZREMRANGEBYRANK': {
        const k = al(a[0], 'zset');
        if (!k) return 0;
        const liste = zsirala(k.deger);
        const [b, s] = aralik(liste.length, a[1], a[2]);
        if (b > s) return 0;
        const silinecek = liste.slice(b, s + 1);
        silinecek.forEach(([m]) => k.deger.delete(m));
        if (!k.deger.size) veri.delete(a[0]);
        return silinecek.length;
      }
      case 'ZCARD': { const k = al(a[0], 'zset'); return k ? k.deger.size : 0; }
      case 'FLUSHALL': veri.clear(); return 'OK';
      default: throw new Error(`ERR unknown command '${ad}'`);
    }
  }

  function istek(yol, govde) {
    if (arizali) return { durum: 500, nesne: { error: 'sahte arıza' } };
    if (yol === '/pipeline' || yol === '/multi-exec') {
      if (!Array.isArray(govde)) return { durum: 400, nesne: { error: 'ERR expected array of commands' } };
      return {
        durum: 200,
        nesne: govde.map((k) => {
          try { return { result: calistir(k) }; } catch (e) { return { error: e.message }; }
        }),
      };
    }
    if (yol === '' || yol === '/') {
      try { return { durum: 200, nesne: { result: calistir(govde) } }; } catch (e) { return { durum: 400, nesne: { error: e.message } }; }
    }
    return { durum: 404, nesne: { error: 'bilinmeyen uç' } };
  }

  return {
    veri, gunluk, istek, calistir,
    arizaAyarla(v) { arizali = Boolean(v); },
    temizle() { veri.clear(); gunluk.length = 0; },
  };
}

// ---------------------------------------------------------------------------
// HTTP sunucusu
// ---------------------------------------------------------------------------
function govdeTopla(req) {
  return new Promise((resolve, reject) => {
    const parcalar = [];
    req.on('data', c => parcalar.push(c));
    req.on('end', () => resolve(Buffer.concat(parcalar).toString('utf8')));
    req.on('error', reject);
  });
}

function baslat({ port = 0, host = '127.0.0.1', sifre = 'deneme1234', redisVar = true, redisToken } = {}) {
  const redis = sahteRedis();
  const token = redisToken || crypto.randomBytes(12).toString('hex');
  const handler = require(path.join(KOK, 'api', 'yonetim.js'));
  let gecikmeMs = 0;

  const sunucu = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://yerel');
    try {
      if (url.pathname.startsWith('/__upstash')) {
        if (String(req.headers.authorization || '') !== `Bearer ${token}`) {
          res.writeHead(401, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Unauthorized' }));
          return;
        }
        const ham = await govdeTopla(req);
        let govde = null;
        try { govde = JSON.parse(ham || 'null'); } catch (e) { govde = null; }
        const { durum, nesne } = redis.istek(url.pathname.slice('/__upstash'.length), govde);
        res.writeHead(durum, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(nesne));
        return;
      }
      if (url.pathname === '/api/yonetim' || url.pathname === '/api/yonetim/') {
        if (gecikmeMs) await new Promise(r => setTimeout(r, gecikmeMs));
        // Vercel yardımcılarının taklidi: req.query ve JSON req.body
        req.query = Object.fromEntries(url.searchParams.entries());
        if (req.method === 'POST') {
          const ham = await govdeTopla(req);
          const tip = String(req.headers['content-type'] || '');
          if (!ham) req.body = null;
          else if (tip.includes('application/json')) {
            try { req.body = JSON.parse(ham); } catch (e) { req.body = ham; }
          } else req.body = ham;
        }
        await handler(req, res);
        return;
      }
      // Statik dosyalar (depo kökü)
      let yol = decodeURIComponent(url.pathname);
      if (yol.endsWith('/')) yol += 'index.html';
      const tam = path.normalize(path.join(KOK, yol));
      if (!tam.startsWith(KOK) || tam.includes(`${path.sep}.git`)) { res.writeHead(403); res.end(); return; }
      fs.readFile(tam, (err, icerik) => {
        if (err) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('bulunamadı'); return; }
        res.writeHead(200, { 'Content-Type': TURLER[path.extname(tam)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
        res.end(icerik);
      });
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(String(e && e.stack || e));
    }
  });

  return new Promise((resolve) => {
    sunucu.listen(port, host, () => {
      const gercekPort = sunucu.address().port;
      const taban = `http://127.0.0.1:${gercekPort}`;
      if (redisVar) {
        process.env.KV_REST_API_URL = `${taban}/__upstash`;
        process.env.KV_REST_API_TOKEN = token;
      } else {
        delete process.env.KV_REST_API_URL;
        delete process.env.KV_REST_API_TOKEN;
      }
      delete process.env.UPSTASH_REDIS_REST_URL;
      delete process.env.UPSTASH_REDIS_REST_TOKEN;
      if (sifre) process.env.ADMIN_PASSWORD = sifre; else delete process.env.ADMIN_PASSWORD;
      resolve({
        taban,
        port: gercekPort,
        redis,
        gecikme(ms) { gecikmeMs = ms; },
        kapat: () => new Promise(r => sunucu.close(() => r())),
      });
    });
  });
}

module.exports = { baslat, sahteRedis };

if (require.main === module) {
  const arg = (ad, vars) => {
    const i = process.argv.indexOf(ad);
    return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : vars;
  };
  baslat({ port: Number(arg('--port', 8080)), host: arg('--host', '0.0.0.0'), sifre: arg('--sifre', 'deneme1234') })
    .then(({ port }) => {
      console.log(`Mürekkep yerel sunucu: http://0.0.0.0:${port}/  (yönetici şifresi: ${arg('--sifre', 'deneme1234')})`);
      console.log('Upstash taklidi bellekte — sunucu kapanınca veriler silinir.');
    });
}
