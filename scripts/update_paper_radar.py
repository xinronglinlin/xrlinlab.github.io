#!/usr/bin/env python3
import html
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUTPUT = Path("assets/data/paper-radar.json")
WINDOW_DAYS = 30
JOURNALS = {
    "Science": ["0036-8075", "1095-9203"],
    "Nature": ["0028-0836", "1476-4687"],
    "Nature Materials": ["1476-1122", "1476-4660"],
    "Nature Chemistry": ["1755-4330", "1755-4349"],
    "Nature Energy": ["2058-7546"],
    "Nature Nanotechnology": ["1748-3387", "1748-3395"],
    "Joule": ["2542-4351"],
    "Chem": ["2451-9294"],
    "Journal of the American Chemical Society": ["0002-7863", "1520-5126"],
    "Angewandte Chemie International Edition": ["1433-7851", "1521-3773"],
    "Macromolecules": ["0024-9297", "1520-5835"],
    "Nature Sustainability": ["2398-9629"],
}
TOPICS = {
    "Ion-conducting polymers and single-ion conductors": [r"ion[- ]conducting polymer", r"single[- ]ion", r"polymer ion conductor", r"polyelectrolyte", r"\bionomer"],
    "Solid-state batteries": [r"solid[- ]state batter", r"solid electrolytes?", r"all[- ]solid[- ]state"],
    "Lithium-metal and anode-free batteries": [r"lithium[- ]metal", r"\bli metal\b", r"anode[- ]free", r"lithium deposition", r"lithium plating"],
    "Fast charging and interfacial ion transport": [r"fast[- ]charg", r"extreme fast charg", r"high[- ]rate charg", r"interfacial ion transport", r"charge[- ]transfer", r"interphase", r"sand['’]s time"],
}

def clean(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def date_parts(item, key):
    parts = ((item.get(key) or {}).get("date-parts") or [[]])[0]
    if len(parts) < 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (TypeError, ValueError):
        return None

def publication_date(item):
    for key in ("published-online", "published-print", "published", "issued"):
        value = date_parts(item, key)
        if value:
            return value
    return None

def authors(item):
    names = []
    for author in item.get("author") or []:
        name = " ".join(part for part in (author.get("given", "").strip(), author.get("family", "").strip()) if part)
        if name:
            names.append(name)
    return ", ".join(names)

def fetch_issn(issn, start, end):
    params = {
        "filter": f"from-online-pub-date:{start},until-online-pub-date:{end},issn:{issn},type:journal-article",
        "rows": "1000",
        "select": "DOI,title,author,container-title,published-online,published-print,published,issued,URL,abstract,ISSN",
        "mailto": "xinronglinlin@gmail.com",
    }
    url = "https://api.crossref.org/works?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "MolEnergy-Paper-Radar/1.0 (mailto:xinronglinlin@gmail.com)", "Accept": "application/json"})
    with urlopen(request, timeout=45) as response:
        return json.load(response).get("message", {}).get("items", [])

def matched_topics(item):
    title = clean((item.get("title") or [""])[0])
    abstract = clean(item.get("abstract"))
    corpus = (title + " " + abstract).lower()
    return [topic for topic, patterns in TOPICS.items() if any(re.search(pattern, corpus, re.I) for pattern in patterns)]

def main():
    end = date.today()
    start = end - timedelta(days=WINDOW_DAYS - 1)
    existing = {}
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
            existing = {
                (paper.get("doi") or re.sub(r"[^a-z0-9]+", "", paper.get("title", "").lower())): paper
                for paper in previous.get("papers", []) if isinstance(paper, dict)
            }
        except (OSError, json.JSONDecodeError):
            existing = {}
    collected = {}
    errors = []
    for journal, issns in JOURNALS.items():
        journal_items = []
        for issn in issns:
            try:
                journal_items.extend(fetch_issn(issn, start.isoformat(), end.isoformat()))
                time.sleep(0.25)
            except Exception as exc:
                errors.append(f"{journal} ({issn}): {exc}")
        for item in journal_items:
            topics = matched_topics(item)
            pub_date = publication_date(item)
            title = clean((item.get("title") or [""])[0])
            if not topics or not pub_date or not title or not (start <= pub_date <= end):
                continue
            doi = clean(item.get("DOI")).lower()
            key = doi or re.sub(r"[^a-z0-9]+", "", title.lower())
            paper = {
                "title": title,
                "authors": authors(item),
                "journal": journal,
                "publicationDate": pub_date.isoformat(),
                "doi": doi,
                "link": f"https://doi.org/{doi}" if doi else clean(item.get("URL")),
                "abstract": clean(item.get("abstract")),
                "matchedTopics": topics,
            }
            old = existing.get(key, {})
            for field in ("summaryZh", "summarySource", "summaryGeneratedAt", "summaryPromptVersion"):
                if old.get(field):
                    paper[field] = old[field]
            collected[key] = paper
    papers = sorted(collected.values(), key=lambda p: (p["publicationDate"], p["title"]), reverse=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "windowDays": WINDOW_DAYS,
        "topics": list(TOPICS),
        "journals": list(JOURNALS),
        "papers": papers,
        "source": "Crossref",
        "errors": errors,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(papers)} papers; {len(errors)} source errors.")

if __name__ == "__main__":
    main()
