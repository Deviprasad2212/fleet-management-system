/* FleetMgr – small, dependency-free UI layer */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const icon = (n) => `<svg class="ic" aria-hidden="true"><use href="#i-${n}"/></svg>`;

  /* ---------- Theme ---------- */
  const root = document.documentElement;
  function setThemeIcon() {
    const dark = root.dataset.theme === "dark";
    $$("[data-theme-toggle]").forEach((b) => {
      b.innerHTML = icon(dark ? "sun" : "moon");
      b.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    });
  }
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-theme-toggle]")) return;
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("fm-theme", root.dataset.theme); } catch (_) {}
    setThemeIcon();
    renderCharts();
  });
  setThemeIcon();

  /* ---------- Clock ---------- */
  const clk = $("#clk");
  if (clk) {
    const tick = () => (clk.textContent = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }));
    tick(); setInterval(tick, 15000);
  }

  /* ---------- Tabs (hash routed) ---------- */
  const panes = $$(".pane");
  const navLinks = $$(".nav a[data-tab]");
  const side = $(".side"), scrim = $(".scrim");
  function closeSide() { side && side.classList.remove("is-open"); scrim && scrim.classList.remove("is-open"); }
  function show(name) {
    if (!panes.length) return;
    if (!$("#pane-" + name)) name = panes[0].id.replace("pane-", "");
    panes.forEach((p) => p.classList.toggle("is-active", p.id === "pane-" + name));
    navLinks.forEach((a) => {
      const on = a.dataset.tab === name;
      a.classList.toggle("is-active", on);
      if (on) { a.setAttribute("aria-current", "page"); const t = $("#page-title"); if (t) t.textContent = a.dataset.title || a.textContent.trim(); }
      else a.removeAttribute("aria-current");
    });
    closeSide();
    renderCharts();
  }
  function route() { show(location.hash.replace("#", "")); }
  window.addEventListener("hashchange", () => { route(); window.scrollTo({ top: 0 }); });
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto]");
    if (g) { e.preventDefault(); location.hash = g.dataset.goto; }
    if (e.target.closest("[data-menu]")) { side.classList.add("is-open"); scrim.classList.add("is-open"); }
    if (e.target.closest(".scrim")) closeSide();
  });

  /* ---------- Toasts ---------- */
  const toasts = $(".toasts");
  function dismiss(t) { t.classList.add("is-leaving"); setTimeout(() => t.remove(), 260); }
  function toast(msg, kind = "success") {
    if (!toasts) return;
    const t = document.createElement("div");
    t.className = "toast t-" + kind; t.setAttribute("role", kind === "error" ? "alert" : "status");
    t.innerHTML = icon(kind === "error" ? "alert-circle" : "check-circle") + "<p></p><button type='button' aria-label='Dismiss'>" + icon("x") + "</button>";
    $("p", t).textContent = msg; toasts.appendChild(t);
    setTimeout(() => dismiss(t), kind === "error" ? 7000 : 4200);
  }
  document.addEventListener("click", (e) => { const b = e.target.closest(".toast button"); if (b) dismiss(b.closest(".toast")); });
  $$(".toast").forEach((t) => setTimeout(() => dismiss(t), t.classList.contains("t-error") ? 7000 : 4200));

  /* ---------- Dialogs ---------- */
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open]");
    if (opener) {
      const d = document.getElementById(opener.dataset.open); if (!d) return;
      const f = $("form", d);
      if (f && opener.dataset.action) f.action = opener.dataset.action;
      if (opener.dataset.fill) {
        const data = JSON.parse(opener.dataset.fill);
        Object.entries(data).forEach(([k, v]) => {
          const el = d.querySelector(`[name="${k}"]`); if (el) el.value = v;
          const out = d.querySelector(`[data-out="${k}"]`); if (out) out.textContent = v;
        });
      }
      d.showModal();
      const first = $("input:not([type=hidden]), select", d); if (first && !opener.dataset.noFocus) first.focus();
    }
    if (e.target.closest("[data-close]")) e.target.closest("dialog").close();
    if (e.target.matches("dialog.modal")) {              // click on backdrop
      const r = e.target.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close();
    }
  });

  /* Confirmation before destructive actions */
  const confirmDlg = $("#confirm-dialog");
  let pendingForm = null;
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.dataset.confirm && confirmDlg && !f.dataset.confirmed) {
      e.preventDefault(); pendingForm = f;
      $("[data-confirm-title]", confirmDlg).textContent = f.dataset.confirmTitle || "Are you sure?";
      $("[data-confirm-text]", confirmDlg).textContent = f.dataset.confirm;
      const ok = $("[data-confirm-ok]", confirmDlg); ok.textContent = f.dataset.confirmOk || "Confirm";
      ok.className = "btn " + (f.dataset.confirmTone === "primary" ? "btn-primary" : "btn-primary");
      confirmDlg.showModal(); return;
    }
    // prevent double submits
    const btn = $("button[type=submit]:not([data-no-lock])", f);
    if (btn && !e.defaultPrevented) setTimeout(() => { btn.disabled = true; btn.classList.add("is-loading"); }, 0);
  });
  if (confirmDlg) {
    $("[data-confirm-ok]", confirmDlg).addEventListener("click", () => {
      if (!pendingForm) return; pendingForm.dataset.confirmed = "1"; confirmDlg.close(); pendingForm.requestSubmit ? pendingForm.requestSubmit() : pendingForm.submit();
    });
    confirmDlg.addEventListener("close", () => { if (pendingForm && !pendingForm.dataset.confirmed) pendingForm = null; });
  }
  // Back/forward cache: re-enable buttons
  window.addEventListener("pageshow", () => $$("button.is-loading").forEach((b) => { b.disabled = false; b.classList.remove("is-loading"); }));

  /* ---------- Search + filter chips ---------- */
  $$("[data-filter-root]").forEach((rootEl) => {
    const items = $$("[data-item]", rootEl);
    const input = $("[data-search]", rootEl);
    const chips = $$("[data-chip]", rootEl);
    const label = $("[data-count]", rootEl);
    const none = $("[data-none]", rootEl);
    let status = "all";
    const apply = () => {
      const q = (input ? input.value : "").trim().toLowerCase();
      let n = 0;
      items.forEach((it) => {
        const okS = status === "all" || it.dataset.status === status;
        const okQ = !q || it.textContent.toLowerCase().includes(q);
        const vis = okS && okQ; it.hidden = !vis; if (vis) n++;
      });
      if (label) label.textContent = n + (n === 1 ? " result" : " results");
      if (none) none.hidden = n !== 0;
    };
    chips.forEach((c) => c.addEventListener("click", () => {
      status = c.dataset.chip; chips.forEach((x) => x.setAttribute("aria-pressed", String(x === c))); apply();
    }));
    if (input) input.addEventListener("input", apply);
    apply();
  });

  /* ---------- CSV export ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-export]"); if (!b) return;
    const table = document.getElementById(b.dataset.export); if (!table) return;
    const cols = $$("thead th", table).map((th, i) => (th.hasAttribute("data-noexport") ? -1 : i)).filter((i) => i >= 0);
    const esc = (s) => '"' + String(s).replace(/\s+/g, " ").trim().replace(/"/g, '""') + '"';
    const rows = [cols.map((i) => esc($$("thead th", table)[i].textContent))];
    $$("tbody tr[data-item]", table).filter((r) => !r.hidden).forEach((r) => {
      const tds = $$("td", r);
      rows.push(cols.map((i) => { const inp = $("input", tds[i]); return esc(inp ? inp.value : tds[i].textContent); }));
    });
    const blob = new Blob(["\ufeff" + rows.map((r) => r.join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = (b.dataset.filename || "export") + "-" + new Date().toISOString().slice(0, 10) + ".csv";
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    toast("Report exported as CSV");
  });

  /* ---------- Invoice print ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-print]"); if (!b) return;
    const inv = document.getElementById(b.dataset.print); if (!inv) return;
    inv.classList.add("is-printing"); window.print();
    setTimeout(() => inv.classList.remove("is-printing"), 400);
  });

  /* ---------- Password reveal ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-reveal]"); if (!b) return;
    const i = b.parentElement.querySelector("input"); const show = i.type === "password";
    i.type = show ? "text" : "password"; b.innerHTML = icon(show ? "eye-off" : "eye");
    b.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });

  /* ---------- Demo account chips ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-demo]"); if (!b) return;
    const f = b.closest(".auth-card").querySelector("form");
    f.email.value = b.dataset.email; f.password.value = b.dataset.password; f.password.focus();
  });

  /* ---------- Route preview (new request) ---------- */
  const rp = $("[data-route-preview]");
  if (rp) {
    const a = $("[name=from_location]"), b = $("[name=to_location]");
    const draw = () => {
      const x = a.value.trim(), y = b.value.trim();
      if (!x && !y) { rp.innerHTML = '<span class="ph-text">Your route will appear here</span>'; return; }
      rp.innerHTML = "";
      const mk = (t, ph) => { const s = document.createElement("span"); s.textContent = t || ph; if (!t) s.style.color = "var(--faint)"; return s; };
      const line = document.createElement("span"); line.className = "route"; line.innerHTML = "<i></i>";
      rp.append(mk(x, "Pickup"), line, mk(y, "Delivery"));
    };
    a.addEventListener("input", draw); b.addEventListener("input", draw); draw();
  }

  /* ---------- Charts (inline SVG, theme-aware) ---------- */
  const NS = "http://www.w3.org/2000/svg";
  const el = (n, attrs = {}, text) => { const e = document.createElementNS(NS, n); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); if (text != null) e.textContent = text; return e; };
  const css = (v) => getComputedStyle(root).getPropertyValue(v).trim();

  function bars(host) {
    const d = JSON.parse(host.dataset.chartData);
    const W = 560, H = 250, pl = 46, pr = 8, pt = 14, pb = 30;
    const max = Math.max(1, ...d.map((x) => x.paid + x.unpaid));
    const nice = (() => { const p = Math.pow(10, Math.floor(Math.log10(max))); return Math.ceil(max / p) * p; })();
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Monthly billing, paid and unpaid" });
    const fmt = (v) => (v >= 100000 ? (v / 100000).toFixed(v % 100000 ? 1 : 0) + "L" : v >= 1000 ? (v / 1000).toFixed(v % 1000 ? 1 : 0) + "k" : String(v));
    for (let i = 0; i <= 4; i++) {
      const y = pt + ((H - pt - pb) * i) / 4, v = nice - (nice * i) / 4;
      svg.append(el("line", { x1: pl, x2: W - pr, y1: y, y2: y, class: "grid-line" }));
      svg.append(el("text", { x: pl - 8, y: y + 4, "text-anchor": "end" }, "₹" + fmt(v)));
    }
    const slot = (W - pl - pr) / d.length, bw = Math.min(46, slot * 0.56);
    d.forEach((m, i) => {
      const x = pl + slot * i + (slot - bw) / 2, ch = H - pt - pb;
      const hp = (m.paid / nice) * ch, hu = (m.unpaid / nice) * ch, yb = H - pb;
      if (m.paid > 0) svg.append(el("rect", { x, y: yb - hp, width: bw, height: hp, rx: 5, fill: css("--ok") }));
      if (m.unpaid > 0) svg.append(el("rect", { x, y: yb - hp - hu, width: bw, height: hu, rx: 5, fill: css("--brand") }));
      const tip = el("title"); tip.textContent = `${m.label}: ₹${(m.paid + m.unpaid).toLocaleString("en-IN")} billed, ₹${m.paid.toLocaleString("en-IN")} paid`;
      const g = el("g"); g.append(tip, el("rect", { x: pl + slot * i, y: pt, width: slot, height: H - pt - pb, fill: "transparent" })); svg.append(g);
      svg.append(el("text", { x: x + bw / 2, y: H - 9, "text-anchor": "middle" }, m.label));
    });
    host.replaceChildren(svg);
  }

  function donut(host) {
    const d = JSON.parse(host.dataset.chartData).filter((x) => x.value > 0);
    const total = JSON.parse(host.dataset.chartData).reduce((a, x) => a + x.value, 0);
    const S = 150, r = 54, sw = 20, c = 2 * Math.PI * r;
    const svg = el("svg", { viewBox: `0 0 ${S} ${S}`, role: "img", "aria-label": host.dataset.label || "Breakdown", style: "max-width:150px" });
    svg.append(el("circle", { cx: S / 2, cy: S / 2, r, fill: "none", stroke: css("--line-2"), "stroke-width": sw }));
    let off = 0; const gap = d.length > 1 ? 3 : 0;
    d.forEach((x) => {
      const len = (x.value / total) * c;
      const arc = el("circle", { cx: S / 2, cy: S / 2, r, fill: "none", stroke: css(x.color), "stroke-width": sw, "stroke-dasharray": `${Math.max(0, len - gap)} ${c - Math.max(0, len - gap)}`, "stroke-dashoffset": -off, transform: `rotate(-90 ${S / 2} ${S / 2})` });
      const t = el("title"); t.textContent = `${x.label}: ${x.value}`; arc.append(t); svg.append(arc); off += len;
    });
    svg.append(el("text", { x: S / 2, y: S / 2 + 4, "text-anchor": "middle", class: "donut-center" }, String(total)));
    svg.append(el("text", { x: S / 2, y: S / 2 + 21, "text-anchor": "middle", class: "donut-center-sub" }, host.dataset.unit || "total"));
    host.replaceChildren(svg);
  }

  function renderCharts() {
    $$("[data-chart]").forEach((h) => {
      if (!h.closest(".pane.is-active") && h.closest(".pane")) return;
      try { (h.dataset.chart === "bars" ? bars : donut)(h); } catch (err) { console.error(err); }
    });
  }
  route();            // initial tab, once every helper above is defined
  window.FleetUI = { toast };
})();
