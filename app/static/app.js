// Top bar: a "My Portfolio" tab that reveals your tickers with live prices; add (+) and remove
// tickers, saved in this browser.
(function () {
  "use strict";

  var STORAGE_KEY = "mh.watchlist.v1";
  var SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;
  var MAX_TICKERS = 25;
  var REFRESH_MS = 60000;

  var bar = document.querySelector("[data-testid=ticker-bar]");
  if (!bar) return;
  var chipsEl = bar.querySelector("#watchlist");
  var addBtn = bar.querySelector("[data-testid=add-ticker]");
  var form = bar.querySelector("[data-testid=add-form]");
  var input = form.querySelector("input");
  var errorEl = form.querySelector("[data-testid=add-error]");
  var cancelBtn = form.querySelector(".add-cancel");
  var defaults = (bar.dataset.default || "").split(",").filter(Boolean);
  var active = bar.dataset.active || "";
  var tab = bar.querySelector("[data-testid=portfolio-tab]");
  var panel = bar.querySelector("[data-testid=portfolio]");
  var countEl = bar.querySelector("[data-testid=portfolio-count]");

  function setOpen(open) {
    panel.hidden = !open;
    tab.setAttribute("aria-expanded", open ? "true" : "false");
    tab.classList.toggle("open", open);
    if (!open) closeForm();
  }
  tab.addEventListener("click", function () { setOpen(panel.hidden); });

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

  function chip(symbol) {
    var el = document.createElement("div");
    el.className = "chip ticker-chip" + (symbol === active ? " active" : "");
    el.dataset.symbol = symbol;
    el.setAttribute("data-testid", "ticker-chip");

    var link = document.createElement("a");
    link.className = "chip-link";
    link.href = "/ticker/" + encodeURIComponent(symbol);
    var sym = document.createElement("span"); sym.className = "sym"; sym.textContent = symbol;
    var px = document.createElement("span"); px.className = "px";
    var chg = document.createElement("span"); chg.className = "chg";
    link.append(sym, px, chg);

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
  function closeForm() { form.hidden = true; errorEl.textContent = ""; }

  addBtn.addEventListener("click", function () { form.hidden ? openForm() : closeForm(); });
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeForm(); });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var symbol = input.value.trim().toUpperCase();
    errorEl.textContent = "";
    if (!SYMBOL_RE.test(symbol)) { errorEl.textContent = "Enter a valid ticker symbol, like TSLA."; return; }
    if (watchlist.indexOf(symbol) !== -1) { errorEl.textContent = symbol + " is already in your bar."; return; }
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
      })
      .catch(function () { errorEl.textContent = "Couldn't add " + symbol + ". Please try again."; })
      .then(function () { submit.disabled = false; });
  });

  // Show "5m ago" style times next to headlines.
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

  render();
  fetchQuotes(watchlist);
  relTimes();
  setInterval(function () { fetchQuotes(watchlist); relTimes(); }, REFRESH_MS);
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
