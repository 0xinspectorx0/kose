#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GEÇİCİ TEŞHİS: fotoğrafı/yazarı bulunamayan gazetelerin makale sayfalarındaki
<img> etiketlerini, JSON-LD bloklarını ve author meta'larını data/diag.json'a
döker. Amaç: extract_author_photo sezgilerini gerçek sayfa yapısına göre
ayarlamak. Teşhisten sonra bu dosya silinecek.
"""
import json
import sys

sys.path.insert(0, "scripts")
import fetch_columns as fc  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

PROBLEM = ["Sözcü", "Diken", "Posta", "Habertürk", "Sabah", "Takvim"]
PER_SOURCE = 2

daily = json.load(open("data/daily.json", encoding="utf-8"))
by_source = {}
for a in daily["articles"]:
    by_source.setdefault(a["source"], []).append(a)

out = {}
for src in PROBLEM:
    arts = by_source.get(src, [])
    # önce yazarı bulunamayanlar, sonra fotoğrafı olmayanlar
    arts = sorted(arts, key=lambda a: (a["author"] != "Köşe Yazarı", bool(a.get("photo"))))
    for a in arts[:PER_SOURCE]:
        html = fc.fetch(a["url"])
        if not html:
            out[f"{src} :: {a['title'][:40]}"] = {"url": a["url"], "error": "fetch boş"}
            continue
        soup = BeautifulSoup(html, "html.parser")
        info = {
            "url": a["url"],
            "author_in_data": a["author"],
            "title": a["title"][:60],
            "jsonld": [
                (t.string or t.get_text() or "")[:900]
                for t in soup.find_all("script", attrs={"type": "application/ld+json"})
            ][:2],
            "meta_author": [
                [m.get("name") or m.get("property"), (m.get("content") or "")[:70]]
                for m in soup.find_all("meta")
                if (m.get("name") or m.get("property") or "").lower()
                in ("author", "article:author", "dc.creator", "parsely-author")
            ],
            "imgs": [],
        }
        for img in soup.find_all("img")[:40]:
            parent = img.find_parent()
            pcls = " ".join(parent.get("class") or []) if parent is not None and parent.get else ""
            info["imgs"].append({
                "src": (img.get("src") or img.get("data-src") or "")[:130],
                "alt": (img.get("alt") or "")[:50],
                "cls": " ".join(img.get("class") or [])[:50],
                "w": img.get("width"),
                "h": img.get("height"),
                "pcls": pcls[:50],
                "pid": (parent.get("id") if parent is not None and parent.get else "") or "",
            })
        out[f"{src} :: {a['title'][:40]}"] = info
        print(f"teşhis: {src} | {a['title'][:45]} | {len(info['imgs'])} img")

with open("data/diag.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("OK -> data/diag.json")
