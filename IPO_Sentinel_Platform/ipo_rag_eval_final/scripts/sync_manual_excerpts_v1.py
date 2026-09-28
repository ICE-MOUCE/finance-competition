from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
HUMAN4_PATH = ROOT / "evaluation" / "benchmark" / "manual_human4_v1.json"
GOLD_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
NEW_PATH = ROOT / "evaluation" / "benchmark" / "manual_new_annotators_v1.json"
EXTRACTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_annotation_original_extracts.json"
AUDIT_PATH = ROOT / "evaluation" / "benchmark" / "human_annotation_retrieval_audit.json"
TEAMER_DIR = ROOT / "team_work" / "teamer_ex"

HUMAN4_ANNOTATORS = {"\u9648\u6167", "\u8463\u98de\u98de", "\u8c2d\u601d\u6021", "\u7530\u6b4c"}

PARAPHRASE_RE = re.compile(
    r"\u7b2c\s*\d+\s*\u9875(?:\u62ab\u9732|\u8bf4\u660e|\u5217\u793a|\u63d0\u5230|\u6307\u51fa)|\u62db\u80a1\u4e66(?:\u540c\u65f6)?\u62ab\u9732|\u516c\u53f8\u8ba1\u5212\u5c06"
)
TRADITIONAL_MARKERS = (
    "\u6211\u5011",
    "\u65bc\u5f80\u7e5e",
    "\u98a8\u96aa\u56e0\u7d20",
    "\u6240\u5f97\u6b3e\u9805",
    "\u4e26\u7121",
    "\u6982\u7121",
    "\u4f54",
)


def load_cases(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, list) else payload.get("cases", [])


def looks_like_human_paraphrase(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if PARAPHRASE_RE.search(raw):
        if not any(m in raw for m in TRADITIONAL_MARKERS):
            return True
        if re.match(r"^\u7b2c\s*\d+\s*\u9875", raw):
            return True
    return False


def classify_excerpt_kind(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "missing"
    if looks_like_human_paraphrase(raw):
        return "human_paraphrase"
    return "prospectus_verbatim"


def parse_template_excerpts() -> Dict[str, str]:
    """Best-effort parse of teamer_ex PDF templates: question -> original excerpt."""
    out: Dict[str, str] = {}
    if not TEAMER_DIR.exists():
        return out
    for path in sorted(TEAMER_DIR.glob("PDF*\u8bc1\u636e\u6807\u6ce8\u6a21\u677f-*.txt")):
        raw = path.read_text(encoding="utf-8-sig")
        blocks = re.split(r"\n(?=\u9898\u76ee\u7f16\u53f7[：:])", raw)
        for block in blocks:
            q_m = re.search(r"\u95ee\u9898[：:]\s*(.+)", block)
            e_m = re.search(r"\u539f\u6587\u6458\u5f55[：:]\s*(.+)", block, re.S)
            if not q_m or not e_m:
                continue
            question = q_m.group(1).strip().splitlines()[0].strip()
            excerpt = e_m.group(1).strip()
            # stop at next field-ish line
            stop = re.search(
                r"\n(?:\u4e3a\u4ec0\u4e48\u8fd9\u662f\u6700\u4f73\u8bc1\u636e|\u4e0d\u786e\u5b9a\u70b9|\u5efa\u8bae\u6807\u6ce8\u72b6\u6001|\u9898\u76ee\u7f16\u53f7)[：:]",
                "\n" + excerpt,
            )
            if stop:
                excerpt = excerpt[: stop.start()].strip()
            if question and excerpt:
                out[question] = excerpt
    return out


def index_by_id(*groups: List[Dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for group in groups:
        for case in group:
            cid = str(case.get("id") or "")
            if cid:
                out[cid] = case
    return out


def resolve_excerpt(case: Dict, template_by_q: Dict[str, str], old_extract: Optional[Dict]) -> Dict[str, str]:
    expected = str(case.get("expected_evidence_text") or "").strip()
    template = template_by_q.get(str(case.get("question") or "").strip(), "")
    cached = ""
    if old_extract:
        cached = str(old_extract.get("original_excerpt") or old_extract.get("manual_original_excerpt") or "").strip()
    if expected:
        src, text = "expected_evidence_text", expected
    elif template:
        src, text = "teamer_ex_template", template
    elif cached:
        src, text = "extracts_cache", cached
    else:
        src, text = "missing", ""
    return {
        "excerpt": text,
        "excerpt_kind": classify_excerpt_kind(text),
        "excerpt_source": src,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync manual display excerpts from Gold/template authority.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    human4 = [c for c in load_cases(HUMAN4_PATH) if str(c.get("annotator") or "") in HUMAN4_ANNOTATORS]
    if not human4:
        # fallback filter source banks
        human4 = [
            c
            for c in (load_cases(GOLD_PATH) + load_cases(NEW_PATH))
            if str(c.get("annotator") or "") in HUMAN4_ANNOTATORS
        ]
    by_id = index_by_id(load_cases(GOLD_PATH), load_cases(NEW_PATH), human4)
    template_by_q = parse_template_excerpts()

    old_extracts = []
    if EXTRACTS_PATH.exists():
        old_extracts = json.loads(EXTRACTS_PATH.read_text(encoding="utf-8-sig"))
    old_by_id = {item.get("gold_case_id"): item for item in old_extracts}

    new_extracts = []
    changed = []
    for case in human4:
        cid = case.get("id")
        full = by_id.get(cid, case)
        old = old_by_id.get(cid, {})
        resolved = resolve_excerpt(full, template_by_q, old)
        row = {
            "gold_case_id": cid,
            "annotator": full.get("annotator") or case.get("annotator") or "",
            "company": (full.get("expected_companies") or [full.get("company") or ""])[0],
            "question": full.get("question") or "",
            "original_excerpt": resolved["excerpt"],
            "excerpt_kind": resolved["excerpt_kind"],
            "excerpt_source": resolved["excerpt_source"],
            "core_terms": old.get("core_terms") or full.get("expected_keywords") or full.get("keywords") or [],
            "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "authority_note": "expected_evidence_text > teamer_ex > legacy extracts",
        }
        # preserve legacy paraphrase separately if different
        legacy = str(old.get("original_excerpt") or "").strip()
        if legacy and legacy != resolved["excerpt"]:
            row["legacy_paraphrase_excerpt"] = legacy
        new_extracts.append(row)
        if legacy and legacy != resolved["excerpt"]:
            changed.append(cid)

    # Keep any non-human4 historical extract rows but rewrite their original_excerpt if gold available
    keep_extra = []
    human_ids = {c.get("id") for c in human4}
    for item in old_extracts:
        cid = item.get("gold_case_id")
        if cid in human_ids:
            continue
        full = by_id.get(cid)
        if full and str(full.get("expected_evidence_text") or "").strip():
            item = dict(item)
            legacy = str(item.get("original_excerpt") or "").strip()
            item["legacy_paraphrase_excerpt"] = legacy
            item["original_excerpt"] = str(full.get("expected_evidence_text") or "").strip()
            item["excerpt_kind"] = classify_excerpt_kind(item["original_excerpt"])
            item["excerpt_source"] = "expected_evidence_text"
            item["synced_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if legacy and legacy != item["original_excerpt"]:
                changed.append(cid)
        keep_extra.append(item)

    final_extracts = new_extracts + keep_extra

    # Audit display field sync
    audit = {}
    if AUDIT_PATH.exists():
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8-sig"))
    audit_cases = audit.get("cases", []) if isinstance(audit, dict) else []
    extract_map = {r["gold_case_id"]: r for r in new_extracts}
    audit_changed = 0
    for row in audit_cases:
        cid = row.get("case_id")
        if cid not in extract_map:
            continue
        resolved = extract_map[cid]
        new_excerpt = str(resolved.get("original_excerpt") or "").strip()
        old_disp = str(row.get("manual_original_excerpt") or "").strip()
        if old_disp and old_disp != new_excerpt:
            row["legacy_paraphrase_excerpt"] = old_disp
            audit_changed += 1
        row["manual_original_excerpt"] = new_excerpt
        row["excerpt_kind"] = resolved.get("excerpt_kind")
        row["excerpt_source"] = resolved.get("excerpt_source")

    summary = {
        "human4_count": len(human4),
        "extracts_rows": len(final_extracts),
        "excerpt_source_updated_ids": sorted(set(changed)),
        "audit_rows_updated": audit_changed,
        "template_questions_parsed": len(template_by_q),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.dry_run:
        return

    EXTRACTS_PATH.write_text(json.dumps(final_extracts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if isinstance(audit, dict):
        audit["excerpt_sync"] = {
            "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "authority": "expected_evidence_text > teamer_ex > extracts",
            "updated_case_ids": sorted(set(changed)),
        }
        AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {EXTRACTS_PATH}")
    print(f"wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()