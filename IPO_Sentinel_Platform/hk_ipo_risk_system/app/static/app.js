const state = {
  selected: null,
  analysisId: null,
  pollTimer: null,
  roomSessionId: null,
  roomPollTimer: null,
  skills: [],
  providers: {},
  analysisStatus: null,
};

const $ = (id) => document.getElementById(id);
const TABS = ["overview", "claims", "evidence", "traces", "agentroom"];

const SKILL_COLORS = {
  financial_risk: "#2f80ed",
  legal_risk: "#f6bd16",
  equity_risk: "#9270ca",
  business_risk: "#d48806",
  market_risk: "#2ca58d",
  nonstandard_risk: "#cf6679",
};

const DEFAULT_SKILLS = [
  {
    skill_id: "financial_risk",
    label: "财务风险 Agent",
    description: "现金流 / 盈利质量 / 杠杆 / 募资用途",
    role_color: "#2f80ed",
    default_provider: "deepseek",
  },
  {
    skill_id: "legal_risk",
    label: "法务风险 Agent",
    description: "诉讼 / 监管 / 牌照 / 数据合规",
    role_color: "#f6bd16",
    default_provider: "deepseek",
  },
  {
    skill_id: "equity_risk",
    label: "股权风险 Agent",
    description: "控制权 / 特殊权利 / 稀释 / 锁定期",
    role_color: "#9270ca",
    default_provider: "deepseek",
  },
  {
    skill_id: "business_risk",
    label: "经营风险 Agent",
    description: "客户供应商 / 管线 / 商业化 / 技术依赖",
    role_color: "#d48806",
    default_provider: "deepseek",
  },
  {
    skill_id: "market_risk",
    label: "市场风险 Agent",
    description: "市场状态 / IPO 窗口 / 认购 / 舆情",
    role_color: "#2ca58d",
    default_provider: "deepseek",
  },
  {
    skill_id: "nonstandard_risk",
    label: "非标风险 Agent",
    description: "非标条款 / 异常承诺 / 模糊披露 / 量化缺口",
    role_color: "#cf6679",
    default_provider: "deepseek",
  },
];

const RADAR_DIMENSIONS = [
  { key: "financial_risk", label: "财务风险", color: "#2f80ed", prefixes: ["FIN_"] },
  { key: "legal_risk", label: "法务风险", color: "#f6bd16", prefixes: ["LEGAL_"] },
  { key: "equity_risk", label: "股权风险", color: "#9270ca", prefixes: ["EQUITY_"] },
  { key: "business_risk", label: "经营风险", color: "#d48806", prefixes: ["BIZ_"] },
  { key: "market_risk", label: "市场风险", color: "#2ca58d", prefixes: ["MKT_"] },
  { key: "nonstandard_risk", label: "非标风险", color: "#cf6679", prefixes: ["TEXT_"] },
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) =>
    ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    })[char]
  );
}

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function inferMetadata(item) {
  const match = item.filename.match(/^(\d{5})_(\d{2})-(\d{2})-(\d{4})_(.+?)_(全球發售|股份發售)/);
  const now = new Date();
  if (!match) return { company: item.filename.replace(/\.pdf$/i, ""), code: "", cutoff: now };
  const [, code, day, month, year, company] = match;
  const cutoff = new Date(`${year}-${month}-${day}T23:59:00+08:00`);
  return { company, code: `${code}.HK`, cutoff };
}

function localDateTime(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 16);
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function setHtml(id, value) {
  const node = $(id);
  if (node) node.innerHTML = value;
}

function setDisabled(id, disabled) {
  const node = $(id);
  if (node) node.disabled = Boolean(disabled);
}

function getRadarScore(claims, dimension) {
  const related = (claims || []).filter((claim) =>
    dimension.prefixes.some((prefix) => String(claim.risk_code || "").startsWith(prefix))
  );
  const audited = related.filter((claim) => ["accepted", "revised"].includes(claim.audit_status));
  const source = audited.length ? audited : related;
  if (!source.length) return { score: 0, count: 0 };
  const total = source.reduce((sum, claim) => {
    const severity = Math.max(0, Math.min(10, Number(claim.severity) || 0));
    const confidence = Math.max(0, Math.min(1, Number(claim.confidence) || 0));
    return sum + severity * (0.7 + confidence * 0.3);
  }, 0);
  return { score: Math.round(Math.min(10, total / source.length) * 10) / 10, count: source.length };
}

function renderRiskRadar(claims = []) {
  const node = $("riskRadar");
  if (!node) return;
  const width = 430;
  const height = 350;
  const center = { x: 215, y: 175 };
  const radius = 120;
  const angle = (index) => -Math.PI / 2 + (index * Math.PI * 2) / RADAR_DIMENSIONS.length;
  const point = (index, value, distance = radius) => ({
    x: center.x + Math.cos(angle(index)) * distance * (value / 10),
    y: center.y + Math.sin(angle(index)) * distance * (value / 10),
  });
  const polygon = (points) => points.map((item) => item.x.toFixed(1) + "," + item.y.toFixed(1)).join(" ");
  const scores = RADAR_DIMENSIONS.map((dimension) => ({ ...dimension, ...getRadarScore(claims, dimension) }));
  const grid = [2, 4, 6, 8, 10].map((level) =>
    "<polygon points=\"" + polygon(RADAR_DIMENSIONS.map((_, index) => point(index, level))) + "\" class=\"radar-grid\" />"
  ).join("");
  const axes = RADAR_DIMENSIONS.map((_, index) => {
    const end = point(index, 10);
    return "<line x1=\"" + center.x + "\" y1=\"" + center.y + "\" x2=\"" + end.x + "\" y2=\"" + end.y + "\" class=\"radar-axis\" />";
  }).join("");
  const labels = scores.map((dimension, index) => {
    const p = point(index, 10, radius + 31);
    const anchor = Math.abs(p.x - center.x) < 8 ? "middle" : p.x < center.x ? "end" : "start";
    return "<text x=\"" + p.x.toFixed(1) + "\" y=\"" + p.y.toFixed(1) + "\" text-anchor=\"" + anchor + "\" class=\"radar-label\">" + escapeHtml(dimension.label) + "</text>";
  }).join("");
  const values = scores.map((dimension, index) => point(index, dimension.score));
  const dots = values.map((p, index) =>
    "<circle cx=\"" + p.x.toFixed(1) + "\" cy=\"" + p.y.toFixed(1) + "\" r=\"4\" fill=\"" + scores[index].color + "\" class=\"radar-dot\"><title>" + scores[index].label + ": " + scores[index].score + "/10</title></circle>"
  ).join("");
  node.innerHTML = "<svg viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-label=\"六维风险雷达图\"><g>" + grid + axes + "</g><polygon points=\"" + polygon(values) + "\" class=\"radar-area\" />" + dots + labels + "</svg>";
  setHtml("radarLegend", scores.map((dimension) =>
    "<div class=\"radar-legend-row\"><span class=\"radar-swatch\" style=\"background:" + dimension.color + "\"></span><strong>" + dimension.label + "</strong><span>" + dimension.score + "/10 · " + dimension.count + " 条</span></div>"
  ).join(""));
  setText("radarUpdated", claims.length ? "已审计结论" : "暂无风险结论");
}

function showAnalysisView() {
  $("emptyState")?.classList.add("hidden");
  $("analysisView")?.classList.remove("hidden");
}

function switchTab(target) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === target);
  });
  TABS.forEach((name) => {
    const panel = $(`${name}Tab`);
    if (!panel) return;
    panel.classList.toggle("hidden", name !== target);
  });
  if (target === "agentroom") {
    ensureAgentRoomChrome();
    if (state.analysisId) {
      hydrateExistingRoom();
    }
  }
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    const healthDot = $("healthDot");
    if (healthDot) healthDot.className = "dot ok";
    setText("healthText", `${data.prompt_version || "ok"} · 服务正常`);
    state.skills = Array.isArray(data.skills) && data.skills.length ? data.skills : DEFAULT_SKILLS;
    state.providers = data.llm_providers || {};
  } catch (_) {
    const healthDot = $("healthDot");
    if (healthDot) healthDot.className = "dot error";
    setText("healthText", "服务异常");
    state.skills = DEFAULT_SKILLS;
    state.providers = {};
  }
  ensureAgentRoomChrome();
}

async function loadDataset() {
  const query = new URLSearchParams();
  if ($("searchInput")?.value.trim()) query.set("search", $("searchInput").value.trim());
  if ($("yearFilter")?.value) query.set("year", $("yearFilter").value);
  query.set("limit", "180");
  const response = await fetch(`/api/dataset?${query}`);
  const data = await response.json();
  setText(
    "datasetCount",
    data.total > data.count ? `${data.total} 份 · 显示 ${data.count}` : `${data.total || 0} 份`
  );
  setHtml(
    "datasetList",
    (data.items || [])
      .map(
        (item, index) => `
    <button class="dataset-item ${state.selected?.path === item.path ? "active" : ""}" data-index="${index}">
      <strong title="${escapeHtml(item.filename)}">${escapeHtml(item.filename.replace(/\.pdf$/i, ""))}</strong>
      <span><em>${item.year ?? "—"}</em><em>${formatBytes(item.size_bytes)}</em></span>
    </button>`
      )
      .join("") || '<div class="notice">没有匹配的 PDF。</div>'
  );
  [...document.querySelectorAll(".dataset-item")].forEach((button) =>
    button.addEventListener("click", () => selectDataset(data.items[Number(button.dataset.index)]))
  );
}

function selectDataset(item) {
  state.selected = item;
  const meta = inferMetadata(item);
  if ($("companyName")) $("companyName").value = meta.company;
  if ($("stockCode")) $("stockCode").value = meta.code;
  if ($("predictionAsOf")) $("predictionAsOf").value = localDateTime(meta.cutoff);
  if ($("listingDate")) $("listingDate").value = "";
  if ($("issuePrice")) $("issuePrice").value = "";
  validateRunForm();
  loadDataset();
}

function validateRunForm() {
  const complete =
    state.selected &&
    $("companyName")?.value.trim() &&
    $("stockCode")?.value.trim() &&
    $("listingDate")?.value &&
    $("predictionAsOf")?.value &&
    Number($("issuePrice")?.value) > 0;
  setDisabled("runAnalysis", !complete);
}

async function runAnalysis() {
  if (!state.selected) return;
  const payload = {
    company_name: $("companyName").value.trim(),
    stock_code: $("stockCode").value.trim(),
    listing_date: $("listingDate").value,
    issue_price: Number($("issuePrice").value),
    prediction_as_of: new Date($("predictionAsOf").value).toISOString(),
    pdf_path: state.selected.path,
    mode: $("mode").value,
  };
  setDisabled("runAnalysis", true);
  const response = await fetch("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    alert(data.detail || "创建任务失败");
    setDisabled("runAnalysis", false);
    return;
  }
  state.analysisId = data.analysis_id;
  state.roomSessionId = null;
  sessionStorage.setItem("hkipo_last_analysis_id", state.analysisId);
  showAnalysisView();
  setText("analysisTitle", payload.company_name);
  setText("analysisCode", `${payload.stock_code} · ${payload.mode}`);
  resetAgentRoomUI("分析进行中，完成后可启动会诊");
  ensureAgentRoomChrome();
  await refreshAnalysis();
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refreshAnalysis, 1500);
}

async function refreshAnalysis() {
  if (!state.analysisId) return;
  const response = await fetch(`/api/analyses/${state.analysisId}`);
  if (!response.ok) return;
  const data = await response.json();
  state.analysisStatus = data.status;
  renderAnalysis(data);
  if (["completed", "failed"].includes(data.status)) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    setDisabled("runAnalysis", false);
    await loadDetails();
    if (data.status === "completed") {
      setDisabled("startAgentRoom", false);
      setDisabled("refreshAgentRoom", false);
      setText("roomSessionMeta", "分析已完成，点击「启动会诊」开始投行多智能体讨论");
      ensureAgentRoomChrome();
      await hydrateExistingRoom();
    }
  }
}

function renderAnalysis(data) {
  showAnalysisView();
  const progressBar = $("progressBar");
  if (progressBar) progressBar.style.width = `${data.progress || 0}%`;
  setText("progressText", `${data.progress || 0}%`);
  setText("stageText", data.stage || "—");
  setText(
    "taskStatus",
    data.status === "completed" ? "已完成" : data.status === "failed" ? "失败" : data.stage || data.status
  );
  const taskStatus = $("taskStatus");
  if (taskStatus) taskStatus.className = `status ${data.status || ""}`;
  if (data.report_url && $("reportLink")) {
    $("reportLink").href = data.report_url;
    $("reportLink").classList.remove("hidden");
  }
  const prediction = data.prediction;
  if (prediction?.probabilities) {
    setText("probabilityMetric", `${(prediction.probabilities.p_5d_drop * 100).toFixed(1)}%`);
    setText("probabilityNote", prediction.model_version || "model");
  } else if (prediction) {
    setText("probabilityMetric", "不可用");
    setText("probabilityNote", "未注册校准模型");
  }
  setText("ruleMetric", prediction ? Number(prediction.rule_score || 0).toFixed(1) : "—");
  const accepted = data.claim_counts?.accepted || 0;
  const revised = data.claim_counts?.revised || 0;
  setText("claimMetric", prediction ? String(accepted + revised) : "—");
  setText("claimNote", `${accepted} 接受 · ${revised} 修订`);
  setText("evidenceMetric", String(data.evidence_count || "—"));
  setText("injectionNote", `注入检测 ${data.injection_count || 0}`);
  const hits = prediction?.rule_hits || [];
  setText("ruleCount", String(hits.length));
  setHtml(
    "ruleHits",
    hits.length
      ? hits.map((item) => `<span>${escapeHtml(item)}</span>`).join("")
      : '<span class="muted">暂无重大规则命中</span>'
  );
  setText(
    "modelStatus",
    prediction?.probabilities
      ? `模型 ${prediction.model_version}，校准 ${prediction.calibration_version || "—"}`
      : prediction
        ? "模型结果不可用。规则命中已保留，系统未伪造概率。"
        : "等待模型门禁"
  );
  const modelStatus = $("modelStatus");
  if (modelStatus) modelStatus.className = `notice ${prediction?.probabilities ? "ok" : ""}`;
  const meta = data.parse_metadata || {};
  setHtml(
    "parseSummary",
    [
      ["页数", meta.pages ? `${meta.parsed_pages}/${meta.pages}` : "—"],
      ["证据块", meta.evidence_count ?? "—"],
      ["低文本页", meta.low_text_pages?.length ?? "—"],
      ["解析器", meta.parser_version ?? "—"],
    ]
      .map(
        ([label, value]) =>
          `<div class="definition"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`
      )
      .join("")
  );
  if (data.error) setText("modelStatus", data.error);
  setText("analysisTitle", data.company_name || $("analysisTitle")?.textContent || "分析任务");
  setText("analysisCode", `${data.stock_code || "—"} · ${data.mode || "—"}`);
}

async function loadDetails() {
  if (!state.analysisId) return;
  const [claims, evidence, traces] = await Promise.all([
    fetch(`/api/analyses/${state.analysisId}/claims`).then((r) => r.json()),
    fetch(`/api/analyses/${state.analysisId}/evidence?limit=160`).then((r) => r.json()),
    fetch(`/api/analyses/${state.analysisId}/traces`).then((r) => r.json()),
  ]);
  renderRiskRadar(claims.items || []);
  setHtml(
    "claimsTable",
    `<table><thead><tr><th>风险代码</th><th>结论</th><th>严重度</th><th>置信度</th><th>审计</th><th>责任 Agent</th></tr></thead><tbody>${(
      claims.items || []
    )
      .map(
        (c) =>
          `<tr><td><strong>${escapeHtml(c.risk_code)}</strong></td><td>${escapeHtml(c.claim)}<br><small>${escapeHtml(
            c.audit_reason || ""
          )}</small></td><td>${c.severity}/10</td><td>${((c.confidence || 0) * 100).toFixed(
            0
          )}%</td><td class="audit ${c.audit_status}">${escapeHtml(c.audit_status)}</td><td>${escapeHtml(
            c.owner_agent || ""
          )}</td></tr>`
      )
      .join("")}</tbody></table>`
  );
  setHtml(
    "evidenceList",
    (evidence.items || [])
      .map(
        (ev) =>
          `<article class="evidence-row ${ev.injection_like_text ? "injection" : ""}"><header><strong>第 ${
            ev.page
          } 页 · ${escapeHtml((ev.section_path || []).join(" / "))}</strong><a href="${
            ev.screenshot_uri || "#"
          }" target="_blank">查看截图</a></header><p>${escapeHtml(ev.text || "")}</p></article>`
      )
      .join("") || '<div class="muted">暂无证据</div>'
  );
  setHtml(
    "traceList",
    (traces.items || [])
      .map(
        (t) =>
          `<article class="trace-row"><header><strong>${escapeHtml(t.agent_name)}</strong><span>${escapeHtml(
            t.status
          )}</span></header><p>${escapeHtml(t.decision_summary || "")}</p><div class="trace-tools">工具：${
            (t.tool_calls || []).map((x) => escapeHtml(x.tool_name)).join("、") || "无"
          } · claims ${(t.claims || []).length} · gaps ${(t.data_gaps || []).length}</div></article>`
      )
      .join("") || '<div class="muted">暂无 trace</div>'
  );
}

function ensureAgentRoomChrome() {
  renderSkillRoster();
  renderProviderStatus();
  const canStart = Boolean(state.analysisId && state.analysisStatus === "completed");
  const busy = ["queued", "running"].includes(state.roomStatus || "");
  setDisabled("startAgentRoom", !canStart || busy);
  setDisabled("refreshAgentRoom", !state.analysisId);
  setDisabled("askAgentBtn", !state.roomSessionId);
  if (!$("agentTimeline")?.dataset.ready) {
    setHtml(
      "agentTimeline",
      `<div class="room-empty">
        <strong>投行多智能体会诊室</strong>
        <p>分析完成后点左侧「启动会诊」。系统将依次呼叫财务、法务、股权、经营、市场与非标六大 Agent，在同一时间线中展示协作过程。</p>
      </div>`
    );
    if ($("agentTimeline")) $("agentTimeline").dataset.ready = "1";
  }
}

function renderSkillRoster() {
  const items = state.skills?.length ? state.skills : DEFAULT_SKILLS;
  setText("skillCount", String(items.length));
  setHtml(
    "skillRoster",
    items
      .map((skill) => {
        const color = skill.role_color || SKILL_COLORS[skill.skill_id] || "#5b8ff9";
        const provider = skill.default_provider || "llm";
        return `<article class="skill-card" data-skill="${escapeHtml(skill.skill_id)}" style="--skill-color:${color}">
        <div class="skill-avatar">${escapeHtml((skill.label || "?").slice(0, 1))}</div>
        <div>
          <strong>${escapeHtml(skill.label || skill.skill_id)}</strong>
          <p>${escapeHtml(skill.description || "可扩展 Skill")}</p>
          <small>Skill · ${escapeHtml(skill.skill_id)} · ${escapeHtml(provider)}</small>
        </div>
      </article>`;
      })
      .join("")
  );
}

function renderProviderStatus() {
  const providers = state.providers || {};
  const rows = [
    ["DeepSeek", providers.deepseek],
  ];
  setHtml(
    "providerStatus",
    rows
      .map(([name, info]) => {
        const ok = Boolean(info?.ready ?? info?.configured);
        const note = info?.note ? ` · ${info.note}` : "";
        const label = ok ? "已就绪" : "未配置 / 将离线降级";
        return `<div class="provider-row ${ok ? "ok" : "warn"}">
        <strong>${name}</strong>
        <span>${label} · ${escapeHtml(info?.model || "—")}${escapeHtml(note)}</span>
      </div>`;
      })
      .join("") || '<div class="provider-row warn"><strong>模型通道</strong><span>等待健康检查</span></div>'
  );
}

function resetAgentRoomUI(message) {
  state.roomSessionId = null;
  state.roomStatus = null;
  const bar = $("roomProgressBar");
  if (bar) bar.style.width = "0%";
  setText("roomProgressText", "0%");
  setText("roomStageText", "待命");
  setText("roomMessageCount", "0 条");
  if ($("agentTimeline")) $("agentTimeline").dataset.ready = "";
  setHtml(
    "agentTimeline",
    `<div class="room-empty">
      <strong>等待会诊开始</strong>
      <p>${escapeHtml(message || "分析完成后可启动多智能体会诊")}</p>
    </div>`
  );
  const board = $("decisionBoard");
  if (board) {
    board.className = "decision-content muted";
    board.textContent = "六大 Agent 会诊结论将显示在这里";
  }
  setDisabled("askAgentBtn", true);
  setDisabled("startAgentRoom", true);
  setDisabled("refreshAgentRoom", true);
  setText("roomSessionMeta", message || "分析完成后可启动多智能体会诊");
  ensureAgentRoomChrome();
}

function markActiveSkills(messages = [], stage = "") {
  const spoken = new Set(messages.filter((m) => m.role === "agent").map((m) => m.skill_id));
  document.querySelectorAll(".skill-card").forEach((card) => {
    const skillId = card.dataset.skill;
    const label = card.querySelector("strong")?.textContent || "";
    card.classList.toggle("spoken", spoken.has(skillId));
    card.classList.toggle("speaking", Boolean(stage) && stage.includes(label));
  });
}

function cleanAgentText(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractHighlightItems(msg) {
  const source = msg || {};
  const payload = source.payload || {};
  const pickArr = (key) => {
    const value = Array.isArray(source[key]) ? source[key] : Array.isArray(payload[key]) ? payload[key] : [];
    return value.map((x) => (typeof x === "string" ? x : x?.text || "")).filter(Boolean);
  };
  const risks = pickArr("risks");
  const findings = pickArr("findings");
  const recommendations = pickArr("recommendations");
  const questions = pickArr("questions");

  if (risks.length || findings.length || recommendations.length) {
    return { risks: risks.slice(0, 4), findings: findings.slice(0, 4), recommendations: recommendations.slice(0, 4), questions: questions.slice(0, 3) };
  }

  const content = cleanAgentText(msg.content);
  const sections = {};
  const pattern = /^(?:#{1,6}\s*|【\s*)([^#【】\n]{1,30}?)(?:\s*】|\s*[:：]?\s*)$/gm;
  const matches = [...content.matchAll(pattern)];
  if (matches.length) {
    matches.forEach((match, index) => {
      const title = match[1].trim();
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index : content.length;
      sections[title] = content.slice(start, end).trim();
    });
  }
  const pick = (...names) => {
    for (const name of names) {
      if (sections[name]) return sections[name];
    }
    return "";
  };
  const toItems = (block) =>
    cleanAgentText(block)
      .split("\n")
      .map((line) => line.replace(/^(?:[-*•]+|\d+[\.、\)]\s+|\(\d+\)\s+|（\d+）\s+)/, "").trim())
      .filter((line) => line && line !== "无" && !/^#{1,6}/.test(line) && !/^好的[，,]|^收到|^作为/.test(line))
      .slice(0, 4);

  return {
    findings: toItems(pick("关键发现", "关键风险", "缓释证据", "冲突裁决")),
    risks: toItems(pick("主要风险", "主要风险排序", "风险")),
    recommendations: toItems(pick("建议", "后续动作", "给总控的建议")),
    questions: toItems(pick("数据缺口", "冲突与缺口")),
  };
}

function renderHighlightList(title, items, cls = "") {
  if (!items?.length) return "";
  return `<div class="highlight-block ${cls}">
    <h4>${escapeHtml(title)}</h4>
    <ul>${items.map((item) => `<li>${escapeHtml(String(item).slice(0, 120))}</li>`).join("")}</ul>
  </div>`;
}

function formatDecisionHighlights(text) {
  const fakeMsg = { content: text, risks: [], findings: [], recommendations: [], questions: [] };
  const parts = extractHighlightItems(fakeMsg);
  const summary = cleanAgentText(text)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !/^#{1,6}/.test(line) && !/^【/.test(line) && !/^好的[，,]|^收到|^作为/.test(line))[0] || cleanAgentText(text).slice(0, 160);
  return {
    summary: summary.slice(0, 180),
    html: [
      `<p class="decision-summary">${escapeHtml(summary.slice(0, 180))}</p>`,
      renderHighlightList("主要风险", parts.risks, "risk"),
      renderHighlightList("关键发现", parts.findings),
      renderHighlightList("建议", parts.recommendations, "action"),
    ].join(""),
  };
}

function renderAgentMessageCard(msg) {
  const color = SKILL_COLORS[msg.skill_id] || (msg.role === "user" ? "#6c8cff" : "#98a2b3");
  const badge = msg.provider ? `${msg.provider}/${msg.model || ""}` : msg.role;
  const highlights = extractHighlightItems(msg);
  const summary = cleanAgentText(msg.summary || highlights.findings[0] || highlights.risks[0] || "").slice(0, 180);
  const raw = cleanAgentText(msg.content || "");
  const showRaw = raw && raw !== summary;
  const statusClass = msg.status === "degraded" ? "is-degraded" : msg.status === "failed" ? "is-failed" : "is-success";
  return `<article class="timeline-item role-${escapeHtml(msg.role || "system")} ${statusClass}" style="--agent-color:${color}">
    <header>
      <div>
        <strong>${escapeHtml(msg.title || msg.agent_name || msg.role || "message")}</strong>
        <span class="pill">${escapeHtml(badge)}</span>
      </div>
      <small>${escapeHtml(msg.status || "")} · #${msg.seq ?? "-"}</small>
    </header>
    <p class="summary">${escapeHtml(summary || "（无摘要）")}</p>
    <div class="highlight-grid">
      ${renderHighlightList("关键发现", highlights.findings)}
      ${renderHighlightList("主要风险", highlights.risks, "risk")}
      ${renderHighlightList("建议", highlights.recommendations, "action")}
      ${renderHighlightList("待确认", highlights.questions, "gap")}
    </div>
    ${
      showRaw
        ? `<details class="raw-details"><summary>查看完整原文</summary><pre>${escapeHtml(raw)}</pre></details>`
        : ""
    }
  </article>`;
}
function renderAgentSession(session) {
  if (!session) return;
  ensureAgentRoomChrome();
  state.roomSessionId = session.session_id;
  state.roomStatus = session.status;
  const bar = $("roomProgressBar");
  if (bar) bar.style.width = `${session.progress || 0}%`;
  setText("roomProgressText", `${session.progress || 0}%`);
  setText("roomStageText", session.stage || session.status || "—");
  setText("roomSessionMeta", `${session.title || session.session_id} · ${session.status}`);
  setDisabled("refreshAgentRoom", false);
  setDisabled("startAgentRoom", ["running", "queued"].includes(session.status) || state.analysisStatus !== "completed");
  setDisabled("askAgentBtn", !["completed", "running"].includes(session.status));

  const messages = session.messages || [];
  setText("roomMessageCount", `${messages.length} 条`);
  if ($("agentTimeline")) $("agentTimeline").dataset.ready = "1";
  setHtml(
    "agentTimeline",
    messages.length
      ? messages.map((msg) => renderAgentMessageCard(msg)).join("")
      : `<div class="room-empty"><strong>暂无消息</strong><p>会诊已创建，等待 Agent 发言…</p></div>`
  );

  const board = $("decisionBoard");
  if (board) {
    if (session.decision) {
      board.className = "decision-content";
      const decisionView = formatDecisionHighlights(session.decision);
      board.innerHTML = decisionView.html || `<p class="decision-summary">${escapeHtml(decisionView.summary)}</p>`;
    } else {
      board.className = "decision-content muted";
      board.textContent = "六大 Agent 会诊结论将显示在这里";
    }
  }
  markActiveSkills(messages, session.stage || "");
}
async function hydrateExistingRoom() {
  if (!state.analysisId) return;
  try {
    const response = await fetch(
      `/api/agent-room/sessions?analysis_id=${encodeURIComponent(state.analysisId)}&limit=1`
    );
    if (!response.ok) return;
    const data = await response.json();
    const latest = (data.items || [])[0];
    if (!latest) {
      ensureAgentRoomChrome();
      return;
    }
    const detail = await fetch(`/api/agent-room/sessions/${latest.session_id}`).then((r) => r.json());
    renderAgentSession(detail);
    if (["queued", "running"].includes(detail.status)) startRoomPolling();
  } catch (error) {
    console.warn("hydrateExistingRoom failed", error);
    ensureAgentRoomChrome();
  }
}

async function startAgentRoom() {
  if (!state.analysisId) {
    alert("请先完成一次分析");
    return;
  }
  if (state.analysisStatus !== "completed") {
    alert("请等待分析完成后再启动会诊");
    return;
  }
  setDisabled("startAgentRoom", true);
  setText("roomStageText", "创建会诊…");
  try {
    const response = await fetch("/api/agent-room/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis_id: state.analysisId,
        auto_start: true,
        skill_ids: [
          "financial_risk",
          "legal_risk",
          "equity_risk",
          "business_risk",
          "market_risk",
          "nonstandard_risk",
        ],
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      alert(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "启动会诊失败"));
      setDisabled("startAgentRoom", false);
      return;
    }
    renderAgentSession(data);
    startRoomPolling();
  } catch (error) {
    alert(`启动会诊失败: ${error}`);
    setDisabled("startAgentRoom", false);
  }
}

function startRoomPolling() {
  if (state.roomPollTimer) clearInterval(state.roomPollTimer);
  state.roomPollTimer = setInterval(refreshAgentRoom, 2000);
}

async function refreshAgentRoom() {
  try {
    if (!state.roomSessionId) {
      await hydrateExistingRoom();
      return;
    }
    const response = await fetch(`/api/agent-room/sessions/${state.roomSessionId}`);
    if (!response.ok) return;
    const data = await response.json();
    renderAgentSession(data);
    if (["completed", "failed"].includes(data.status)) {
      clearInterval(state.roomPollTimer);
      state.roomPollTimer = null;
      setDisabled("startAgentRoom", state.analysisStatus !== "completed");
    }
  } catch (error) {
    console.warn("refreshAgentRoom failed", error);
  }
}

async function askAgent(event) {
  event.preventDefault();
  if (!state.roomSessionId) {
    alert("请先启动会诊室");
    return;
  }
  const question = $("askQuestion")?.value.trim();
  if (!question) return;
  setDisabled("askAgentBtn", true);
  try {
    const response = await fetch(`/api/agent-room/sessions/${state.roomSessionId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        skill_id: $("askSkill")?.value || "financial_risk",
        question,
      }),
    });
    const data = await response.json();
    setDisabled("askAgentBtn", false);
    if (!response.ok) {
      alert(typeof data.detail === "string" ? data.detail : "追问失败");
      return;
    }
    if ($("askQuestion")) $("askQuestion").value = "";
    renderAgentSession(data);
  } catch (error) {
    setDisabled("askAgentBtn", false);
    alert(`追问失败: ${error}`);
  }
}

async function restoreLastAnalysis() {
  const lastId = sessionStorage.getItem("hkipo_last_analysis_id");
  if (!lastId) return;
  state.analysisId = lastId;
  showAnalysisView();
  await refreshAnalysis();
  if (state.analysisStatus && !["completed", "failed"].includes(state.analysisStatus)) {
    state.pollTimer = setInterval(refreshAnalysis, 1500);
  }
}

function bindUi() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  let searchTimer;
  $("searchInput")?.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadDataset, 250);
  });
  $("yearFilter")?.addEventListener("change", loadDataset);
  $("refreshDataset")?.addEventListener("click", loadDataset);
  $("runAnalysis")?.addEventListener("click", runAnalysis);
  $("startAgentRoom")?.addEventListener("click", startAgentRoom);
  $("refreshAgentRoom")?.addEventListener("click", refreshAgentRoom);
  $("agentAskForm")?.addEventListener("submit", askAgent);
  ["companyName", "stockCode", "listingDate", "issuePrice", "predictionAsOf"].forEach((id) =>
    $(id)?.addEventListener("input", validateRunForm)
  );
}

async function boot() {
  bindUi();
  resetAgentRoomUI("分析完成后可启动多智能体会诊");
  ensureAgentRoomChrome();
  await loadHealth();
  await loadDataset();
  await restoreLastAnalysis();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
