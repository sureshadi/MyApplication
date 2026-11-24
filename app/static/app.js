// Ticker suggestions as you type, like Google. Used by the header search box and the
// Portfolio "Add ticker" box. onPick(symbol) runs when a suggestion is chosen.
function attachSuggestions(input, list, onPick) {
  "use strict";
  var items = [];
  var activeIndex = -1;
  var timer = null;
  var lastQuery = "";
  var seq = 0;
  var idPrefix = list.id + "-";

  function close() {
    list.hidden = true;
    list.replaceChildren();
    items = [];
    activeIndex = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function pick(symbol) { close(); onPick(symbol); }

  function highlight(text, query) {
    // Bold the part that matches what was typed, safely (no innerHTML).
    var frag = document.createDocumentFragment();
    var i = text.toLowerCase().indexOf(query.toLowerCase());
    if (!query || i < 0) { frag.append(text); return frag; }
    var b = document.createElement("mark");
    b.textContent = text.slice(i, i + query.length);
    frag.append(text.slice(0, i), b, text.slice(i + query.length));
    return frag;
  }

  function setActive(i) {
    var options = list.querySelectorAll("[role=option]");
    options.forEach(function (el, n) { el.setAttribute("aria-selected", n === i ? "true" : "false"); });
    activeIndex = i;
    if (i >= 0 && options[i]) {
      input.setAttribute("aria-activedescendant", options[i].id);
      options[i].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function render(query, suggestions) {
    items = suggestions;
    activeIndex = -1;
    if (!suggestions.length) {
      list.replaceChildren();
      var empty = document.createElement("li");
      empty.className = "suggestion-empty";
      empty.textContent = "No matching tickers";
      list.append(empty);
    } else {
      list.replaceChildren.apply(list, suggestions.map(function (s, n) {
        var li = document.createElement("li");
        li.id = idPrefix + n;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        li.setAttribute("data-testid", "suggestion");
        li.dataset.symbol = s.symbol;
        var sym = document.createElement("span"); sym.className = "sg-sym"; sym.append(highlight(s.symbol, query));
        var name = document.createElement("span"); name.className = "sg-name"; name.append(highlight(s.name || "", query));
        var ex = document.createElement("span"); ex.className = "sg-ex"; ex.textContent = s.exchange || "";
        li.append(sym, name, ex);
        // mousedown (not click) so it fires before the input loses focus.
        li.addEventListener("mousedown", function (ev) { ev.preventDefault(); pick(s.symbol); });
        li.addEventListener("mousemove", function () { if (activeIndex !== n) setActive(n); });
        return li;
      }));
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function lookup() {
    var query = input.value.trim();
    if (query === lastQuery && !list.hidden) return;
    lastQuery = query;
    if (!query) { close(); return; }
    var mine = ++seq;
    fetch("/api/suggest?q=" + encodeURIComponent(query))
      .then(function (r) { return r.ok ? r.json() : { suggestions: [] }; })
      .then(function (data) {
        if (mine !== seq || input.value.trim() !== query) return; // a newer keystroke won
        render(query, data.suggestions || []);
      })
      .catch(function () { /* leave the box usable without suggestions */ });
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(lookup, 120);
  });
  input.addEventListener("focus", function () { if (input.value.trim()) { lastQuery = ""; lookup(); } });
  input.addEventListener("blur", function () { setTimeout(close, 100); });

  input.addEventListener("keydown", function (ev) {
    if (list.hidden) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopImmediatePropagation(); // first Esc closes the list, not the surrounding form
      close();
      return;
    }
    if (!items.length) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setActive((activeIndex + 1) % items.length);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActive(activeIndex <= 0 ? items.length - 1 : activeIndex - 1);
    } else if (ev.key === "Enter" && activeIndex >= 0) {
      ev.preventDefault();
      pick(items[activeIndex].symbol);
    }
  }, true); // capture: runs before the box's own key handlers

  return {
    // What a press of Enter/Add/Look up should use: a typed company name ("apple") becomes the
    // top suggestion (AAPL); a typed symbol, even one not in the list, stays as typed.
    resolve: function (typed) {
      var t = (typed || "").trim().toUpperCase();
      var exact = items.some(function (s) { return s.symbol === t; });
      if (items.length && !exact && items[0].symbol.indexOf(t) !== 0) return items[0].symbol;
      return t;
    },
    close: close
  };
}

// Header search box.
(function () {
  "use strict";
  var input = document.querySelector("[data-testid=search-input]");
  var list = document.querySelector("[data-testid=suggestions]");
  if (!input || !list) return;
  function go(symbol) { window.location.href = "/ticker/" + encodeURIComponent(symbol); }
  var sg = attachSuggestions(input, list, go);
  if (input.form) {
    input.form.addEventListener("submit", function (ev) {
      var choice = sg.resolve(input.value);
      if (choice !== input.value.trim().toUpperCase()) { ev.preventDefault(); go(choice); }
    });
  }
})();

// Portfolio page: every ticker with live prices; add and remove tickers, saved in this browser.
(function () {
  "use strict";

  var STORAGE_KEY = "mh.watchlist.v1";
  var SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;
  var MAX_TICKERS = 25;
  var REFRESH_MS = 60000;

  var bar = document.querySelector("[data-testid=portfolio]");
  if (!bar) return;
  var chipsEl = bar.querySelector("#watchlist");
  var addBtn = bar.querySelector("[data-testid=add-ticker]");
  var form = bar.querySelector("[data-testid=add-form]");
  var input = form.querySelector("input");
  var errorEl = form.querySelector("[data-testid=add-error]");
  var cancelBtn = form.querySelector(".add-cancel");
  var defaults = (bar.dataset.default || "").split(",").filter(Boolean);
  var countEl = bar.querySelector("[data-testid=portfolio-count]");
  var suggestList = form.querySelector("[data-testid=add-suggestions]");
  // Picking a suggestion fills in its symbol and adds it right away.
  var sg = suggestList ? attachSuggestions(input, suggestList, function (symbol) {
    input.value = symbol;
    form.requestSubmit();
  }) : null;

  function load() {
    try {
      var saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
      if (Array.isArray(saved)) return saved.filter(function (s) { return SYMBOL_RE.test(s); });
    } catch (e) { /* storage unavailable: fall back to defaults */ }
    return defaults.slice();
  }

  function save(list) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch (e) { /* ignore */ }
  }

  var watchlist = load();
  // Set further down by the market research section.
  var onAdd = function () {}, onRemove = function () {}, onPeriod = function () {};

  // Period picker: badges and research compare over 1M ... 5Y, saved in this browser.
  var PERIOD_KEY = "mh.period.v1";
  var periodBtns = Array.prototype.slice.call(bar.querySelectorAll("[data-testid=period-option]"));
  var periodNameEl = bar.querySelector("[data-testid=period-name]");
  var PERIODS = periodBtns.map(function (b) { return b.dataset.period; });
  var period = (function () {
    try { var p = window.localStorage.getItem(PERIOD_KEY); if (PERIODS.indexOf(p) !== -1) return p; } catch (e) { /* ignore */ }
    return "1Y";
  })();
  var quotes = {};       // symbol -> latest quote
  var performance = {};  // symbol -> {1M: pct, ...}, or null when unavailable

  function chip(symbol) {
    var el = document.createElement("div");
    el.className = "ticker-card";
    el.dataset.symbol = symbol;
    el.setAttribute("data-testid", "ticker-chip");

    var link = document.createElement("a");
    link.className = "chip-link";
    link.href = "/ticker/" + encodeURIComponent(symbol);
    var sym = document.createElement("span"); sym.className = "sym"; sym.textContent = symbol;
    var name = document.createElement("span"); name.className = "name";
    var px = document.createElement("span"); px.className = "px";
    var chg = document.createElement("span"); chg.className = "chg";
    link.append(sym, name, px, chg);

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.setAttribute("aria-label", "Remove " + symbol);
    remove.title = "Remove " + symbol;
    remove.textContent = "×";
    remove.addEventListener("click", function (ev) {
      ev.preventDefault();
      watchlist = watchlist.filter(function (s) { return s !== symbol; });
      save(watchlist);
      el.remove();
      updateCount();
      delete quotes[symbol]; delete performance[symbol];
      onRemove(symbol);
    });

    el.append(link, remove);
    return el;
  }

  function updateCount() { countEl.textContent = String(watchlist.length); }

  function render() {
    updateCount();
    chipsEl.replaceChildren.apply(chipsEl, watchlist.map(chip).concat([addBtn]));
  }

  function fmt(n) {
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function paint(q) {
    quotes[q.symbol] = q;
    var el = chipsEl.querySelector('[data-symbol="' + q.symbol + '"]');
    if (!el) return;
    var px = el.querySelector(".px");
    var name = el.querySelector(".name");
    if (name && q.name) name.textContent = q.name;
    px.textContent = q.error ? "" : fmt(q.price);
    paintBadge(q.symbol);
  }

  // The badge shows the price change over the chosen period.
  function paintBadge(symbol) {
    var el = chipsEl.querySelector('[data-symbol="' + symbol + '"]');
    if (!el) return;
    var chg = el.querySelector(".chg"), q = quotes[symbol];
    var label = periodLabel(period);
    if ((q && q.error) || performance[symbol] === null) {
      chg.textContent = "n/a"; chg.className = "chg na"; chg.title = "No price history";
      return;
    }
    if (!performance[symbol]) { chg.textContent = ""; chg.className = "chg"; return; }
    var pct = performance[symbol][period];
    if (pct == null) {
      chg.textContent = "–"; chg.className = "chg na"; chg.title = "No price history for " + label;
      return;
    }
    chg.textContent = (pct > 0 ? "+" : "") + pct.toFixed(2) + "%";
    chg.className = "chg " + (pct > 0 ? "up" : pct < 0 ? "down" : "flat");
    chg.title = "Price change over " + label;
  }

  function periodLabel(p) {
    var b = periodBtns.filter(function (x) { return x.dataset.period === p; })[0];
    return b ? b.dataset.label : p;
  }

  function fetchPerformance(symbols) {
    if (!symbols.length) return Promise.resolve();
    return fetch("/api/performance?symbols=" + encodeURIComponent(symbols.join(",")))
      .then(function (r) { return r.ok ? r.json() : { performance: [] }; })
      .then(function (data) {
        data.performance.forEach(function (p) { performance[p.symbol] = p.error ? null : p.changes; paintBadge(p.symbol); });
      })
      .catch(function () { /* badges stay empty; the next refresh tries again */ });
  }

  function setPeriod(p, focus) {
    period = p;
    try { window.localStorage.setItem(PERIOD_KEY, p); } catch (e) { /* ignore */ }
    periodBtns.forEach(function (b) {
      var on = b.dataset.period === p;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.setAttribute("tabindex", on ? "0" : "-1");
      if (on && focus) b.focus();
    });
    if (periodNameEl) periodNameEl.textContent = periodLabel(p);
    watchlist.forEach(paintBadge);
    onPeriod(p);
  }

  periodBtns.forEach(function (b, i) {
    b.addEventListener("click", function () { if (b.dataset.period !== period) setPeriod(b.dataset.period); });
    b.addEventListener("keydown", function (ev) {
      var next = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? i + 1 : ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? i - 1 : null;
      if (next === null) return;
      ev.preventDefault();
      setPeriod(PERIODS[(next + PERIODS.length) % PERIODS.length], true);
    });
  });

  function fetchQuotes(symbols) {
    if (!symbols.length) return Promise.resolve([]);
    return fetch("/api/quotes?symbols=" + encodeURIComponent(symbols.join(",")))
      .then(function (r) { return r.ok ? r.json() : { quotes: [] }; })
      .then(function (data) { data.quotes.forEach(paint); return data.quotes; })
      .catch(function () { return []; });
  }

  function openForm() {
    form.hidden = false;
    errorEl.textContent = "";
    input.value = "";
    input.focus();
  }
  function closeForm() { form.hidden = true; errorEl.textContent = ""; if (sg) sg.close(); }

  addBtn.addEventListener("click", function () { form.hidden ? openForm() : closeForm(); });
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeForm(); });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var symbol = sg ? sg.resolve(input.value) : input.value.trim().toUpperCase();
    if (sg) sg.close();
    errorEl.textContent = "";
    if (!SYMBOL_RE.test(symbol)) { errorEl.textContent = "Enter a valid ticker symbol, like TSLA."; return; }
    if (watchlist.indexOf(symbol) !== -1) { errorEl.textContent = symbol + " is already in your portfolio."; return; }
    if (watchlist.length >= MAX_TICKERS) { errorEl.textContent = "You can keep up to " + MAX_TICKERS + " tickers."; return; }

    var submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    fetch("/api/quotes?symbols=" + encodeURIComponent(symbol))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var q = data.quotes[0];
        if (q.error === "not_found") { errorEl.textContent = "Couldn't find " + symbol + "."; return; }
        watchlist.push(symbol);
        save(watchlist);
        chipsEl.insertBefore(chip(symbol), addBtn);
        updateCount();
        paint(q);
        fetchPerformance([symbol]);
        closeForm();
        onAdd(symbol);
      })
      .catch(function () { errorEl.textContent = "Couldn't add " + symbol + ". Please try again."; })
      .then(function () { submit.disabled = false; });
  });

  // ---------- Side panel: top 3 news for a clicked ticker ----------
  var panel = document.querySelector("[data-testid=news-panel]");
  var backdrop = document.querySelector("[data-testid=news-panel-backdrop]");
  var panelSeq = 0;
  var lastFocus = null;

  function relTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var mins = Math.round((Date.now() - d) / 60000);
    return mins < 1 ? "just now" : mins < 60 ? mins + "m ago" : mins < 1440 ? Math.floor(mins / 60) + "h ago"
      : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function panelMessage(text) {
    var li = document.createElement("li");
    li.className = "panel-empty";
    li.textContent = text;
    return li;
  }

  function closePanel() {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    backdrop.hidden = true;
    document.querySelectorAll(".is-open[data-symbol]").forEach(function (el) { el.classList.remove("is-open"); });
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }

  function openNews(symbol, name) {
    if (!panel) { window.location.href = "/ticker/" + encodeURIComponent(symbol); return; }
    lastFocus = document.activeElement;
    document.querySelectorAll(".is-open[data-symbol]").forEach(function (el) { el.classList.remove("is-open"); });
    var card = chipsEl.querySelector('[data-symbol="' + symbol + '"]');
    if (card) card.classList.add("is-open");
    panel.querySelector("[data-testid=news-panel-symbol]").textContent = symbol;
    panel.querySelector("[data-testid=news-panel-name]").textContent = name || "";
    panel.querySelector("[data-testid=panel-more]").href = "/ticker/" + encodeURIComponent(symbol);
    var list = panel.querySelector("[data-testid=panel-news]");
    list.replaceChildren(panelMessage("Loading headlines…"));
    panel.hidden = false;
    backdrop.hidden = false;
    panel.querySelector("[data-testid=news-panel-close]").focus();

    var mine = ++panelSeq;
    fetch("/api/ticker/" + encodeURIComponent(symbol) + "/news?limit=3")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        if (mine !== panelSeq) return;
        if (!data.items.length) { list.replaceChildren(panelMessage("No recent headlines for " + symbol + ".")); return; }
        list.replaceChildren.apply(list, data.items.map(function (item) {
          var li = document.createElement("li");
          li.className = "panel-item";
          li.setAttribute("data-testid", "panel-news-item");
          var meta = document.createElement("div"); meta.className = "news-meta";
          var src = document.createElement("span"); src.className = "news-source"; src.dataset.source = item.source; src.textContent = item.source;
          meta.append(src);
          if (item.published) {
            var t = document.createElement("time"); t.dateTime = item.published; t.textContent = relTime(item.published);
            t.title = new Date(item.published).toLocaleString();
            meta.append(t);
          }
          var a = document.createElement("a");
          a.className = "panel-title"; a.href = item.link; a.target = "_blank"; a.rel = "noopener noreferrer";
          a.textContent = item.title;
          li.append(meta, a);
          if (item.summary) { var p = document.createElement("p"); p.className = "panel-summary"; p.textContent = item.summary; li.append(p); }
          return li;
        }));
      })
      .catch(function () { if (mine === panelSeq) list.replaceChildren(panelMessage("Couldn't load headlines. Please try again.")); });
  }

  if (panel) {
    panel.querySelector("[data-testid=news-panel-close]").addEventListener("click", closePanel);
    backdrop.addEventListener("click", closePanel);
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && !panel.hidden) closePanel(); });
  }

  // A plain click on a ticker opens the panel; Cmd/Ctrl/middle-click still opens the full page.
  chipsEl.addEventListener("click", function (ev) {
    var link = ev.target.closest(".chip-link");
    if (!link || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    var card = link.closest("[data-symbol]");
    var name = card.querySelector(".name");
    openNews(card.dataset.symbol, name ? name.textContent : "");
  });

  // ---------- Market research: one tab per company, one analysis shown at a time ----------
  var tabsEl = document.querySelector("[data-testid=research-tabs]");
  var panelEl = document.querySelector("[data-testid=research-panel]");
  var analyses = {};   // symbol -> analysis JSON
  var failures = {};   // symbol -> message
  var selected = null;
  var queue = [];
  var running = 0;
  var MAX_PARALLEL = 3;
  var LEVEL_LABEL = { hi: "High risk", md: "Watch", lo: "Low risk", ok: "No flags" };
  var SEV_LABEL = { high: "High", medium: "Medium", low: "Low" };
  var KEY_METRICS = ["Revenue", "Operating margin", "Net income", "Free cash flow"];

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function money(v) {
    if (v == null) return "n/a";
    var a = Math.abs(v), sign = v < 0 ? "-" : "";
    var units = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (var i = 0; i < units.length; i++) if (a >= units[i][0]) return sign + "$" + (a / units[i][0]).toFixed(2) + units[i][1];
    return sign + "$" + a.toFixed(0);
  }

  function value(m, v) {
    if (v == null) return "n/a";
    if (m.unit === "pct") return v.toFixed(1) + "%";
    if (m.unit === "eps") return (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
    return money(v);
  }

  function comparisonOf(a) {
    return a.comparison || { key: "1Y", label: "Prior year", phrase: "year over year", price_window: "1 year" };
  }

  function changeText(m) {
    if (m.change == null) return m.prior == null ? "No earlier figure" : "n/m";
    return (m.change > 0 ? "+" : "") + m.change.toFixed(1) + (m.change_unit === "pp" ? " pp" : "%");
  }

  function changeClass(m) { return m.change == null ? "flat" : m.change > 0 ? "up" : m.change < 0 ? "down" : "flat"; }

  function riskLevel(a) {
    var sev = a.risks.map(function (r) { return r.severity; });
    return sev.indexOf("high") >= 0 ? "hi" : sev.indexOf("medium") >= 0 ? "md" : sev.length ? "lo" : "ok";
  }

  function levelBadge(level) {
    var b = el("span", "level-badge lv-" + level, LEVEL_LABEL[level]);
    b.setAttribute("data-testid", "risk-level");
    b.dataset.level = level;
    return b;
  }

  // Tabs ----------------------------------------------------------------
  function tabFor(symbol) { return tabsEl.querySelector('[data-symbol="' + symbol + '"]'); }

  function paintTab(symbol) {
    var tab = tabFor(symbol);
    if (!tab) return;
    var dot = tab.querySelector(".tab-dot");
    var a = analyses[symbol];
    var level = a ? riskLevel(a) : failures[symbol] ? "na" : "loading";
    dot.className = "tab-dot dot-" + level;
    tab.dataset.level = level;
    tab.title = symbol + ": " + (a ? LEVEL_LABEL[level] : failures[symbol] ? "no analysis" : "analyzing…");
  }

  function makeTab(symbol) {
    var tab = el("button", "research-tab");
    tab.type = "button";
    tab.id = "rtab-" + symbol.replace(/[^A-Z0-9]/g, "_");
    tab.dataset.symbol = symbol;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", "false");
    tab.setAttribute("tabindex", "-1");
    tab.setAttribute("data-testid", "research-tab");
    tab.append(el("span", "tab-dot dot-loading"), el("span", "tab-sym", symbol));
    tab.addEventListener("click", function () { select(symbol); });
    return tab;
  }

  function select(symbol, focus) {
    selected = symbol;
    tabsEl.querySelectorAll("[role=tab]").forEach(function (t) {
      var on = t.dataset.symbol === symbol;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.setAttribute("tabindex", on ? "0" : "-1");
      if (on && focus) t.focus();
      if (on) t.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
    var tab = tabFor(symbol);
    if (tab) panelEl.setAttribute("aria-labelledby", tab.id);
    renderPanel();
  }

  tabsEl.addEventListener("keydown", function (ev) {
    var tabs = Array.prototype.slice.call(tabsEl.querySelectorAll("[role=tab]"));
    var i = tabs.findIndex(function (t) { return t.dataset.symbol === selected; });
    var next = ev.key === "ArrowRight" ? i + 1 : ev.key === "ArrowLeft" ? i - 1 : ev.key === "Home" ? 0 : ev.key === "End" ? tabs.length - 1 : null;
    if (next === null || !tabs.length) return;
    ev.preventDefault();
    select(tabs[(next + tabs.length) % tabs.length].dataset.symbol, true);
  });

  // Panel ---------------------------------------------------------------
  function riskList(a) {
    var box = el("section", "rc-risks");
    box.setAttribute("data-testid", "research-risks");
    box.append(el("h4", "rp-h", "Risks and red flags"));
    if (!a.risks.length) { box.append(el("p", "rc-muted", "No red flags found in the figures checked.")); return box; }
    var ul = el("ul", "risk-list");
    a.risks.forEach(function (r) {
      var li = el("li", "risk sev-" + r.severity);
      li.setAttribute("data-testid", "risk");
      li.dataset.severity = r.severity;
      li.append(el("span", "sev", SEV_LABEL[r.severity] || r.severity), el("strong", "risk-title", r.title), el("p", "risk-detail", r.detail));
      ul.append(li);
    });
    box.append(ul);
    return box;
  }

  function kpiTiles(a) {
    var byName = {};
    a.metrics.forEach(function (m) { byName[m.name] = m; });
    var grid = el("div", "kpi-grid");
    grid.setAttribute("data-testid", "research-kpis");
    KEY_METRICS.forEach(function (name) {
      var m = byName[name];
      if (!m) return;
      var tile = el("div", "kpi");
      tile.setAttribute("data-testid", "kpi");
      var vs = m.change != null ? " vs " + comparisonOf(a).label.toLowerCase() : "";
      tile.append(el("span", "kpi-name", name), el("b", "kpi-value", value(m, m.current)), el("span", "kpi-change " + changeClass(m), changeText(m) + vs));
      grid.append(tile);
    });
    return grid;
  }

  function metricsTable(a) {
    var wrap = el("div", "rc-table-wrap");
    var table = el("table", "rc-metrics");
    table.setAttribute("data-testid", "research-metrics");
    var thead = el("thead"), tr = el("tr");
    ["Metric", comparisonOf(a).label, "This period", "Change"].forEach(function (h) { var th = el("th", null, h); th.scope = "col"; tr.append(th); });
    thead.append(tr); table.append(thead);
    var tbody = el("tbody");
    a.metrics.forEach(function (m) {
      var row = el("tr");
      row.setAttribute("data-testid", "metric-row");
      var th = el("th"); th.scope = "row";
      th.append(el("span", "rc-metric", m.name), el("span", "rc-period", m.period + " · " + m.basis));
      var ch = el("td", "rc-change " + changeClass(m), m.change == null ? "n/a" : changeText(m));
      row.append(th, el("td", null, value(m, m.prior)), el("td", null, value(m, m.current)), ch);
      tbody.append(row);
    });
    table.append(tbody); wrap.append(table);
    return wrap;
  }

  function moreSection(a) {
    var details = el("details", "rp-more");
    details.setAttribute("data-testid", "research-more");
    var summary = el("summary", null);
    summary.append(el("span", null, "All fundamentals · Drivers & guidance · Sources"), el("span", "rp-more-toggle"));
    details.append(summary);
    var body = el("div", "rp-more-body");
    if (a.metrics.length) { body.append(el("h4", "rp-h", "All fundamentals"), metricsTable(a)); }
    var cols = el("div", "rc-cols");
    var drivers = el("section", "rc-drivers");
    drivers.setAttribute("data-testid", "research-drivers");
    drivers.append(el("h4", "rp-h", a.analyst === "claude" ? "What drove the results" : "What changed"));
    var dl = el("ul");
    (a.drivers.length ? a.drivers : ["No comparison with " + comparisonOf(a).label.toLowerCase() + " is available."]).forEach(function (d) { dl.append(el("li", null, d)); });
    drivers.append(dl);
    var guidance = el("section", "rc-guidance");
    guidance.setAttribute("data-testid", "research-guidance");
    guidance.append(el("h4", "rp-h", "Guidance and outlook"), el("p", null, a.guidance));
    cols.append(drivers, guidance);
    body.append(cols);
    var foot = el("footer", "rc-sources");
    foot.append(el("span", null, "Sources: "));
    a.sources.forEach(function (s, i) {
      var link = el("a", null, s.label);
      link.href = s.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      if (i) foot.append(document.createTextNode(" · "));
      foot.append(link);
    });
    var who = a.analyst === "claude" ? "Drivers, guidance and some risks written by Claude from the filed figures and recent headlines." : "Computed from the filed figures.";
    foot.append(el("span", "rc-disclaimer", " " + who + " " + a.disclaimer));
    body.append(foot);
    details.append(body);
    return details;
  }

  function panelHead(symbol, name, level) {
    var head = el("div", "rp-head");
    var title = el("h3", "rp-title");
    title.append(el("span", "rp-sym", symbol));
    if (name) title.append(el("span", "rp-name", name));
    var side = el("div", "rp-side");
    if (level) side.append(levelBadge(level));
    var news = el("button", "rp-news", "Top news");
    news.type = "button";
    news.setAttribute("data-testid", "research-news");
    news.addEventListener("click", function () { openNews(symbol, name || ""); });
    side.append(news);
    head.append(title, side);
    return head;
  }

  function renderPanel() {
    if (!panelEl) return;
    if (!selected) { panelEl.hidden = true; panelEl.replaceChildren(); return; }
    panelEl.hidden = false;
    panelEl.dataset.symbol = selected;
    var a = analyses[selected];
    var openMore = !!panelEl.querySelector("details[open]") && panelEl.dataset.shown === selected;
    panelEl.dataset.shown = selected;
    if (!a) {
      var msg = failures[selected];
      panelEl.replaceChildren(panelHead(selected, "", null),
        el("p", msg ? "rc-muted" : "rc-loading", msg || "Analyzing the latest filings…"));
      return;
    }
    var headline = el("p", "rp-headline", a.headline);
    headline.setAttribute("data-testid", "research-headline");
    var meta = el("p", "rp-meta", (a.period ? a.period + " · " : "") + "GAAP · " + (a.analyst === "claude" ? "AI analysis" : "Rule-based analysis"));
    var c = comparisonOf(a);
    var compare = el("p", "rp-compare",
      (c.key === "1M" ? "Companies report every quarter, so for 1 month the fundamentals compare with the prior quarter. " :
        "Fundamentals compare the latest period with the same period " + (c.earlier || "a year earlier") + ". ") +
      "The share price uses " + c.price_window + ".");
    compare.setAttribute("data-testid", "research-compare");
    var parts = [panelHead(selected, a.name, riskLevel(a)), headline, meta, compare, riskList(a)];
    if (a.metrics.length) parts.push(kpiTiles(a));
    var more = moreSection(a);
    if (openMore) more.open = true;
    parts.push(more);
    panelEl.replaceChildren.apply(panelEl, parts);
  }

  // Loading -------------------------------------------------------------
  function pump() {
    while (running < MAX_PARALLEL && queue.length) {
      (function (symbol) {
        running++;
        var asked = period;
        fetch("/api/research/" + encodeURIComponent(symbol) + "?period=" + asked)
          .then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (data) { return { ok: r.ok, data: data }; });
          })
          .then(function (res) {
            if (!tabFor(symbol) || asked !== period) return;
            if (res.ok) analyses[symbol] = res.data;
            else failures[symbol] = res.data.detail || "Analysis isn't available right now.";
          })
          .catch(function () { if (asked === period) failures[symbol] = "Analysis isn't available right now. Please try again later."; })
          .then(function () {
            running--;
            paintTab(symbol);
            if (symbol === selected) renderPanel();
            pump();
          });
      })(queue.shift());
    }
  }

  function addResearch(symbol) {
    if (!tabsEl || tabFor(symbol)) return;
    tabsEl.append(makeTab(symbol));
    queue.push(symbol);
    if (!selected) select(symbol);
    pump();
  }

  function removeResearch(symbol) {
    if (!tabsEl) return;
    var tab = tabFor(symbol);
    if (tab) tab.remove();
    delete analyses[symbol];
    delete failures[symbol];
    queue = queue.filter(function (s) { return s !== symbol; });
    if (selected === symbol) {
      var first = tabsEl.querySelector("[role=tab]");
      selected = null;
      if (first) select(first.dataset.symbol); else renderPanel();
    }
  }

  // A new period re-runs the research for every company (the server caches each period).
  function periodChanged() {
    if (!tabsEl) return;
    analyses = {}; failures = {};
    queue = Array.prototype.map.call(tabsEl.querySelectorAll("[role=tab]"), function (t) { return t.dataset.symbol; });
    queue.forEach(paintTab);
    renderPanel();
    pump();
  }

  onAdd = addResearch;
  onRemove = removeResearch;
  onPeriod = periodChanged;

  render();
  setPeriod(period);
  fetchQuotes(watchlist);
  fetchPerformance(watchlist);
  watchlist.forEach(addResearch);
  setInterval(function () { fetchQuotes(watchlist); }, REFRESH_MS);
  setInterval(function () { fetchPerformance(watchlist); }, 10 * REFRESH_MS);
})();

// Show "5m ago" style times next to headlines.
(function () {
  "use strict";
  function relTimes() {
    var now = Date.now();
    document.querySelectorAll(".news-meta time[datetime]").forEach(function (t) {
      var d = new Date(t.getAttribute("datetime"));
      if (isNaN(d)) return;
      var mins = Math.round((now - d) / 60000);
      t.title = d.toLocaleString();
      t.textContent = mins < 1 ? "just now" : mins < 60 ? mins + "m ago" : mins < 1440 ? Math.floor(mins / 60) + "h ago" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    });
  }
  relTimes();
  setInterval(relTimes, 60000);
})();

// Keep --header-h equal to the sticky header's real height, so the source sidebar
// sticks at exactly its starting position and doesn't move while the page scrolls.
(function () {
  "use strict";
  var header = document.querySelector(".site-header");
  if (!header) return;
  function update() {
    document.documentElement.style.setProperty("--header-h", header.offsetHeight + "px");
  }
  update();
  if ("ResizeObserver" in window) new ResizeObserver(update).observe(header);
  else window.addEventListener("resize", update);
})();

// Dark mode toggle. The inline script in <head> already applied the theme before the first
// paint; this keeps the button in sync, saves an explicit choice, and follows the system
// setting live until the user has picked one.
(function () {
  "use strict";
  var KEY = "theme";
  var root = document.documentElement;
  var button = document.getElementById("theme-toggle");
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function saved() {
    try {
      var t = localStorage.getItem(KEY);
      return t === "light" || t === "dark" ? t : null;
    } catch (e) { return null; }
  }
  function systemTheme() { return media && media.matches ? "dark" : "light"; }
  function current() { return root.getAttribute("data-theme") === "dark" ? "dark" : "light"; }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    if (!button) return;
    var dark = theme === "dark";
    button.setAttribute("aria-pressed", dark ? "true" : "false");
    button.title = dark ? "Switch to light mode" : "Switch to dark mode";
  }

  apply(saved() || current() || systemTheme());

  if (button) {
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch (e) {}
    });
  }

  if (media) {
    var onChange = function () { if (!saved()) apply(systemTheme()); };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }

  // Another tab changed the choice: follow it.
  window.addEventListener("storage", function (ev) {
    if (ev.key === KEY) apply(saved() || systemTheme());
  });
})();
