"""Lightweight traditional/simplified term normalization and section families."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence

# Character-level traditional -> simplified map focused on IPO risk vocabulary.
TRAD_TO_SIMP = str.maketrans(
    {
        "識": "识", "寧": "宁", "徳": "德", "豐": "丰", "獲": "获", "觸": "触", "圍": "围", "圍": "围", "術": "术", "質": "质", "總": "总", "額": "额",
        "東": "东", "務": "务", "業": "业", "與": "与", "為": "为",
        "於": "于", "對": "对", "開": "开", "關": "关", "門": "门",
        "問": "问", "題": "题", "條": "条", "項": "项", "萬": "万",
        "億": "亿", "並": "并", "從": "从", "後": "后", "當": "当",
        "時": "时", "間": "间", "將": "将", "來": "来", "還": "还",
        "這": "这", "該": "该", "經": "经", "營": "营", "運": "运",
        "轉": "转", "變": "变", "動": "动", "據": "据", "證": "证",
        "應": "应", "賬": "账", "虧": "亏", "損": "损", "約": "约",
        "發": "发", "現": "现", "資": "资", "財": "财", "實": "实",
        "際": "际", "聯": "联", "風": "风", "險": "险", "數": "数",
        "價": "价", "訴": "诉", "訟": "讼", "採": "采", "購": "购",
        "佔": "占", "會": "会", "報": "报", "產": "产", "戶": "户",
        "點": "点", "軟": "软", "國": "国", "車": "车", "銷": "销",
        "舊": "旧", "淨": "净", "債": "债", "許": "许", "隱": "隐",
        "確": "确", "認": "认", "雲": "云", "聲": "声", "電": "电",
        "監": "监", "規": "规", "歷": "历", "組": "组", "層": "层",
        "劃": "划", "計": "计", "錄": "录", "調": "调", "幣": "币",
        "週": "周", "預": "预", "記": "记", "處": "处", "裡": "里",
        "無": "无", "們": "们", "個": "个", "長": "长", "區": "区",
        "華": "华", "內": "内", "卻": "却", "則": "则", "給": "给",
        "讓": "让", "說": "说", "請": "请", "見": "见", "視": "视",
        "覽": "览", "款": "款", "匯": "汇", "備": "备", "復": "复",
        "複": "复", "審": "审", "師": "师", "顯": "显", "標": "标",
        "準": "准", "權": "权", "責": "责", "員": "员", "僱": "雇",
        "傭": "佣", "減": "减", "餘": "余", "負": "负", "優": "优",
        "級": "级", "競": "竞", "爭": "争", "劇": "剧", "趨": "趋",
        "勢": "势", "壘": "垒", "遲": "迟", "緩": "缓", "難": "难",
        "撥": "拨", "潤": "润", "議": "议", "進": "进", "場": "场",
        "貸": "贷", "償": "偿", "觀": "观", "濟": "济", "決": "决",
    }
)

# Explicit multi-character aliases (simplified canonical -> variants).
TERM_ALIASES: Dict[str, List[str]] = {
    "知识产权侵权": ["知识产权侵权", "知識產權侵權", "侵权申索", "侵權申索"],

    "净亏损": ["净亏损", "淨虧損"],

    "净负债": ["净负债", "淨負債"],

    "经营活动所用现金": ["经营活动所用现金", "經營活動所用現金", "经营现金", "經營現金"],

    "现金流量净额": ["现金流量净额", "現金流量淨額"],

    "流动负债": ["流动负债", "流動負債"],

    "经调整净亏损": ["经调整净亏损", "經調整淨虧損"],

    "许可证": ["许可证", "許可證", "牌照"],

    "数据": ["数据", "數據"],

    "隐私": ["隐私", "隱私"],

    "诉讼": ["诉讼", "訴訟"],

    "董事确认": ["董事确认", "董事確認", "据董事所知", "據董事所知"],

    "监管": ["监管", "監管"],

    "所得款项净额": ["所得款项净额", "所得款項淨額", "所得款项", "所得款項"],

    "用途": ["用途"],


    "募资": ["募资", "募資", "募集资金", "募集資金"],

}



SECTION_FAMILY_KEYWORDS: Dict[str, List[str]] = {

    "financial": [

        "财务资料", "財務資料", "会计师报告", "會計師報告", "综合财务", "綜合財務",

        "合并全面亏损", "合併全面虧損", "财务摘要", "財務摘要", "净亏损", "淨虧損",

        "现金流", "現金流", "流动负债", "流動負債",

    ],

    "compliance": [

        "风险因素", "風險因素", "法规", "法規", "法律", "监管", "監管", "诉讼", "訴訟",

        "牌照", "许可证", "許可證", "数据", "數據", "隐私", "隱私", "法定及一般资料", "法定及一般資料",

    ],

    "ownership": [

        "历史及重组", "歷史及重組", "控股股东", "控股股東", "董事及高级管理层", "董事及高級管理層",

        "主要股东", "主要股東",

    ],

    "business": ["业务", "業務", "概要"],

    "ipo": [

        "未来计划及所得款项用途", "未來計劃及所得款項用途", "所得款项用途", "所得款項用途",

        "所得款项", "所得款項", "募资", "募資", "全球发售", "全球發售",

    ],

}



QUERY_FAMILY_TRIGGERS: Dict[str, List[str]] = {

    "financial": ["净亏损", "净负债", "现金流", "流动负债", "毛利率", "亏损", "负债", "财务"],

    "compliance": ["诉讼", "仲裁", "许可证", "牌照", "数据", "隐私", "合规", "监管", "处罚"],

    "ownership": ["控股股东", "关联交易", "股权", "一致行动", "董事"],

    "business": ["客户", "供应商", "竞争", "商业模式", "集中度"],

    "ipo": ["所得款项", "募资", "募集资金", "发售", "上市所得", "用途"],

}





def normalize_text(text: str) -> str:

    return re.sub(r"\s+", "", str(text or "").translate(TRAD_TO_SIMP)).lower()





def alias_variants(term: str) -> List[str]:

    key = normalize_text(term)

    variants = [term]

    for canonical, alias_list in TERM_ALIASES.items():

        if key == normalize_text(canonical) or any(key == normalize_text(a) for a in alias_list):

            variants.extend(alias_list)

            variants.append(canonical)

    # Always include normalized form as a soft variant for matching.

    variants.append(normalize_text(term))

    # Deduplicate while preserving order.

    seen = set()

    unique: List[str] = []

    for item in variants:

        marker = normalize_text(item)

        if not marker or marker in seen:

            continue

        seen.add(marker)

        unique.append(item)

    return unique





def term_matches(text: str, term: str) -> bool:

    haystack = normalize_text(text)

    for variant in alias_variants(term):

        wanted = normalize_text(variant)

        if not wanted:

            continue

        if wanted in haystack:

            return True

        if wanted.endswith("%") and wanted[:-1] in haystack:

            return True

    return False





def expand_query_with_aliases(query: str) -> str:

    """Keep original query and append useful traditional/simplified aliases."""

    parts = [query]

    normalized_query = normalize_text(query)

    for canonical, alias_list in TERM_ALIASES.items():

        if normalize_text(canonical) in normalized_query or any(

            normalize_text(alias) in normalized_query for alias in alias_list

        ):

            for alias in alias_list:

                if alias not in query and alias not in parts:

                    parts.append(alias)

    return " ".join(parts)





def infer_section_families(query: str) -> List[str]:

    normalized = normalize_text(query)

    families: List[str] = []

    for family, triggers in QUERY_FAMILY_TRIGGERS.items():

        if any(normalize_text(trigger) in normalized for trigger in triggers):

            families.append(family)

    return families





def section_family_match(section_path: Sequence[str], families: Iterable[str]) -> bool:

    # Section labels sometimes arrive spaced like "財 務 資 料"; normalize_text strips spaces.

    section_text = normalize_text(" ".join(str(item) for item in (section_path or [])))

    if not section_text:

        return False

    for family in families:

        keywords = SECTION_FAMILY_KEYWORDS.get(family, [])

        for keyword in keywords:

            nk = normalize_text(keyword)

            if not nk:

                continue

            if nk in section_text or section_text in nk:

                return True

        # 概要 is a weak business/ipo anchor only; avoid treating every summary page as financial.

        if family in {"business", "ipo"} and "概要" in section_text:

            return True

    return False





def section_match_score(section_path: Sequence[str], families: Iterable[str]) -> float:

    if section_family_match(section_path, families):

        return 1.0

    section_text = normalize_text(" ".join(str(item) for item in (section_path or [])))

    score = 0.0

    for family in families:

        for keyword in SECTION_FAMILY_KEYWORDS.get(family, []):

            nk = normalize_text(keyword)

            if nk and nk in section_text:

                score = max(score, min(1.0, len(nk) / max(len(section_text), 1)))

    return score

