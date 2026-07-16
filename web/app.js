const state = {
  view: "overview",
  profiles: [],
  capabilities: null,
  selectedAccount: localStorage.getItem("redditBotAccount") || "all",
};

const viewEl = document.getElementById("view");
const toastEl = document.getElementById("toast");
const profileSelect = document.getElementById("profileSelect");
const profileMeta = document.getElementById("profileMeta");

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function accountQuery(params = {}) {
  const query = new URLSearchParams(params);
  if (state.selectedAccount && state.selectedAccount !== "all") {
    query.set("account", state.selectedAccount);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

function writeToken() {
  const meta = document.querySelector('meta[name="reddit-bot-ui-token"]');
  const fromMeta = (meta?.getAttribute("content") || "").trim();
  if (fromMeta) return fromMeta;
  return (localStorage.getItem("redditBotUiToken") || "").trim();
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const method = String(options.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    const token = writeToken();
    if (token) {
      headers["X-Reddit-Bot-Token"] = token;
    }
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function toast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toastEl._timer);
  toastEl._timer = setTimeout(() => {
    toastEl.hidden = true;
  }, 4200);
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function short(value, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function badge(value) {
  const normalized = String(value || "").toLowerCase();
  let cls = "";
  if (["active", "queued", "succeeded", "success", "running"].includes(normalized)) cls = "ok";
  if (["failed", "fail", "paused"].includes(normalized)) cls = "fail";
  if (["pending", "reserved"].includes(normalized)) cls = "wait";
  return `<span class="badge ${cls}">${esc(value || "-")}</span>`;
}

function progress(count, quota) {
  const numericQuota = Number(quota || 0);
  const numericCount = Number(count || 0);
  const percent = numericQuota > 0 ? Math.min(100, Math.round((numericCount / numericQuota) * 100)) : 0;
  const cls = numericQuota > 0 && numericCount >= numericQuota ? "over" : percent >= 80 ? "warn" : "";
  return `
    <div class="progress" title="${numericCount}/${numericQuota || "no quota"}">
      <div class="progress-fill ${cls}" style="width: ${percent}%"></div>
    </div>
  `;
}

function table(headers, rows, empty = "No rows.") {
  if (!rows.length) return `<div class="table-wrap"><div class="empty">${esc(empty)}</div></div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${esc(header)}</th>`).join("")}</tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>
  `;
}

function accountLabel(profile) {
  const account = profile.accountLabel || profile.redditUsername || profile.profileName;
  const reddit = profile.redditUsername ? ` (u/${profile.redditUsername})` : "";
  const suffix = profile.isDefault ? " default" : "";
  return `${account}${reddit}${suffix}`;
}

function selectedProfile() {
  return state.profiles.find((profile) => profile.accountLabel === state.selectedAccount);
}

function identityForValue(value) {
  const profile = state.profiles.find((item) => item.accountLabel === value);
  if (profile?.accountLabel) return { account_label: profile.accountLabel };
  if (profile?.profileName) return { profile_name: profile.profileName };
  return {};
}

function renderProfilePicker() {
  const options = [
    `<option value="all">All profiles</option>`,
    ...state.profiles.map((profile) => {
      const value = profile.accountLabel || profile.profileName;
      return `<option value="${esc(value)}">${esc(accountLabel(profile))}</option>`;
    }),
  ];
  profileSelect.innerHTML = options.join("");
  if (![...profileSelect.options].some((option) => option.value === state.selectedAccount)) {
    state.selectedAccount = "all";
  }
  profileSelect.value = state.selectedAccount;
  const profile = selectedProfile();
  if (state.selectedAccount === "all") {
    profileMeta.textContent = "Aggregate view across saved accounts.";
  } else {
    const debug = profile?.configuredDebugAddress || profile?.suggestedDebugAddress || "no debug address";
    profileMeta.textContent = `${profile?.profileName || state.selectedAccount} - ${debug}`;
  }
}

function setupEvents() {
  profileSelect.addEventListener("change", () => {
    state.selectedAccount = profileSelect.value;
    localStorage.setItem("redditBotAccount", state.selectedAccount);
    renderProfilePicker();
    renderView();
  });

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      renderView();
    });
  });
}

async function renderOverview() {
  viewEl.innerHTML = `<div class="message">Loading overview...</div>`;
  const payload = await api(`/api/overview${accountQuery()}`);
  const data = payload.data;
  const counts = data.queueCounts || {};
  const today = data.today || {};
  const executor = data.executor || {};
  const next = data.nextSchedule;
  viewEl.innerHTML = `
    <section class="grid">
      <div class="metric">
        <div class="metric-label">Queue</div>
        <div class="metric-value">${Number(counts.queued || 0) + Number(counts.running || 0)}</div>
        <div class="metric-detail">queued ${counts.queued || 0}, running ${counts.running || 0}, failed ${counts.failed || 0}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Today</div>
        <div class="metric-value">${today.action_count || 0}</div>
        <div>${progress(today.action_count || 0, today.daily_action_quota)}</div>
        <div class="metric-detail">quota ${today.daily_action_quota || "not set"}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Next schedule</div>
        <div class="metric-value">${next ? esc(next.status) : "-"}</div>
        <div class="metric-detail">${next ? `${esc(next.name)} at ${esc(formatDate(next.next_run_at))}` : "No upcoming active schedule"}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Executor</div>
        <div class="metric-value">${executor.running ? "Running" : "Stopped"}</div>
        <div class="metric-detail">${executor.method || "-"}; recent errors ${data.recentErrorCount || 0}</div>
      </div>
    </section>
  `;
}

async function renderSchedule() {
  viewEl.innerHTML = `<div class="message">Loading schedules...</div>`;
  const payload = await api(`/api/schedules${accountQuery()}`);
  const schedules = payload.data.registeredSchedules || [];
  const rows = schedules.map((item) => `
    <tr>
      <td>${esc(item.name || item.id)}</td>
      <td>${esc(item.humanCadence || item.rrule)}</td>
      <td>${esc(formatDate(item.next_run_at))}</td>
      <td>${esc(formatDate(item.last_run_at))}</td>
      <td>${badge(item.status)}</td>
      <td>${esc(item.account || "-")}</td>
      <td>${esc(item.last_error || "-")}</td>
      <td>
        <div class="actions">
          <button data-schedule="${esc(item.id)}" data-action="${item.status === "ACTIVE" ? "pause" : "resume"}" type="button">${item.status === "ACTIVE" ? "Pause" : "Resume"}</button>
          <button data-schedule="${esc(item.id)}" data-action="delete" class="danger" type="button">Delete</button>
        </div>
      </td>
    </tr>
  `);
  viewEl.innerHTML = `
    <section class="toolbar">
      <h2>Schedule</h2>
      <button id="runDue" class="primary" type="button">Run Due Now</button>
    </section>
    ${table(["Name", "Cadence", "Next run", "Last run", "Status", "Account", "Last error", "Actions"], rows, "No schedules.")}
  `;
  document.getElementById("runDue").addEventListener("click", async () => {
    if (!confirm("Run due schedules now? This can submit and execute real Reddit actions.")) return;
    const result = await post("/api/schedules/run-due", { limit: 5 });
    toast(result.ok ? "Due schedule run requested." : result.error || "Run failed.");
    renderSchedule();
  });
  viewEl.querySelectorAll("[data-schedule]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.schedule;
      const action = button.dataset.action;
      if (action === "delete" && !confirm(`Delete schedule ${id}?`)) return;
      const result = await post(`/api/schedules/${encodeURIComponent(id)}/${action}`, {});
      toast(result.ok ? `Schedule ${action} complete.` : result.error || "Schedule update failed.");
      renderSchedule();
    });
  });
}

async function renderFailed() {
  viewEl.innerHTML = `<div class="message">Loading failures...</div>`;
  const [queuePayload, errorPayload] = await Promise.all([
    api(`/api/queue${accountQuery({ status: "failed", limit: 100 })}`),
    api(`/api/errors${accountQuery({ limit: 50 })}`),
  ]);
  const jobs = queuePayload.data.jobs || [];
  const rows = jobs.map((item) => `
    <tr>
      <td>${esc(formatDate(item.updated_at))}</td>
      <td>${esc(item.account)}</td>
      <td>${esc(item.action)}</td>
      <td>${esc(item.link)}</td>
      <td>${esc(item.attempts)}/${esc(item.max_attempts)}</td>
      <td>${esc(item.last_error || "-")}</td>
      <td><button data-retry="${esc(item.id)}" type="button">Retry</button></td>
    </tr>
  `);
  const actionErrors = errorPayload.data.actionErrors || [];
  viewEl.innerHTML = `
    <section class="toolbar">
      <h2>Failed Attempts</h2>
      <button id="retryAll" class="primary" type="button" ${jobs.length ? "" : "disabled"}>Retry All Failed</button>
    </section>
    ${table(["Time", "Account", "Action", "Link", "Attempts", "Error", "Action"], rows, "No failed queue jobs.")}
    <section class="panel">
      <h3>Action log errors</h3>
      ${table(["Time", "Account", "Action", "Link", "Error", "Screenshot"], actionErrors.map((item) => `
        <tr>
          <td>${esc(formatDate(item.timestamp))}</td>
          <td>${esc(item.account)}</td>
          <td>${esc(item.action)}</td>
          <td>${esc(item.link)}</td>
          <td>${esc(item.error_message || "-")}</td>
          <td>${esc(item.screenshot_path || "-")}</td>
        </tr>
      `), "No action-log errors.")}
    </section>
  `;
  document.getElementById("retryAll").addEventListener("click", async () => {
    if (!confirm("Retry all failed queue jobs for this profile view?")) return;
    const result = await post(`/api/queue/retry-failed${accountQuery()}`, {});
    toast(result.ok ? `Retried ${result.data.count || 0} jobs.` : result.error || "Retry failed.");
    renderFailed();
  });
  viewEl.querySelectorAll("[data-retry]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = await post(`/api/queue/${button.dataset.retry}/retry`, {});
      toast(result.ok ? "Job re-queued." : result.error || "Retry failed.");
      renderFailed();
    });
  });
}

async function renderSuccess() {
  viewEl.innerHTML = `<div class="message">Loading successful tasks...</div>`;
  const payload = await api(`/api/history${accountQuery({ result: "success", limit: 150 })}`);
  const rows = (payload.data.history || []).map((item) => `
    <tr>
      <td>${esc(formatDate(item.timestamp))}</td>
      <td>${esc(item.account)}</td>
      <td>${esc(item.action)}</td>
      <td>${esc(item.link)}</td>
      <td>${badge(item.success ? "success" : "failed")}</td>
    </tr>
  `);
  viewEl.innerHTML = `
    <section class="toolbar"><h2>Successful Tasks</h2></section>
    ${table(["Time", "Account", "Action", "Link", "Result"], rows, "No successful actions logged.")}
  `;
}

function formProfileOptions() {
  const selected = state.selectedAccount !== "all" ? state.selectedAccount : (state.profiles[0]?.accountLabel || "");
  return state.profiles.map((profile) => {
    const value = profile.accountLabel || profile.profileName;
    return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(accountLabel(profile))}</option>`;
  }).join("");
}

function renderFieldInputs(action) {
  const spec = state.capabilities.actions[action] || {};
  const fields = [...new Set([...(spec.required || []), ...(spec.optional || [])])];
  if (!fields.length) return "";
  return fields.map((field) => {
    const isLong = ["comment", "body", "message"].includes(field);
    const label = `${field}${(spec.required || []).includes(field) ? " *" : ""}`;
    return `
      <label class="field ${isLong ? "wide" : ""}">
        <span>${esc(label)}</span>
        ${isLong ? `<textarea name="${esc(field)}"></textarea>` : `<input name="${esc(field)}" type="text">`}
      </label>
    `;
  }).join("");
}

function renderTimingFields(mode) {
  if (mode === "once") {
    return `<label class="field wide"><span>Run at</span><input name="at" type="datetime-local" required></label>`;
  }
  if (mode === "daily") {
    return `<label class="field"><span>Daily time</span><input name="dailyAt" type="time" value="09:00" required></label>`;
  }
  if (mode === "weekly") {
    return `
      <div class="wide">
        <label class="field"><span>Weekly days</span></label>
        <div class="weekday-row">
          ${["MO", "TU", "WE", "TH", "FR", "SA", "SU"].map((day) => `<label><input name="weekday" value="${day}" type="checkbox"> ${day}</label>`).join("")}
        </div>
      </div>
      <label class="field"><span>Weekly time</span><input name="time" type="time" value="09:00" required></label>
    `;
  }
  if (mode === "rrule") {
    return `<label class="field wide"><span>RRULE</span><textarea name="rrule" placeholder="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"></textarea></label>`;
  }
  return `<div class="message wide">Now submits the task and runs one queue worker pass.</div>`;
}

function renderAdd() {
  const actions = Object.keys(state.capabilities.actions).sort();
  const defaultAction = actions[0];
  viewEl.innerHTML = `
    <section class="form-panel">
      <h2>Add Task</h2>
      <form id="taskForm" class="form-grid">
        <label class="field">
          <span>Profile</span>
          <select name="profile" required>${formProfileOptions()}</select>
        </label>
        <label class="field">
          <span>Action</span>
          <select name="action">${actions.map((action) => `<option value="${esc(action)}">${esc(action)}</option>`).join("")}</select>
        </label>
        <div id="fieldInputs" class="wide form-grid">${renderFieldInputs(defaultAction)}</div>
        <div class="wide">
          <label class="field"><span>Timing</span></label>
          <div class="segmented">
            ${["now", "once", "daily", "weekly", "rrule"].map((mode) => `
              <label><input name="mode" type="radio" value="${mode}" ${mode === "now" ? "checked" : ""}> ${mode}</label>
            `).join("")}
          </div>
        </div>
        <div id="timingFields" class="wide form-grid">${renderTimingFields("now")}</div>
        <div class="wide actions">
          <button class="primary" type="submit">Submit Task</button>
        </div>
        <div id="formResult" class="wide"></div>
      </form>
    </section>
  `;
  const form = document.getElementById("taskForm");
  const fieldInputs = document.getElementById("fieldInputs");
  const timingFields = document.getElementById("timingFields");
  const actionSelect = form.elements.action;
  const modeInputs = form.elements.mode;
  actionSelect.addEventListener("change", () => {
    fieldInputs.innerHTML = renderFieldInputs(actionSelect.value);
  });
  form.querySelectorAll("input[name='mode']").forEach((radio) => {
    radio.addEventListener("change", () => {
      timingFields.innerHTML = renderTimingFields(modeInputs.value);
    });
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedAction = actionSelect.value;
    const spec = state.capabilities.actions[selectedAction] || {};
    const fields = {};
    [...fieldInputs.querySelectorAll("input, textarea")].forEach((input) => {
      if (input.value.trim()) fields[input.name] = input.value.trim();
    });
    if (spec.link_kind === "post_url" && fields.link && /\/r\/[^/]+\/s\//.test(fields.link)) {
      document.getElementById("formResult").innerHTML = `<div class="message error">Resolve Reddit /s/ share links to canonical /comments/ URLs before submitting.</div>`;
      return;
    }
    const timing = { mode: modeInputs.value };
    if (timing.mode === "once") timing.at = timingFields.querySelector("[name='at']").value;
    if (timing.mode === "daily") timing.dailyAt = timingFields.querySelector("[name='dailyAt']").value;
    if (timing.mode === "weekly") {
      timing.weekdays = [...timingFields.querySelectorAll("[name='weekday']:checked")].map((input) => input.value);
      timing.time = timingFields.querySelector("[name='time']").value;
    }
    if (timing.mode === "rrule") timing.rrule = timingFields.querySelector("[name='rrule']").value;
    if (timing.mode === "now" && !confirm("Submit and run this action now? This can perform a real Reddit mutation.")) return;
    const resultEl = document.getElementById("formResult");
    resultEl.innerHTML = `<div class="message">Submitting...</div>`;
    const result = await post("/api/tasks", {
      action: selectedAction,
      fields,
      timing,
      identity: identityForValue(form.elements.profile.value),
      noEnsureExecutor: false,
    });
    const ok = result.ok && result.data?.ok !== false;
    resultEl.innerHTML = `<div class="message ${ok ? "success" : "error"}">${esc(ok ? "Task submitted." : (result.error || result.data?.error || "Task failed."))}</div>`;
    toast(ok ? "Task submitted." : "Task failed.");
  });
}

async function renderDaily() {
  viewEl.innerHTML = `<div class="message">Loading action history...</div>`;
  const payload = await api(`/api/daily${accountQuery({ days: 30 })}`);
  const data = payload.data;
  const history = data.history || [];
  const max = Math.max(1, ...history.map((item) => Number(item.action_count || 0)));
  const bars = history.map((item) => {
    const height = Math.max(2, Math.round((Number(item.action_count || 0) / max) * 160));
    return `<div class="bar" style="height: ${height}px" data-label="${esc(item.action_date)}: ${esc(item.action_count)}"></div>`;
  }).join("");
  viewEl.innerHTML = `
    <section class="grid">
      <div class="metric">
        <div class="metric-label">Today</div>
        <div class="metric-value">${esc(data.today_action_count || 0)}</div>
        ${progress(data.today_action_count || 0, data.daily_action_quota)}
        <div class="metric-detail">quota ${data.daily_action_quota || "not set"}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Accounts</div>
        <div class="metric-value">${esc((data.accounts || []).length || (state.selectedAccount === "all" ? 0 : 1))}</div>
        <div class="metric-detail">${state.selectedAccount === "all" ? "aggregate" : esc(state.selectedAccount)}</div>
      </div>
    </section>
    <section class="panel">
      <h2>Last 30 Days</h2>
      <div class="bars">${bars}</div>
    </section>
  `;
}

async function renderView() {
  try {
    if (state.view === "overview") await renderOverview();
    if (state.view === "schedule") await renderSchedule();
    if (state.view === "failed") await renderFailed();
    if (state.view === "success") await renderSuccess();
    if (state.view === "add") renderAdd();
    if (state.view === "daily") await renderDaily();
  } catch (error) {
    viewEl.innerHTML = `<div class="message error">${esc(error.message || error)}</div>`;
  }
}

async function init() {
  setupEvents();
  const [profilesPayload, capabilitiesPayload] = await Promise.all([
    api("/api/profiles"),
    api("/api/capabilities"),
  ]);
  state.profiles = profilesPayload.data.profiles || [];
  state.capabilities = capabilitiesPayload.data;
  renderProfilePicker();
  renderView();
}

init().catch((error) => {
  viewEl.innerHTML = `<div class="message error">${esc(error.message || error)}</div>`;
});
