const state = {
  newsTimer: null,
  oilTimer: null,
  refreshSeconds: 30,
  oilRefreshSeconds: 1,
};

const meta = document.querySelector("#meta");
const oilPanel = document.querySelector("#oil");
const sourcesPanel = document.querySelector("#sources");
const refreshButton = document.querySelector("#refresh");

function fmtDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function number(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toLocaleString([], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderOil(oil) {
  if (!oil.ok) {
    oilPanel.innerHTML = `
      <div>
        <div class="oil-title">${escapeHtml(oil.label)}</div>
        <div class="source-meta">${escapeHtml(oil.status || "Price unavailable")}</div>
      </div>
    `;
    return;
  }
  const direction = oil.change > 0 ? "up" : oil.change < 0 ? "down" : "";
  const sign = oil.change > 0 ? "+" : "";
  oilPanel.innerHTML = `
    <div>
      <div class="oil-title">${escapeHtml(oil.label)}</div>
      <div class="source-meta">${escapeHtml(oil.exchange)} | ${escapeHtml(oil.market_state)} | ${escapeHtml(oil.contract_month || "")} | ${fmtDate(oil.as_of)}</div>
    </div>
    <div class="metric">
      <span class="metric-label">Symbol</span>
      <span class="metric-value">${escapeHtml(oil.symbol)}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Last</span>
      <span class="metric-value">${number(oil.price)} ${escapeHtml(oil.currency || "USD")}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Change</span>
      <span class="metric-value ${direction}">${sign}${number(oil.change)} (${sign}${number(oil.change_percent)}%)</span>
    </div>
    <div class="metric">
      <span class="metric-label">Source</span>
      <a class="metric-value" href="${escapeHtml(oil.source_url)}" target="_blank" rel="noreferrer">Open</a>
    </div>
  `;
}

function renderSource(source) {
  const items = source.items
    .map((item) => {
      const title = escapeHtml(item.title || "Untitled update");
      const url = escapeHtml(item.url || source.url);
      const body = escapeHtml(item.body || "");
      return `
        <article class="item">
          <div class="item-time">${escapeHtml(item.published || "")}</div>
          <a class="item-title" href="${url}" target="_blank" rel="noreferrer">${title}</a>
          ${body ? `<p class="item-body">${body}</p>` : ""}
        </article>
      `;
    })
    .join("");

  return `
    <section class="source">
      <div class="source-head">
        <div>
          <div class="source-title">${escapeHtml(source.label)}</div>
          <div class="source-meta">${escapeHtml(source.status)} | ${source.elapsed_ms} ms | ${fmtDate(source.fetched_at)}</div>
        </div>
        <span class="badge ${source.ok ? "" : "error"}">${source.ok ? "Live" : "Check source"}</span>
      </div>
      <div class="items">
        ${items || `<div class="empty">${source.ok ? "No matching items yet." : escapeHtml(source.status)}</div>`}
      </div>
    </section>
  `;
}

function scheduleNews() {
  window.clearTimeout(state.newsTimer);
  state.newsTimer = window.setTimeout(loadSnapshot, state.refreshSeconds * 1000);
}

function scheduleOil() {
  window.clearTimeout(state.oilTimer);
  state.oilTimer = window.setTimeout(loadOil, state.oilRefreshSeconds * 1000);
}

async function loadSnapshot() {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    const snapshot = await response.json();
    state.refreshSeconds = snapshot.refresh_seconds || 30;
    state.oilRefreshSeconds = snapshot.oil_refresh_seconds || 1;
    renderOil(snapshot.oil);
    sourcesPanel.innerHTML = snapshot.sources.map(renderSource).join("");
    meta.textContent = `Updated ${fmtDate(snapshot.generated_at)} | oil every ${state.oilRefreshSeconds}s | sources every ${state.refreshSeconds}s | ${snapshot.item_limit || 4} items per source | keywords: ${snapshot.keywords.join(", ")}`;
  } catch (error) {
    meta.textContent = `Could not load snapshot: ${error}`;
  } finally {
    refreshButton.disabled = false;
    scheduleNews();
  }
}

async function loadOil() {
  try {
    const response = await fetch("/api/oil", { cache: "no-store" });
    const snapshot = await response.json();
    state.oilRefreshSeconds = snapshot.oil_refresh_seconds || 1;
    renderOil(snapshot.oil);
  } catch (error) {
    renderOil({
      ok: false,
      label: "Brent Oil first nearby future",
      status: `Could not load oil price: ${error}`,
    });
  } finally {
    scheduleOil();
  }
}

refreshButton.addEventListener("click", () => {
  loadSnapshot();
  loadOil();
});

loadSnapshot();
loadOil();
