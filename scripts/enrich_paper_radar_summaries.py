#!/usr/bin/env python3
"""Generate GeoWater-style Chinese research guides for Paper Radar."""
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

OUTPUT = Path("assets/data/paper-radar.json")
PROMPT_VERSION = 1
ABSTRACT_LABELS = ("新在哪里", "有意思的现象", "怎么解释", "为什么重要")
TITLE_LABELS = ("研究什么", "为什么值得关注")

def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()

def prompt_for(paper, source):
    title, journal = clean(paper.get("title")), clean(paper.get("journal"))
    if source == "title-only":
        return f"""论文标题：{title}\n期刊：{journal}\n\n目前没有获取到可靠英文摘要，因此只能依据标题做非常保守的导读。\n请严格输出下面2行，每行25–60个中文字：\n研究什么：用自然、易懂但专业的中文说明标题明确指向的研究对象、问题或关系。\n为什么值得关注：只根据标题可以合理判断的学术背景说明这个问题为什么值得关注；无法可靠判断时写“仅凭标题无法进一步判断”。\n不得猜测具体数据、方法、机制或结论；不要输出序号、Markdown、开场白或额外说明。"""
    return f"""论文标题：{title}\n期刊：{journal}\n英文摘要：\n{clean(paper.get('abstract'))}\n\n请把论文整理成科研人员真正想快速知道的4个问题，而不是翻译摘要。严格输出下面4行，每行约30–80个中文字：\n新在哪里：相对于已有认知或常见做法，说明论文真正新增的科学认识、现象、尺度、方法、机制联系或验证。摘要未明确支持时如实说明。\n有意思的现象：提炼最反常、最有辨识度或最值得记住的结果；若无反常现象，就概括最核心发现。\n怎么解释：说明作者如何解释现象，或用什么关键证据把现象与机制联系起来。严格区分现象、相关性、机制与因果；摘要未解释时明确说明。\n为什么重要：具体说明该发现改变了对什么过程的理解，或怎样影响材料设计、模型、性能评价或器件应用，不能只写“具有重要意义”。\n\n要求：面向有机化学、高分子化学、电化学与电池研究者；专业但易懂；保留最有帮助的1–2个数字；不逐句翻译、不堆术语、不添加摘要没有的信息、不夸大结论；四点之间不重复；不要输出序号、Markdown、开场白或额外说明。"""

def validate(text, labels):
    lines = [clean(re.sub(r"^[\-•]\s*", "", line)) for line in text.splitlines() if clean(line)]
    found = {label for label in labels if any(re.match(rf"^{re.escape(label)}[？?]?\s*[：:]", line) for line in lines)}
    if len(found) != len(labels):
        raise ValueError("导读字段不完整")
    return "\n".join(lines)

def call_llm(paper, api_key, base_url, model):
    source = "crossref-abstract" if len(clean(paper.get("abstract"))) >= 100 else "title-only"
    system = "你是一名有机化学、高分子化学、电化学与电池领域的资深研究者兼学术编辑。提炼论文的新意、辨识度最高的现象、证据支持的解释及具体重要性。严格区分现象、相关性、机制与因果，不补充摘要没有的证据。"
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt_for(paper, source)}], "temperature": 0.2, "max_tokens": 700}
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    request = Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        if exc.code == 400 and "max_tokens" in detail:
            body["max_completion_tokens"] = body.pop("max_tokens")
            retry = Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urlopen(retry, timeout=90) as response:
                payload = json.load(response)
        else:
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    content = payload["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", clean(content), flags=re.I)
    # Restore line breaks that clean() removes by splitting at the required labels.
    labels = TITLE_LABELS if source == "title-only" else ABSTRACT_LABELS
    content = re.sub(rf"\s+(?=({'|'.join(labels)})[？?]?\s*[：:])", "\n", content)
    return validate(content, labels), source

def main():
    api_key = clean(os.getenv("PAPER_RADAR_LLM_API_KEY"))
    if not api_key:
        print("::warning::Chinese guides skipped: PAPER_RADAR_LLM_API_KEY/OPENAI_API_KEY is not configured.")
        return 0
    base_url = clean(os.getenv("PAPER_RADAR_LLM_BASE_URL")) or "https://api.openai.com/v1"
    model = clean(os.getenv("PAPER_RADAR_LLM_MODEL")) or "gpt-5-mini"
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    candidates = [p for p in data.get("papers", []) if not p.get("summaryZh") or int(p.get("summaryPromptVersion", 0)) < PROMPT_VERSION]
    candidates.sort(key=lambda p: (p.get("publicationDate", ""), p.get("title", "")), reverse=True)
    changed = 0
    for index, paper in enumerate(candidates[:120], 1):
        try:
            summary, source = call_llm(paper, api_key, base_url, model)
            paper.update(summaryZh=summary, summarySource=source, summaryGeneratedAt=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), summaryPromptVersion=PROMPT_VERSION)
            changed += 1
            print(f"[{index}/{min(len(candidates),120)}] generated: {paper.get('title','')[:80]}")
        except Exception as exc:
            print(f"::warning::Guide failed for {paper.get('doi') or paper.get('title')}: {exc}")
        time.sleep(0.8)
    if changed:
        data["summaryPipeline"] = {"mode": "question-led-four-point-guide", "promptVersion": PROMPT_VERSION, "generatedThisRun": changed}
        OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {changed} Chinese guides.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
