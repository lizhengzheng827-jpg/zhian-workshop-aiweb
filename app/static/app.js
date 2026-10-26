const state = {data: null, selected: null};
const $ = (id) => document.getElementById(id);

function toast(message) { const el = $("toast"); el.textContent = message; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2800); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c])); }

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach((item) => item.classList.remove("active"));
  button.classList.add("active"); $(button.dataset.tab + "Pane").classList.add("active");
}));
$("dropzone").addEventListener("click", () => $("zipInput").click());
$("zipInput").addEventListener("change", () => { $("scanZip").disabled = !$("zipInput").files.length; });

async function postJson(url, body) { const response = await fetch(url, {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)}); const data = await response.json(); if (!response.ok) throw new Error(data.error || "请求失败"); return data; }

$("scanText").addEventListener("click", async () => {
  const content = $("codeInput").value;
  if (!content.trim()) return toast("请先粘贴代码");
  setBusy($("scanText"), true);
  try { renderResult(await postJson("/api/scan/text", {file_name: $("fileName").value, content})); toast("检测完成"); } catch (error) { toast(error.message); } finally { setBusy($("scanText"), false); }
});
$("scanZip").addEventListener("click", async () => {
  const file = $("zipInput").files[0]; if (!file) return toast("请先选择 ZIP 文件");
  const form = new FormData(); form.append("file", file); setBusy($("scanZip"), true);
  try { const response = await fetch("/api/scan/zip", {method: "POST", body: form}); const data = await response.json(); if (!response.ok) throw new Error(data.error); renderResult(data); toast("检测完成"); } catch (error) { toast(error.message); } finally { setBusy($("scanZip"), false); }
});
$("reportBtn").addEventListener("click", () => { if (state.data) window.location.href = "/api/report.pdf"; });
$("planBtn").addEventListener("click", async () => { if (!state.data) return; const button = $("planBtn"); button.disabled = true; button.textContent = "生成中..."; try { const response = await fetch("/api/project/remediation-plan", {method: "POST"}); const plan = await response.json(); if (!response.ok) throw new Error(plan.error || "生成失败"); $("planResult").classList.remove("hidden"); $("planResult").innerHTML = `<strong>${esc(plan.title || "项目级整改计划")} · ${esc(plan.source || "")}</strong>${esc(plan.advice)}\n\n${esc(plan.example)}\n\n${esc(plan.privacy_note)}`; } catch (error) { toast(error.message); } finally { button.disabled = false; button.textContent = "重新生成项目整改计划"; } });

function setBusy(button, busy) { button.disabled = busy; if (busy) button.dataset.original = button.innerHTML, button.innerHTML = "检测中..."; else button.innerHTML = button.dataset.original || button.innerHTML; }

function renderResult(data) {
  state.data = data; state.selected = data.findings[0] || null; $("emptyState").classList.add("hidden"); $("results").classList.remove("hidden");
  const summary = data.summary; $("sourceName").textContent = data.source_name || "代码片段"; $("scanMeta").textContent = `${summary.files} 个文件 · ${summary.lines} 行代码 · ${new Date().toLocaleString("zh-CN")}`; $("score").textContent = summary.score; $("findingCount").textContent = summary.findings; $("pendingCount").textContent = data.findings.filter((item) => item.status === "待确认").length; $("fileCount").textContent = summary.files; $("filterSummary").textContent = `${summary.findings} 条风险线索`; renderInsights(data); renderFindings(); if (state.selected) selectFinding(state.selected.id); else { $("codeView").textContent = "未发现风险代码"; $("selectedLocation").textContent = "无风险"; }
}

function renderInsights(data) {
  const dependencies = data.dependencies || {};
  const git = data.git_evidence || {};
  const dependencyClass = dependencies.unpinned_count ? "warn" : "good";
  const gitText = git.included ? `${git.commit_count} 次提交，${git.author_count} 位作者` : "上传包未包含 .git";
  $("insightContent").innerHTML = `<div class="insight-row"><span>依赖清单</span><strong>${dependencies.dependency_count || 0} 项</strong></div><div class="insight-row"><span>版本卫生</span><strong class="${dependencyClass}">${dependencies.unpinned_count || 0} 项需核查</strong></div><div class="insight-row"><span>Git 开发证据</span><strong>${esc(gitText)}</strong></div><div class="insight-row"><span>安全边界</span><strong>仅检测，不改源码</strong></div>`;
  $("planBtn").disabled = false;
  loadHistory();
}

async function loadHistory() {
  try {
    const history = await (await fetch("/api/history")).json();
    $("historyCount").textContent = `${history.length} 次`;
    if (!history.length) return;
    $("historyList").innerHTML = history.map((item, index) => `<div class="history-item"><div class="history-title">${esc(item.source_name || "代码片段")}</div><div class="history-meta">${esc(item.created_at || "")} · 评分 ${item.summary.score} · 风险 ${item.summary.findings}</div>${index === 0 ? "" : `<div class="history-delta" data-compare-id="${esc(item.scan_id)}">点击与本次结果对比</div>`}</div>`).join("");
    document.querySelectorAll("[data-compare-id]").forEach((el) => el.addEventListener("click", async (event) => { event.stopPropagation(); const current = history[0]; try { const result = await (await fetch(`/api/history/compare?from=${encodeURIComponent(el.dataset.compareId)}&to=${encodeURIComponent(current.scan_id)}`)).json(); if (!result.error) toast(`对比完成：新增 ${result.new_count} 条，已消失 ${result.resolved_count} 条，评分变化 ${result.score_delta >= 0 ? "+" : ""}${result.score_delta}`); } catch (_) { toast("暂时无法完成对比"); } }));
  } catch (_) { $("historyList").innerHTML = '<span class="muted">历史记录暂时不可用</span>'; }
}

function renderFindings() {
  const list = $("findingList");
  if (!state.data.findings.length) { list.innerHTML = '<div class="finding-item"><div class="finding-title">未发现敏感信息泄露线索</div><div class="finding-meta">可以继续进行人工复核</div></div>'; return; }
  list.innerHTML = state.data.findings.map((item) => `<div class="finding-item" data-id="${esc(item.id)}"><div class="finding-row"><span class="finding-title">${esc(item.category)}</span><span class="level level-${esc(item.severity)}">${esc(item.severity)}风险</span></div><div class="finding-meta">${esc(item.file_name)} · 第 ${item.line_number} 行 · 置信度 ${item.confidence}%</div><select class="status-select" data-status-id="${esc(item.id)}"><option ${item.status === "待确认" ? "selected" : ""}>待确认</option><option ${item.status === "已确认" ? "selected" : ""}>已确认</option><option ${item.status === "误报" ? "selected" : ""}>误报</option><option ${item.status === "已修复" ? "selected" : ""}>已修复</option><option ${item.status === "忽略本次" ? "selected" : ""}>忽略本次</option></select></div>`).join("");
  document.querySelectorAll(".finding-item").forEach((item) => item.addEventListener("click", (event) => { if (event.target.matches("select")) return; selectFinding(item.dataset.id); }));
  document.querySelectorAll("[data-status-id]").forEach((select) => select.addEventListener("change", async (event) => { event.stopPropagation(); try { const updated = await postJson(`/api/findings/${select.dataset.statusId}/status`, {status: select.value}); renderResult(updated); toast("状态已更新"); } catch (error) { toast(error.message); } }));
}

function selectFinding(id) {
  const finding = state.data.findings.find((item) => item.id === id); if (!finding) return; state.selected = finding;
  document.querySelectorAll(".finding-item").forEach((item) => item.classList.toggle("active", item.dataset.id === id)); $("selectedLocation").textContent = `${finding.file_name} · 第 ${finding.line_number} 行`; $("codeCategory").textContent = `${finding.severity}风险 · ${finding.category}`; $("codeLine").textContent = `行号 ${finding.line_number}`; $("codeView").innerHTML = `<span class="line-no">${finding.line_number}</span><span class="risk-line">${esc(finding.code_line)}</span>`; $("adviceCard").classList.remove("hidden"); $("adviceSource").textContent = "内置建议"; $("adviceText").textContent = finding.recommendation; $("exampleCode").textContent = finding.example_code;
  const askButton = document.createElement("button"); askButton.className = "outline-btn"; askButton.textContent = "使用 DeepSeek 优化建议"; askButton.style.margin = "14px 15px 0"; askButton.onclick = async () => { askButton.disabled = true; askButton.textContent = "生成中..."; try { const advice = await (await fetch(`/api/findings/${finding.id}/advice`, {method: "POST"})).json(); $("adviceSource").textContent = advice.source; $("adviceText").textContent = advice.advice; $("exampleCode").textContent = advice.example; toast(advice.privacy_note); } finally { askButton.disabled = false; askButton.textContent = "使用 DeepSeek 优化建议"; } }; const old = $("adviceCard").querySelector("button"); if (old) old.remove(); $("adviceCard").appendChild(askButton);
}

async function loadStatus() { try { const data = await (await fetch("/api/status")).json(); $("providerStatus").textContent = data.provider.configured ? `DeepSeek 建议：${data.provider.model}` : "DeepSeek 建议：未配置"; if (data.scan) renderResult(data.scan); } catch (_) {} }
loadStatus();

