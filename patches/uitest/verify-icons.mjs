// lucide simge denetimi: sayfadaki tüm data-lucide adları gerçek pakette var mı?
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { JSDOM } from '/tmp/uitest/node_modules/jsdom/lib/api.js';

const require = createRequire('/tmp/uitest/');
const lucide = require('lucide');
const html = readFileSync('/home/user/kose/index.html', 'utf8');

// JS şablonlarındaki dinamik adlar (data-lucide="${row.icon}") denetim dışıdır:
// bunlar zaten lucide paketinden gelen simge adlarıdır.
const names = [...new Set([...html.matchAll(/data-lucide="([^"]+)"/g)].map(m => m[1]))]
  .filter(n => !n.includes('${'))
  .sort();
const have = new Set(Object.keys(lucide.icons).map(n => n.toLowerCase()));
const missing = names.filter(n => !have.has(n.replace(/-/g, '')));

console.log('lucide sürümü:', require('lucide/package.json').version);
console.log('sayfadaki farklı simge adı:', names.length);
console.log('eksik simge:', missing.length ? missing.join(', ') : 'yok');

const dom = new JSDOM(html, { url: 'http://localhost/' });
globalThis.document = dom.window.document;
lucide.createIcons({ icons: lucide.icons, nameAttr: 'data-lucide' });
const doc = dom.window.document;
console.log('oluşan <svg>:', doc.querySelectorAll('svg.lucide').length, '| boş kalan <i>:', doc.querySelectorAll('i[data-lucide]').length);
console.log('nav simgeleri:', [...doc.querySelectorAll('.nav-btn svg')].map(s => [...s.classList].find(c => c.startsWith('lucide-'))).join(', '));
console.log('okuyucu ses simgesi:', doc.getElementById('mini-play-icon') ? 'mini-play-icon var' : 'YOK');
