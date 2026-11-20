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
      })
      .catch(function () { errorEl.textContent = "Couldn't add " + symbol + ". Please try again."; })
      .then(function () { submit.disabled = false; });
  });

  render();
  fetchQuotes(watchlist);
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
