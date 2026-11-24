// Ticker suggestions as you type, like Google. Used by the header search box and the
// My Portfolio "Add ticker" box. onPick(symbol) runs when a suggestion is chosen.
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

// My Portfolio page: every ticker with live prices; add and remove tickers, saved in this browser.
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
  var onAdd = function () {}, onRemove = function () {};

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
    var el = chipsEl.querySelector('[data-symbol="' + q.symbol + '"]');
    if (!el) return;
    var px = el.querySelector(".px"), chg = el.querySelector(".chg");
    var name = el.querySelector(".name");
    if (name && q.name) name.textContent = q.name;
    if (q.error) {
      px.textContent = "";
      chg.textContent = "n/a";
      chg.className = "chg na";
      return;
    }
    px.textContent = fmt(q.price);
    var pct = q.change_percent;
    chg.textContent = (pct > 0 ? "+" : "") + pct.toFixed(2) + "%";
    chg.className = "chg " + (pct > 0 ? "up" : pct < 0 ? "down" : "flat");
  }

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

  // ---------- Market research: one analysis per company, risks first ----------
  var researchEl = document.querySelector("[data-testid=research-list]");
  var summaryEl = document.querySelector("[data-testid=risk-summary]");
  var analyses = {};
  var queue = [];
  var running = 0;
  var MAX_PARALLEL = 3;
  var SEV_LABEL = { high: "High", medium: "Medium", low: "Low" };
  var SEV_RANK = { high: 0, medium: 1, low: 2 };

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

  function changeCell(m) {
    var td = el("td", "rc-change");
    if (m.change == null) { td.textContent = "n/a"; return td; }
    td.textContent = (m.change > 0 ? "+" : "") + m.change.toFixed(1) + (m.change_unit === "pp" ? " pp" : "%");
    td.classList.add(m.change > 0 ? "up" : m.change < 0 ? "down" : "flat");
    return td;
  }

  function riskItem(r) {
    var li = el("li", "risk sev-" + r.severity);
    li.setAttribute("data-testid", "risk");
    li.dataset.severity = r.severity;
    li.append(el("span", "sev", SEV_LABEL[r.severity] || r.severity), el("strong", "risk-title", r.title), el("p", "risk-detail", r.detail));
    return li;
  }

  function cardShell(symbol) {
    var card = el("article", "research-card");
    card.dataset.symbol = symbol;
    card.setAttribute("data-testid", "research-card");
    var head = el("header", "rc-head");
    var sym = el("button", "rc-sym", symbol);
    sym.type = "button";
    sym.title = "Show top news for " + symbol;
    sym.setAttribute("data-testid", "research-symbol");
    sym.addEventListener("click", function () { openNews(symbol, (analyses[symbol] || {}).name || ""); });
    head.append(sym, el("span", "rc-name"), el("span", "rc-badge"));
    var body = el("div", "rc-body");
    body.append(el("p", "rc-loading", "Analyzing the latest filings…"));
    card.append(head, body);
    return card;
  }

  function fillCard(card, a) {
    var head = card.querySelector(".rc-head");
    head.querySelector(".rc-name").textContent = a.name;
    var badge = head.querySelector(".rc-badge");
    badge.textContent = a.analyst === "claude" ? "AI analysis" : "Rule-based";
    badge.title = a.analyst === "claude" ? "Written by Claude from the filed figures and recent headlines" : "Computed from the filed figures. Set ANTHROPIC_API_KEY for AI drivers and guidance.";
    badge.dataset.analyst = a.analyst;
    var body = card.querySelector(".rc-body");
    body.replaceChildren();

    // 1. Risks first.
    var risks = el("section", "rc-risks");
    risks.setAttribute("data-testid", "research-risks");
    risks.append(el("h4", null, "Risks and red flags"));
    if (a.risks.length) {
      var ul = el("ul", "risk-list");
      a.risks.forEach(function (r) { ul.append(riskItem(r)); });
      risks.append(ul);
    } else {
      risks.append(el("p", "rc-muted", "No red flags found in the figures checked."));
    }
    body.append(risks);

    // 2. Headline.
    var hl = el("p", "rc-headline", a.headline);
    hl.setAttribute("data-testid", "research-headline");
    body.append(hl);

    // 3. Key metrics table.
    if (a.metrics.length) {
      var wrap = el("div", "rc-table-wrap");
      var table = el("table", "rc-metrics");
      table.setAttribute("data-testid", "research-metrics");
      var thead = el("thead"); var tr = el("tr");
      ["Metric", "This period", "Prior year", "Change"].forEach(function (h) { var th = el("th", null, h); th.scope = "col"; tr.append(th); });
      thead.append(tr); table.append(thead);
      var tbody = el("tbody");
      a.metrics.forEach(function (m) {
        var row = el("tr");
        row.setAttribute("data-testid", "metric-row");
        var th = el("th"); th.scope = "row";
        th.append(el("span", "rc-metric", m.name), el("span", "rc-period", m.period + " · " + m.basis));
        row.append(th, el("td", null, value(m, m.current)), el("td", null, value(m, m.prior)), changeCell(m));
        tbody.append(row);
      });
      table.append(tbody); wrap.append(table); body.append(wrap);
    }

    // 4. Drivers and 5. guidance.
    var cols = el("div", "rc-cols");
    var drivers = el("section", "rc-drivers");
    drivers.setAttribute("data-testid", "research-drivers");
    drivers.append(el("h4", null, a.analyst === "claude" ? "What drove the results" : "What changed"));
    var dl = el("ul");
    (a.drivers.length ? a.drivers : ["No year-over-year comparison is available."]).forEach(function (d) { dl.append(el("li", null, d)); });
    drivers.append(dl);
    var guidance = el("section", "rc-guidance");
    guidance.setAttribute("data-testid", "research-guidance");
    guidance.append(el("h4", null, "Guidance and outlook"), el("p", null, a.guidance));
    cols.append(drivers, guidance);
    body.append(cols);

    // 6. Sources.
    var foot = el("footer", "rc-sources");
    foot.append(el("span", null, "Sources: "));
    a.sources.forEach(function (s, i) {
      var link = el("a", null, s.label);
      link.href = s.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      if (i) foot.append(document.createTextNode(" · "));
      foot.append(link);
    });
    foot.append(el("span", "rc-disclaimer", " " + a.disclaimer));
    body.append(foot);
  }

  function failCard(card, message) {
    card.classList.add("rc-failed");
    var body = card.querySelector(".rc-body");
    body.replaceChildren(el("p", "rc-muted", message));
  }

  function renderSummary() {
    if (!summaryEl) return;
    var all = [];
    watchlist.forEach(function (s) {
      var a = analyses[s];
      if (!a) return;
      a.risks.forEach(function (r) { if (r.severity !== "low") all.push({ symbol: s, risk: r }); });
    });
    all.sort(function (x, y) { return SEV_RANK[x.risk.severity] - SEV_RANK[y.risk.severity]; });
    var list = summaryEl.querySelector("[data-testid=risk-summary-list]");
    list.replaceChildren.apply(list, all.slice(0, 8).map(function (x) {
      var li = riskItem(x.risk);
      li.querySelector(".risk-detail").remove();
      var tag = el("button", "risk-sym", x.symbol);
      tag.type = "button";
      tag.title = "Show top news for " + x.symbol;
      tag.addEventListener("click", function () { openNews(x.symbol, analyses[x.symbol] ? analyses[x.symbol].name : ""); });
      li.insertBefore(tag, li.querySelector(".risk-title"));
      li.setAttribute("data-testid", "summary-risk");
      return li;
    }));
    summaryEl.hidden = all.length === 0;
  }

  function pump() {
    while (running < MAX_PARALLEL && queue.length) {
      (function (symbol) {
        running++;
        fetch("/api/research/" + encodeURIComponent(symbol))
          .then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (data) { return { ok: r.ok, data: data }; });
          })
          .then(function (res) {
            var card = researchEl.querySelector('[data-symbol="' + symbol + '"]');
            if (!card) return;
            if (!res.ok) { failCard(card, res.data.detail || "Analysis isn't available right now."); return; }
            analyses[symbol] = res.data;
            fillCard(card, res.data);
            renderSummary();
          })
          .catch(function () {
            var card = researchEl.querySelector('[data-symbol="' + symbol + '"]');
            if (card) failCard(card, "Analysis isn't available right now. Please try again later.");
          })
          .then(function () { running--; pump(); });
      })(queue.shift());
    }
  }

  function addResearch(symbol) {
    if (!researchEl || researchEl.querySelector('[data-symbol="' + symbol + '"]')) return;
    researchEl.append(cardShell(symbol));
    queue.push(symbol);
    pump();
  }

  function removeResearch(symbol) {
    if (!researchEl) return;
    var card = researchEl.querySelector('[data-symbol="' + symbol + '"]');
    if (card) card.remove();
    delete analyses[symbol];
    queue = queue.filter(function (s) { return s !== symbol; });
    renderSummary();
  }

  onAdd = addResearch;
  onRemove = removeResearch;

  render();
  fetchQuotes(watchlist);
  watchlist.forEach(addResearch);
  setInterval(function () { fetchQuotes(watchlist); }, REFRESH_MS);
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
