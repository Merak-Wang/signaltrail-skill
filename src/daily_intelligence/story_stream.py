"""Deterministic, accessible illustrated reading from exact script revisions."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from .narrative import script_context
from .narrative_contracts import VISUAL_SCHEMA, Admission, validate_schema
from .narrative_store import digest, file_ref, load_artifact, parent_path, save_artifact
from .narrative_verification import explainer_status
from .utils import write_text_atomic

LABELS = {
    "zh-CN": {
        "label": "中文",
        "section": "讲解与研判",
        "sources": "本段依据",
        "intro": "本期导读",
        "closing": "接下来，看什么",
        "contents": "阅读目录",
        "snapshot": "实验解读 · 依据已保存晨报",
        "draft": "实验草稿 · 尚未通过完整语义审核",
        "disclosure": "内容依据下方注明时间的已保存日报；尚未完成来源更新与更正链复核，"
        "请勿把历史快照解读为实时状态。图形为解释示意，不是新闻现场影像。",
        "as_of": "资料截止",
        "diagram": "解释示意",
        "parallel": "并列阅读 · 不表示因果",
        "sequence": "叙述顺序 · 不表示因果",
        "conditional": "条件关系 · 保留正文限定",
        "change": "变化",
        "background": "前情",
        "mechanism": "研判",
        "limit": "边界",
        "watch": "观察",
        "analysis": "条件研判",
        "original": "来源原文",
        "unknown": "发布时间未记录",
        "evidence": "展开证据与主张",
        "top": "返回目录",
        "partial": "所依据的晨报仍有未完成项。",
    },
    "en": {
        "label": "English",
        "section": "Explanation & analysis",
        "sources": "Sources",
        "intro": "The thread of this edition",
        "closing": "What to watch next",
        "contents": "Contents",
        "snapshot": "Experimental explainer · saved report snapshot",
        "draft": "Experimental draft · full semantic review pending",
        "disclosure": "This reading is based on the saved report at the cutoff below. Source "
        "updates and correction chains have not been rechecked. It does not establish "
        "the current state of events. Graphics are explanatory diagrams, not scene images.",
        "as_of": "Evidence cutoff",
        "diagram": "Explanatory diagram",
        "parallel": "Parallel ideas · no causal connection implied",
        "sequence": "Narrative order · not a causal chain",
        "conditional": "Conditional relationship · retain the qualifications in the text",
        "change": "Development",
        "background": "Context",
        "mechanism": "Analysis",
        "limit": "Boundary",
        "watch": "Watch point",
        "analysis": "Conditional analysis",
        "original": "Original source",
        "unknown": "Publication time not recorded",
        "evidence": "Explore evidence and claims",
        "top": "Back to contents",
        "partial": "The underlying report retains incomplete work.",
    },
}

CSS = """
:root{color-scheme:light;--ink:#20312f;--muted:#516661;--paper:#f4f3ec;--green:#15584e;
--gold:#b17b38;--line:#cad4cc;--white:#fffefa}*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:5rem}body{margin:0;background:var(--paper);
color:var(--ink);font:17px/1.85 'Segoe UI','Microsoft YaHei',sans-serif}
a{color:var(--green);text-underline-offset:4px;overflow-wrap:anywhere}button{font:inherit}
button,a{-webkit-tap-highlight-color:transparent}a:focus-visible,button:focus-visible,
summary:focus-visible{outline:3px solid var(--gold);outline-offset:4px}
.toolbar{position:sticky;top:0;z-index:2;background:#f4f3ecf5;border-bottom:1px solid var(--line);
display:flex;align-items:center;justify-content:space-between;padding:12px max(5vw,20px);gap:16px}
.brand{font-size:14px;font-weight:750;letter-spacing:.15em}.switch{display:flex;gap:8px}
.switch button{border:1px solid var(--green);border-radius:22px;padding:4px 17px;
background:transparent;color:var(--green);cursor:pointer}.switch button[aria-pressed=true]{
background:var(--green);color:white}main{max-width:1160px;margin:auto;padding:45px 28px 90px}
.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:var(--green)}
.hero{display:grid;grid-template-columns:1.7fr .8fr;gap:55px;align-items:center;margin:25px 0 32px}
h1{font-size:clamp(32px,4.4vw,57px);line-height:1.27;letter-spacing:-.035em;
margin:16px 0 24px;text-wrap:balance}
h2{font-size:clamp(25px,3vw,35px);line-height:1.45;margin:6px 0 15px}
.intro{font-size:19px;line-height:1.9}.hero-art{width:100%;height:auto;max-width:330px;justify-self:center}
.disclosure{border-left:3px solid var(--gold);padding:13px 19px;background:#ecebe0;font-size:13px;
line-height:1.8;color:#4d5149}.meta{font-size:12px;letter-spacing:.03em;margin-top:12px;color:var(--muted)}
.contents{display:flex;flex-wrap:wrap;gap:10px 25px;border-block:1px solid var(--line);
padding:22px 0;margin:30px 0 42px}.contents a{font-size:14px;text-decoration:none}
.chapter{background:var(--white);border:1px solid var(--line);border-radius:6px;margin:0 0 36px;
padding:38px 42px}.chapter-head{display:grid;grid-template-columns:54px 1fr;gap:14px;
border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:12px}
.chapter-number{font:45px/1.3 Georgia,serif;color:var(--gold)}.question{color:var(--muted);margin:0}
.beat{display:grid;grid-template-columns:94px minmax(0,1fr);gap:20px;padding:22px 0;
border-bottom:1px solid #e8ebe4}.beat:last-of-type{border-bottom:0}
.role{font-size:12px;color:var(--green);
font-weight:650;padding-top:7px;letter-spacing:.06em}.beat p{margin:0;white-space:pre-line}
.beat-body{min-width:0}.diagram{margin:24px 0 10px;background:#f0f4ef;border:1px solid #d2ded5;
border-radius:5px;padding:20px}
.diagram figcaption{font-size:11px;color:var(--muted);margin-bottom:15px}
.nodes{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;list-style:none;
padding:0;margin:0}.node{border-top:3px solid var(--green);padding:14px;background:var(--white);
font-size:14px;line-height:1.65}.node-index{font:18px Georgia,serif;color:var(--gold);display:block;
margin-bottom:8px}.sources{display:flex;flex-wrap:wrap;gap:7px 15px;font-size:11px;margin:14px 0 0}
.sources a{text-decoration-thickness:1px}details{font-size:12px;color:var(--muted);margin-top:18px}
summary{cursor:pointer}.claim{padding:8px 0;border-top:1px dotted var(--line)}
.claim code{font-size:10px}
.closing{padding:20px 8px;max-width:850px}.closing p{white-space:pre-line}.footer{font-size:12px;
color:var(--muted);border-top:1px solid var(--line);padding-top:24px;margin-top:28px}
[hidden]{display:none!important}@media(max-width:700px){body{font-size:16px;line-height:1.9}
.toolbar{padding:10px 16px}.brand{font-size:11px}.switch button{font-size:13px;padding:4px 12px}
main{padding:22px 18px 55px}.hero{grid-template-columns:1fr;gap:14px;margin-top:10px}
.hero-art{width:150px;display:none}h1{font-size:34px}.intro{font-size:17px}
.chapter{padding:24px 20px}.chapter-head{grid-template-columns:36px 1fr;gap:12px}
.chapter-number{font-size:31px}.beat{grid-template-columns:1fr;gap:5px;padding:20px 0}
.role{padding:0}.diagram{padding:15px}.nodes{grid-template-columns:1fr}.contents{gap:8px 16px}
.node{padding:12px}.disclosure{padding:12px 14px}}@media(prefers-reduced-motion:reduce){
html{scroll-behavior:auto}}@media print{.toolbar,.switch{display:none}main{max-width:none;padding:0}
.chapter{break-inside:avoid}.hero{grid-template-columns:1fr}.hero-art{display:none}}
"""

ART = """<svg class="hero-art" viewBox="0 0 320 300" aria-hidden="true" focusable="false">
<rect x="35" y="20" width="250" height="260" rx="125" fill="#e4e9df"/>
<path d="M65 205Q125 25 245 85M65 205Q200 230 245 85" fill="none" stroke="#b17b38"
stroke-width="2" stroke-dasharray="5 6"/><path d="M75 210L160 147L243 82" stroke="#15584e"
stroke-width="2"/><g fill="#fffefa" stroke="#15584e" stroke-width="2">
<rect x="48" y="184" width="58" height="48" rx="7"/><rect x="130" y="123" width="60"
height="48" rx="7"/><rect x="213" y="57" width="58" height="48" rx="7"/></g>
<g stroke="#15584e" stroke-width="2"><path d="M61 201h30m-30 12h23M144 139h31m-31 12h23
M226 73h31m-31 12h23"/></g><circle cx="238" cy="220" r="12" fill="#b17b38"/>
<circle cx="86" cy="85" r="5" fill="#15584e"/></svg>"""


def build_story_stream(
    script_paths: list[Path], data_dir: Path, *, bilingual_path: Path | None = None
) -> Path:
    """处理：原样编排语言脚本成顺序图文清单，不创作新标题或图注。
    输入：明确语言修订和可选双语回执；图仅使用脚本已登记的视觉文案。
    输出：带来源、文字替代和原创示意图来源说明的不可变 story manifest。
    """
    if not 1 <= len(script_paths) <= 2:
        raise ValueError("A story requires one or two language scripts")
    contexts = [script_context(p, data_dir) for p in script_paths]
    scripts = [c[0] for c in contexts]
    if len({s["parents"]["ledger"]["sha256"] for s in scripts}) != 1:
        raise ValueError("Story languages must share the exact ledger")
    languages = [s["payload"]["script"]["language"] for s in scripts]
    if len(languages) != len(set(languages)):
        raise ValueError("Duplicate story language")
    parents = {lang: path for lang, path in zip(languages, script_paths, strict=True)}
    status = Admission.DRAFT
    if bilingual_path:
        bilingual = load_artifact(bilingual_path, data_dir, kind="bilingual")
        dossier = load_artifact(parent_path(bilingual, "packet", data_dir), data_dir)
        reviewed = {
            load_artifact(parent_path(dossier, k, data_dir), data_dir)["parents"]["script"][
                "sha256"
            ]
            for k in ("zh_review", "en_review")
        }
        if reviewed != {file_ref(p, data_dir)["sha256"] for p in script_paths}:
            raise ValueError("Bilingual receipt belongs to other script revisions")
        status = bilingual["payload"]["status"]
        parents["bilingual"] = bilingual_path
    packet = contexts[0][2]["payload"]
    payload = {
        "languages": languages,
        "scripts": [s["payload"]["script"] for s in scripts],
        "claims": contexts[0][1]["payload"]["claims"],
        "evidence": packet["evidence"],
        "as_of": packet["as_of"],
        "timezone": packet["timezone"],
        "status": status,
        "current_admission": Admission.BLOCKED,
        "assets": {
            "type": "original_explanatory_diagrams",
            "external_images": [],
            "fallback": "complete_script_text",
            "rights": "original_shapes_and_layout",
            "semantic_source": "verbatim_script_visual_segments",
        },
        "metrics": [explainer_status(p, data_dir) for p in script_paths],
        "visual_review": "pending",
    }
    return save_artifact(
        data_dir, scripts[0]["session"], "story", payload, parents, render_story_markdown(payload)
    )


def _safe_url(value: str) -> str | None:
    """处理：拒绝证据链接中的可执行或本地 URL。
    输入：索引保存的未信任来源 URL。
    输出：可转义的 HTTP(S) 链接或空值，供读者安全跳转。
    """
    url = urlsplit(value)
    return value if url.scheme in {"http", "https"} and url.netloc and not url.username else None


def _sources(claim_ids: list[str], story: dict) -> list[dict]:
    """处理：将片段主张解析为去重的来源记录。
    输入：脚本登记的 claim IDs 与绑定清单。
    输出：原始证据顺序的来源，供链接和审计详情共同使用。
    """
    spans = {
        s for c in story["claims"] if c["claim_id"] in claim_ids for s in c["evidence_span_ids"]
    }
    return [e for e in story["evidence"] if any(s["span_id"] in spans for s in e["spans"])]


def _source_html(claim_ids: list[str], story: dict, labels: dict) -> str:
    """处理：生成带来源时间的安全链接，不扩展证据措辞。
    输入：片段主张、清单和界面语言。
    输出：可附在正文旁的来源链接 HTML。
    """
    links = []
    for evidence in _sources(claim_ids, story):
        url = _safe_url(evidence["url"])
        if url:
            timestamp = evidence["published_at"] or labels["unknown"]
            links.append(
                f'<a href="{escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer" title="{escape(timestamp, quote=True)}">'
                f"{escape(evidence['source_name'])}</a>"
            )
    return '<div class="sources">' + "".join(links) + "</div>" if links else ""


def _chapter_html(chapter: dict, story: dict, language: str, position: int) -> str:
    """处理：将一个章节的原样文字和视觉节点排成可访问图文卡。
    输入：脚本已登记的标题、问题、正文及图标签；程序只负责布局。
    输出：完整章节 HTML，图形隐藏或不可见时正文仍自足。
    """
    labels = LABELS[language]
    prefix = f"{language}-{chapter['chapter_id']}"
    parts = [
        f'<article class="chapter" id="{prefix}" data-card-id="{prefix}">',
        f'<header class="chapter-head"><span class="chapter-number">{position:02}</span><div>',
        f"<h2>{escape(chapter['title']['text'])}</h2>",
        f'<p class="question">{escape(chapter["question"]["text"])}</p></div></header>',
    ]
    for beat in chapter["beats"]:
        parts.extend(
            [
                f'<div class="beat"><div class="role">{labels[beat["role"]]}</div>',
                f'<div class="beat-body"><p>{escape(beat["text"])}</p>',
            ]
        )
        if beat["visual"]:
            parts.append(
                f'<figure class="diagram"><figcaption>{labels["diagram"]} · '
                f'{labels[beat["visual_relation"]]}</figcaption><ol class="nodes">'
            )
            for i, node in enumerate(beat["visual"], 1):
                parts.append(
                    f'<li class="node"><span class="node-index" aria-hidden="true">'
                    f"{i:02}</span>{escape(node['text'])}</li>"
                )
            parts.append("</ol></figure>")
        parts.append(_source_html(beat["claim_ids"], story, labels))
        parts.append("</div></div>")
    ids = {c for b in chapter["beats"] for c in b["claim_ids"]}
    parts.append(f"<details><summary>{labels['evidence']}</summary>")
    for claim in story["claims"]:
        if claim["claim_id"] in ids:
            # 双语账本允许审计区显示权威中文原文，明确 lang，避免当作英语正文。
            parts.append(
                f'<div class="claim" lang="zh-CN"><code>{claim["claim_id"]}</code> · '
                f"{escape(claim['text'])}</div>"
            )
    parts.append("</details></article>")
    return "".join(parts)


def render_story_html(story: dict) -> str:
    """处理：确定性渲染双语阅读页，所有新闻语义来自不可变清单。
    输入：已核对父闭包的清单；任何脚本、URL、正文都只作为数据转义。
    输出：无需外部字体、图片或脚本库的单文件 HTML，支持手机和语言切换。
    """
    languages = story["languages"]
    parts = [
        '<!doctype html><html lang="' + languages[0] + '"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<link rel="icon" href="data:,"><meta name="referrer" content="no-referrer">'
        "<title>SignalTrail · "
        + escape(story["scripts"][0]["title"]["text"])
        + "</title><style>"
        + CSS
        + "</style>",
        '</head><body><header class="toolbar"><span class="brand">SIGNALTRAIL / FIELDNOTES</span>',
        '<nav class="switch" aria-label="Language / 语言">',
    ]
    for i, lang in enumerate(languages):
        parts.append(
            f'<button type="button" data-language="{lang}" '
            f'aria-pressed="{"true" if i == 0 else "false"}">{LABELS[lang]["label"]}'
            "</button>"
        )
    parts.append("</nav></header><main>")
    for i, script in enumerate(story["scripts"]):
        lang = script["language"]
        labels = LABELS[lang]
        parent_note = (
            labels["partial"] if story["metrics"][0]["parent_status"] == "completed_partial" else ""
        )
        state = "snapshot" if story["status"] == Admission.VERIFIED else "draft"
        parts.extend(
            [
                f'<section data-edition="{lang}" lang="{lang}"' + (" hidden" if i else "") + ">",
                f'<div class="eyebrow">{labels["section"]} / {escape(story["as_of"][:10])}</div>',
                '<div class="hero"><div>',
                f"<h1>{escape(script['title']['text'])}</h1>",
                f'<p class="intro">{escape(script["introduction"]["text"])}</p></div>{ART}</div>',
                f'<aside class="disclosure"><strong>{labels[state]}</strong>'
                f"<br>{labels['disclosure']} {parent_note}",
                f'<div class="meta">{labels["as_of"]}: {escape(story["as_of"])} '
                f"({escape(story['timezone'])})</div></aside>",
                f'<nav class="contents" id="{lang}-contents" aria-label="{labels["contents"]}">',
            ]
        )
        for n, chapter in enumerate(script["chapters"], 1):
            parts.append(
                f'<a href="#{lang}-{chapter["chapter_id"]}">{n:02} / '
                f"{escape(chapter['title']['text'])}</a>"
            )
        parts.append("</nav>")
        for n, chapter in enumerate(script["chapters"], 1):
            parts.append(_chapter_html(chapter, story, lang, n))
        parts.extend(
            [
                f'<section class="closing"><div class="eyebrow">{labels["closing"]}</div>',
                f"<p>{escape(script['closing']['text'])}</p></section>",
                f'<footer class="footer">SignalTrail · '
                f'<a href="#{lang}-contents">{labels["top"]}</a>',
                "</footer></section>",
            ]
        )
    parts.append("""</main><script>
document.querySelectorAll('[data-language]').forEach(button=>button.addEventListener('click',()=>{
const language=button.dataset.language;
document.documentElement.lang=language;
document.querySelectorAll('[data-edition]').forEach(s=>s.hidden=s.dataset.edition!==language);
const heading=document.querySelector('[data-edition]:not([hidden]) h1');
document.title='SignalTrail · '+heading.textContent;
document.querySelectorAll('[data-language]').forEach(b=>b.setAttribute('aria-pressed',
String(b.dataset.language===language)));
}));</script><noscript><style>[data-edition][hidden]{display:block!important}</style></noscript>
</body></html>""")
    return "".join(parts)


def render_story_markdown(story: dict) -> str:
    """处理：保留与图文页相同的语言正文、视觉标签和来源。
    输入：不可变图文语义清单；Markdown 不从 HTML 反推。
    输出：与 JSON 一起提交的权威 Markdown，不含推测时长或实时通过标签。
    """
    lines = []
    for script in story["scripts"]:
        labels = LABELS[script["language"]]
        lines.extend(
            [
                f"# {script['title']['text']}",
                labels["disclosure"],
                f"{labels['as_of']}: {story['as_of']}",
                script["introduction"]["text"],
            ]
        )
        for chapter in script["chapters"]:
            lines.extend([f"## {chapter['title']['text']}", chapter["question"]["text"]])
            for beat in chapter["beats"]:
                lines.append(beat["text"])
                if beat["visual"]:
                    lines.append(labels[beat["visual_relation"]])
                    lines.extend(f"- {n['text']}" for n in beat["visual"])
                for evidence in _sources(beat["claim_ids"], story):
                    url = _safe_url(evidence["url"])
                    if url:
                        lines.append(f"[{evidence['source_name']}](<{url}>)")
        lines.extend([f"## {labels['closing']}", script["closing"]["text"]])
    return "\n\n".join(lines) + "\n"


def render_story(story_path: Path, data_dir: Path, *, mode: str = "preview") -> dict:
    """处理：检查父闭包后生成可恢复预览，拒绝未经时效适配器的实时发布。
    输入：确切故事修订和预览模式；不能从作者标签获得当前准入。
    输出：单文件 HTML 与绑定其字节摘要的投影回执；失败不影响日报。
    """
    story = load_artifact(story_path, data_dir, kind="story")
    if mode != "preview":
        raise ValueError("Current admission blocked: freshness adapter and live acceptance pending")
    html = render_story_html(story["payload"])
    output = story_path.parent / "projections" / digest(html) / "preview.html"
    if not output.exists():
        write_text_atomic(output, html)
    if output.read_text(encoding="utf-8") != html:
        raise ValueError("Existing projection changed")
    receipt = save_artifact(
        data_dir,
        story["session"],
        "projection",
        {
            "status": "preview",
            "html_ref": file_ref(output, data_dir),
            "renderer_hash": digest(CSS + ART),
            "visual_review": "pending",
        },
        {"story": story_path, "html": output},
    )
    return {
        "html_path": str(output),
        "projection_path": str(receipt),
        "story_path": str(story_path),
        "content_status": story["payload"]["status"],
        "current_admission": Admission.BLOCKED,
    }


def submit_visual_review(projection_path: Path, review: dict, data_dir: Path) -> Path:
    """处理：绑定实际渲染字节、逐卡双端检查与本地截图。
    输入：投影回执、实际检查结果和数据根内截图；不可见的端不能记为通过。
    输出：不可变视觉审核记录，后续布局改变必须重审。
    """
    projection = load_artifact(projection_path, data_dir, kind="projection")
    validate_schema(review, VISUAL_SCHEMA)
    if review["projection_sha256"] != projection["payload"]["html_ref"]["sha256"]:
        raise ValueError("Visual review belongs to another projection")
    story = load_artifact(parent_path(projection, "story", data_dir), data_dir, kind="story")
    cards = {
        f"{s['language']}-{ch['chapter_id']}"
        for s in story["payload"]["scripts"]
        for ch in s["chapters"]
    }
    ids = [r["card_id"] for r in review["cards"]]
    if set(ids) != cards or len(ids) != len(set(ids)):
        raise ValueError("Visual review must cover every card exactly once")
    parents = {"projection": projection_path}
    for i, name in enumerate(review["screenshots"]):
        path = data_dir / name
        file_ref(path, data_dir)
        if path.suffix.lower() != ".png" or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Visual evidence must be a local PNG screenshot")
        parents[f"screenshot-{i}"] = path
    status = (
        "pass"
        if all(r["desktop"] == r["mobile"] == "pass" for r in review["cards"])
        else "pending_or_failed"
    )
    return save_artifact(
        data_dir, story["session"], "visual-review", {"review": review, "status": status}, parents
    )
