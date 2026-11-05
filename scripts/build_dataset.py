"""Build site/words.json from a kaikki.org Wiktionary Tamil extract (CC BY-SA).
Usage: python3 -I build_dataset.py <tamil.jsonl> <out.json>
Each entry: [tamil, romanization, pos, [english glosses]]
"""
import json, sys

src, out = sys.argv[1], sys.argv[2]
merged = {}
with open(src, encoding="utf-8") as f:
    for line in f:
        e = json.loads(line)
        word = e.get("word")
        if not word:
            continue
        glosses = []
        for s in e.get("senses", []):
            tags = set(s.get("tags", []))
            if "form-of" in tags or "alt-of" in tags:
                continue
            for g in s.get("glosses", [])[:1]:
                g = g.strip()
                if g and len(g) <= 120 and g not in glosses:
                    glosses.append(g)
        if not glosses:
            continue
        roman = next((x["form"] for x in e.get("forms", []) if "romanization" in x.get("tags", [])), "")
        key = (word, e.get("pos", ""))
        if key in merged:
            for g in glosses:
                if g not in merged[key][3]:
                    merged[key][3].append(g)
        else:
            merged[key] = [word, roman, e.get("pos", ""), glosses[:6]]

rows = sorted(merged.values(), key=lambda r: r[0])
with open(out, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
print(len(rows), "entries")
