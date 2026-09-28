from __future__ import annotations

import json
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(r"E:\WorkSpace\IPO-Risk-Agent")
FULL = Path(r"E:\WorkSpace\IPO-Full-System")
ANN_DIR = ROOT / "team_work" / "teamer_ex"
OUT_DIR = ROOT / "evaluation" / "benchmark"
AGENT_DATA = FULL / "agent" / "data"
AGENT_PROS = AGENT_DATA / "prospectuses"
CATALOG = AGENT_DATA / "prospectus_catalog.json"

DOC_MAP = {
    "01351_28-10-2020_辉煌明天_股份发售.pdf": {
        "document_id": "2020_01351_輝煌明天",
        "company_names": ["辉煌明天科技控股有限公司", "辉煌明天", "輝煌明天"],
        "raw_pdf": ROOT / "data" / "raw" / "2020_138份" / "01351_28-10-2020_輝煌明天_股份發售.pdf",
        "agent_pdf_name": "01351_28-10-2020_輝煌明天_股份發售.pdf",
        "stock_code": "01351.HK",
        "listing_date": "2020-11-09",
        "issue_price": 1.0,
        "year": 2020,
    },
    # annotation filename variants
    "01351_28-10-2020_輝煌明天_股份發售.pdf": {
        "document_id": "2020_01351_輝煌明天",
        "company_names": ["辉煌明天科技控股有限公司", "辉煌明天", "輝煌明天"],
        "raw_pdf": ROOT / "data" / "raw" / "2020_138份" / "01351_28-10-2020_輝煌明天_股份發售.pdf",
        "agent_pdf_name": "01351_28-10-2020_輝煌明天_股份發售.pdf",
        "stock_code": "01351.HK",
        "listing_date": "2020-11-09",
        "issue_price": 1.0,
        "year": 2020,
    },
    "03931_23-09-2022_中創新航_全球發售.pdf": {
        "document_id": "2022_03931_中創新航",
        "company_names": ["中創新航", "中创新航", "中創新航科技股份有限公司"],
        "raw_pdf": ROOT / "data" / "raw" / "2022_87份" / "03931_23-09-2022_中創新航_全球發售.pdf",
        "agent_pdf_name": "03931_23-09-2022_中創新航_全球發售.pdf",
        "stock_code": "03931.HK",
        "listing_date": "2022-10-06",
        "issue_price": 38.0,
        "year": 2022,
    },
}

CAT_MAP = {
    "财务风险": "financial_risk",
    "经营风险": "business_risk",
    "股权治理风险": "ownership_risk",
    "合规法律风险": "compliance_risk",
    "IPO 特殊风险": "ipo_specific_risk",
    "IPO特殊风险": "ipo_specific_risk",
}


def parse_records(path: Path) -> list[dict]:
    t = path.read_text(encoding="utf-8")
    parts = t.split("```text")
    recs = []
    for part in parts[1:]:
        body = part.split("```", 1)[0].strip()
        if "填写人" not in body:
            continue
        fields: dict[str, str] = {}
        current = None
        buf: list[str] = []

        def flush() -> None:
            nonlocal current, buf
            if current is not None:
                fields[current] = "\n".join(buf).strip()
            current = None
            buf = []

        for line in body.splitlines():
            m = re.match(
                r"^(填写人|日期|题目编号|公司名称|PDF 文件名|风险大类|风险子类|问题|最佳证据所在章节|最佳证据页码|是否表格证据|证据关键词|原文摘录|为什么这是最佳证据|不确定点|建议标注状态)[:：]\s*(.*)$",
                line,
            )
            if m:
                flush()
                current = m.group(1)
                buf = [m.group(2)]
            elif current is not None:
                buf.append(line)
        flush()
        rec = {
            "annotator": fields.get("填写人", "").strip(),
            "date": fields.get("日期", "").strip(),
            "case_id": fields.get("题目编号", "").strip(),
            "company": fields.get("公司名称", "").strip(),
            "pdf": fields.get("PDF 文件名", "").strip(),
            "risk_major": fields.get("风险大类", "").strip(),
            "risk_sub": fields.get("风险子类", "").strip(),
            "question": re.sub(r"\s+", " ", fields.get("问题", "").strip()),
            "section": fields.get("最佳证据所在章节", "").strip(),
            "pages_raw": fields.get("最佳证据页码", "").strip(),
            "is_table": fields.get("是否表格证据", "").strip(),
            "keywords": fields.get("证据关键词", "").strip(),
            "excerpt": re.sub(r"\s+", " ", fields.get("原文摘录", "").strip()),
            "why": fields.get("为什么这是最佳证据", "").strip(),
            "uncertain": fields.get("不确定点", "").strip(),
            "status": fields.get("建议标注状态", "").strip(),
            "source_file": path.name,
        }
        if rec["annotator"] in ("", "赵六"):
            continue
        if not rec["company"] or not rec["question"]:
            continue
        pages = re.findall(r"\[\[\s*(\d+)\s*,\s*(\d+)\s*\]\]", rec["pages_raw"])
        if not pages:
            pages = re.findall(r"\[(\d+)\s*,\s*(\d+)\]", rec["pages_raw"])
        rec["page_ranges"] = [[int(a), int(b)] for a, b in pages]
        recs.append(rec)
    return recs


def pdf_label_map(pdf_path: Path) -> dict[str, int]:
    """Map printed page label -> 0-based physical page index."""
    import fitz

    doc = fitz.open(pdf_path)
    mapping: dict[str, int] = {}
    for i in range(doc.page_count):
        label = doc[i].get_label() or str(i + 1)
        # keep first occurrence
        mapping.setdefault(str(label).strip(), i)
        # also numeric-only form
        m = re.search(r"(\d+)", str(label))
        if m:
            mapping.setdefault(m.group(1), i)
    doc.close()
    return mapping


def to_physical_ranges(page_ranges: list[list[int]], label_map: dict[str, int]) -> tuple[list[list[int]], str]:
    if not page_ranges:
        return [], "no_pages"
    out = []
    missing = 0
    for a, b in page_ranges:
        pa = label_map.get(str(a))
        pb = label_map.get(str(b))
        if pa is None or pb is None:
            missing += 1
            # fallback: treat annotation as 1-based physical if labels missing
            pa = max(a - 1, 0) if pa is None else pa
            pb = max(b - 1, 0) if pb is None else pb
        if pa > pb:
            pa, pb = pb, pa
        out.append([pa, pb])
    status = "label_mapped" if missing == 0 else "partial_fallback_1based"
    return out, status


def keywords_list(raw: str) -> list[str]:
    parts = re.split(r"[、,，;/；\s]+", raw)
    return [p.strip() for p in parts if p.strip()]


def stage_pdfs(needed_pdfs: set[str]) -> list[dict]:
    AGENT_PROS.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {"version": "gold-frontend-v1", "items": {}}
    items = catalog.setdefault("items", {})
    staged = []
    for pdf_name in sorted(needed_pdfs):
        meta = DOC_MAP.get(pdf_name)
        if not meta:
            # try fuzzy
            for k, v in DOC_MAP.items():
                if pdf_name.replace("辉煌", "輝煌").replace("发售", "發售") == k or pdf_name in k or k in pdf_name:
                    meta = v
                    break
        if not meta:
            staged.append({"pdf": pdf_name, "status": "unknown_mapping"})
            continue
        src = meta["raw_pdf"]
        dst = AGENT_PROS / meta["agent_pdf_name"]
        if not src.exists():
            staged.append({"pdf": pdf_name, "status": "source_missing", "src": str(src)})
            continue
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
            action = "copied"
        else:
            action = "exists"
        key = meta["agent_pdf_name"]
        items[key] = {
            "company_name": meta["company_names"][0],
            "stock_code": meta["stock_code"],
            "listing_date": meta["listing_date"],
            "issue_price": meta["issue_price"],
            "document_id": meta["document_id"],
            "year": meta["year"],
            "prediction_as_of": f"{meta['listing_date']}T23:59:00+08:00",
            "path": f"prospectuses/{meta['agent_pdf_name']}",
        }
        staged.append(
            {
                "pdf": pdf_name,
                "document_id": meta["document_id"],
                "agent_pdf": str(dst),
                "status": action,
                "vectors_expected_doc": meta["document_id"],
            }
        )
    catalog["note"] = (
        "Manual Gold + new annotator demo defaults for local Agent frontend. "
        "issue_price/listing_date are form defaults, not official market facts."
    )
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return staged


def search_rag(query: str, company: str | None, document_id: str | None, top_k: int = 5) -> dict:
    body = {
        "query": query,
        "top_k": top_k,
        "enable_followup": True,
        "enable_claim_analysis": False,
    }
    if company:
        body["company"] = company
    if document_id:
        body["document_id"] = document_id
    req = urllib.request.Request(
        "http://127.0.0.1:8000/v1/search",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def norm(s: str) -> str:
    s = (s or "").lower()
    table = str.maketrans({
        "為": "为", "與": "与", "對": "对", "業": "业", "國": "国", "們": "们",
        "於": "于", "後": "后", "來": "来", "這": "这", "還": "还", "從": "从",
        "開": "开", "關": "关", "無": "无", "產": "产", "億": "亿", "萬": "万",
        "餘": "余", "並": "并", "計": "计", "報": "报", "發": "发", "總": "总",
        "佔": "占", "經": "经", "營": "营", "現": "现", "輝": "辉", "創": "创",
        "東": "东", "車": "车", "電": "电", "風": "风", "險": "险",
    })
    s = s.translate(table)
    s = re.sub(r"\s+", "", s)
    return s


def excerpt_hit(text: str, excerpt: str) -> dict:
    if not excerpt:
        return {"hit": False, "coverage": 0.0, "matched_tokens": []}
    # token-ish: numbers/percents + long CJK chunks
    tokens = re.findall(r"\d+(?:\.\d+)?%?|[\u4e00-\u9fff]{2,8}", excerpt)
    tokens = list(dict.fromkeys(tokens))[:20]
    nt = norm(text)
    matched = []
    for tok in tokens:
        if norm(tok) and norm(tok) in nt:
            matched.append(tok)
    cov = (len(matched) / len(tokens)) if tokens else 0.0
    return {"hit": cov >= 0.35 or (len(matched) >= 3), "coverage": round(cov, 4), "matched_tokens": matched[:10]}


def keyword_hit(text: str, keywords: list[str]) -> dict:
    if not keywords:
        return {"hit": False, "coverage": 0.0, "matched": []}
    nt = norm(text)
    matched = [k for k in keywords if norm(k) and norm(k) in nt]
    cov = len(matched) / len(keywords)
    return {"hit": cov >= 0.4 or len(matched) >= 2, "coverage": round(cov, 4), "matched": matched}


def pages_overlap(result_pages: list[int], expected_phys: list[list[int]]) -> bool:
    if not result_pages or not expected_phys:
        return False
    for p in result_pages:
        for a, b in expected_phys:
            if a <= int(p) <= b:
                return True
    return False


def main() -> None:
    files = [
        ANN_DIR / "PDF证据标注模板-董飞飞.txt",
        ANN_DIR / "PDF证据标注模板-田歌.txt",
    ]
    recs: list[dict] = []
    for f in files:
        recs.extend(parse_records(f))

    # build label maps once per pdf
    label_maps: dict[str, dict[str, int]] = {}
    gold = []
    for i, r in enumerate(recs, 1):
        meta = DOC_MAP.get(r["pdf"])
        if not meta:
            # normalize simplified filename to traditional map
            alt = r["pdf"].replace("辉煌", "輝煌").replace("发售", "發售")
            meta = DOC_MAP.get(alt)
        if not meta:
            print("SKIP unmapped", r["pdf"], r["case_id"])
            continue
        pdf_path = meta["raw_pdf"]
        if str(pdf_path) not in label_maps:
            label_maps[str(pdf_path)] = pdf_label_map(pdf_path) if pdf_path.exists() else {}
        phys, map_status = to_physical_ranges(r["page_ranges"], label_maps[str(pdf_path)])
        kws = keywords_list(r["keywords"])
        gid = f"manual_new_{r['annotator']}_{r['case_id'] or i}"
        gold.append(
            {
                "id": gid,
                "annotator": r["annotator"],
                "category": CAT_MAP.get(r["risk_major"], "unknown"),
                "risk_sub": r["risk_sub"],
                "question": r["question"],
                "keywords": kws,
                "expected_keywords": kws,
                "expected_document_ids": [meta["document_id"]],
                "expected_companies": meta["company_names"],
                "expected_sections": [s for s in re.split(r"[；;／/]", r["section"]) if s.strip()][:4],
                "expected_page_ranges": r["page_ranges"],
                "raw_annotated_page_ranges": r["page_ranges"],
                "page_basis": "printed_page_label",
                "expected_page_labels": r["page_ranges"],
                "expected_physical_page_ranges_0_based": phys,
                "page_mapping_status": "confirmed" if map_status == "label_mapped" else "provisional",
                "mapping_note": f"Mapped from annotation pages via PDF page labels ({map_status}).",
                "expected_evidence_text": r["excerpt"],
                "is_table_evidence": r["is_table"] in ("是", "yes", "Y", "y", "true", "True"),
                "source_file": r["source_file"],
                "annotation_status": r["status"] or "gold_seed",
                "uncertain": r["uncertain"],
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gold_path = OUT_DIR / "manual_new_annotators_v1.json"
    gold_path.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")

    needed = {r["pdf"] for r in recs}
    staged = stage_pdfs(needed)

    # verify index coverage
    docs = json.loads((ROOT / "data" / "vectors" / "documents.json").read_text(encoding="utf-8"))
    by_doc: dict[str, int] = {}
    for d in docs:
        did = d.get("document_id") or ""
        by_doc[did] = by_doc.get(did, 0) + 1

    # RAG-only evaluation (no Agent LLM)
    results = []
    for case in gold:
        did = case["expected_document_ids"][0]
        company = case["expected_companies"][0]
        # Prefer document_id scope; company is assistive only.
        data = search_rag(case["question"], company=None, document_id=did, top_k=5)
        res = data.get("results") or []
        texts = "\n".join((item.get("text") or "") for item in res)
        doc_ids = [item.get("document_id") for item in res]
        all_pages: list[int] = []
        for item in res:
            for p in item.get("pages") or []:
                try:
                    all_pages.append(int(p))
                except Exception:
                    pass
        doc_hit = any(x == did for x in doc_ids)
        kw = keyword_hit(texts, case.get("expected_keywords") or [])
        ex = excerpt_hit(texts, case.get("expected_evidence_text") or "")
        page_hit = pages_overlap(all_pages, case.get("expected_physical_page_ranges_0_based") or [])
        top1_text = (res[0].get("text") if res else "") or ""
        top1_pages = res[0].get("pages") if res else []
        results.append(
            {
                "id": case["id"],
                "annotator": case["annotator"],
                "category": case["category"],
                "document_id": did,
                "question": case["question"],
                "document_hit": doc_hit,
                "keyword_hit": kw["hit"],
                "keyword_coverage": kw["coverage"],
                "keyword_matched": kw["matched"],
                "excerpt_hit": ex["hit"],
                "excerpt_coverage": ex["coverage"],
                "excerpt_matched_tokens": ex["matched_tokens"],
                "page_hit": page_hit,
                "result_pages": sorted(set(all_pages))[:20],
                "expected_physical_pages": case.get("expected_physical_page_ranges_0_based"),
                "top1_pages": top1_pages,
                "top1_preview": re.sub(r"\s+", " ", top1_text)[:220],
                "n_results": len(res),
                "routing": data.get("routing"),
            }
        )
        print(
            case["id"],
            "doc",
            doc_hit,
            "kw",
            kw["hit"],
            round(kw["coverage"], 2),
            "ex",
            ex["hit"],
            round(ex["coverage"], 2),
            "page",
            page_hit,
        )

    n = len(results) or 1
    summary = {
        "n_cases": len(results),
        "document_hit_rate": round(sum(r["document_hit"] for r in results) / n, 4),
        "keyword_hit_rate": round(sum(r["keyword_hit"] for r in results) / n, 4),
        "excerpt_hit_rate": round(sum(r["excerpt_hit"] for r in results) / n, 4),
        "page_hit_rate": round(sum(r["page_hit"] for r in results) / n, 4),
        "by_annotator": {},
        "by_document": {},
        "index_vectors": {did: by_doc.get(did, 0) for did in sorted({c["expected_document_ids"][0] for c in gold})},
        "staged_pdfs": staged,
        "note": "RAG-only offline evaluation. No Agent/LLM keys used.",
    }
    for key_name, field in [("by_annotator", "annotator"), ("by_document", "document_id")]:
        groups: dict[str, list] = {}
        for r in results:
            groups.setdefault(str(r[field]), []).append(r)
        for g, rows in groups.items():
            m = len(rows) or 1
            summary[key_name][g] = {
                "n": len(rows),
                "document_hit_rate": round(sum(x["document_hit"] for x in rows) / m, 4),
                "keyword_hit_rate": round(sum(x["keyword_hit"] for x in rows) / m, 4),
                "excerpt_hit_rate": round(sum(x["excerpt_hit"] for x in rows) / m, 4),
                "page_hit_rate": round(sum(x["page_hit"] for x in rows) / m, 4),
            }

    res_path = OUT_DIR / "manual_new_annotators_v1_rag_results.json"
    res_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    # markdown report
    lines = [
        "# Manual New Annotators V1 – RAG-only Evaluation",
        "",
        "## Scope",
        "- Sources: 董飞飞 / 田歌 PDF evidence annotations",
        "- PDFs: 辉煌明天(01351), 中创新航(03931)",
        "- Evaluator: Thin RAG API only (no Agent LLM / no external key spend)",
        "- Goal: generalizable acceptance criteria, not overfit to these PDFs",
        "",
        "## Index readiness",
    ]
    for did, cnt in summary["index_vectors"].items():
        lines.append(f"- `{did}`: {cnt} vectors (already in index, no re-embedding needed)")
    lines += ["", "## Staging for Agent frontend (optional UI only)"]
    for s in staged:
        lines.append(f"- {s}")
    lines += [
        "",
        "## Metrics (Top5)",
        f"- cases: {summary['n_cases']}",
        f"- document hit: {summary['document_hit_rate']*100:.1f}%",
        f"- keyword hit: {summary['keyword_hit_rate']*100:.1f}%",
        f"- excerpt support hit: {summary['excerpt_hit_rate']*100:.1f}%",
        f"- physical page hit: {summary['page_hit_rate']*100:.1f}%",
        "",
        "## By annotator",
    ]
    for k, v in summary["by_annotator"].items():
        lines.append(
            f"- {k}: n={v['n']}, doc={v['document_hit_rate']*100:.1f}%, kw={v['keyword_hit_rate']*100:.1f}%, excerpt={v['excerpt_hit_rate']*100:.1f}%, page={v['page_hit_rate']*100:.1f}%"
        )
    lines += ["", "## Failures (actionable)"]
    fails = [r for r in results if not (r["document_hit"] and (r["keyword_hit"] or r["excerpt_hit"]))]
    if not fails:
        lines.append("- none under current soft gate (doc + keyword/excerpt)")
    for r in fails:
        lines.append(
            f"- `{r['id']}` doc={r['document_hit']} kw={r['keyword_hit']} excerpt={r['excerpt_hit']} page={r['page_hit']} | {r['question']}"
        )
    lines += [
        "",
        "## Acceptance criteria (do NOT overfit)",
        "Use these gates for go/no-go on RAG quality before Agent demo:",
        "",
        "### Hard gates (RAG-only)",
        "1. document hit >= 90% on this new set AND on frozen Manual Gold V1",
        "2. excerpt support hit >= 70% (or keyword hit >= 70% if excerpt short)",
        "3. page hit >= 60% after label->physical mapping (diagnostic, not sole kill criterion)",
        "4. no category collapse: each risk class with >=3 cases should have document hit >= 80%",
        "",
        "### Soft gates",
        "1. top1 should usually contain at least one expected keyword or numeric fact when question asks for ratio/amount",
        "2. failures should not be fixed by hardcoding company-specific boosts",
        "",
        "### Explicit non-goals",
        "- Do not tune ranker only to 辉煌明天/中创新航",
        "- Do not spend Agent teammate LLM quota for this gate",
        "- Agent room quality is secondary; evidence raw material quality is primary",
        "",
        "## Your manual verification steps",
        "1. RAG UI: http://127.0.0.1:8501/  query the new questions with company/document constrained",
        "2. Agent UI (optional): http://127.0.0.1:8001/  should now list the two PDFs; use RAG ON",
        "3. For each failed case above, check whether gold excerpt text exists in retrieved top5",
        "4. If page miss but excerpt hit: mapping/display issue, not necessarily retrieval miss",
        "5. If excerpt miss: true retrieval/representation issue -> RAG optimization candidate",
        "",
        f"Artifacts: `{gold_path}` , `{res_path}`",
    ]
    report = ROOT / "docs" / "rag" / "MANUAL_NEW_ANNOTATORS_V1_RAG_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False, indent=2))
    print("report", report)


if __name__ == "__main__":
    main()
