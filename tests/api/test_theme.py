"""Dark mode: every page has the toggle and applies the theme before the first paint."""

import re

import pytest

PAGES = ["/", "/news/technology", "/news/health", "/portfolio", "/ticker/AAPL", "/ticker/ZZZZ"]


@pytest.mark.parametrize("path", PAGES)
class TestThemeOnEveryPage:
    def test_toggle_button_is_present_and_accessible(self, client, path):
        html = client.get(path).text
        button = re.search(r'<button[^>]*data-testid="theme-toggle"[^>]*>', html, re.S)
        assert button, path
        tag = button.group(0)
        assert 'type="button"' in tag
        assert 'aria-label="Dark mode"' in tag
        assert 'aria-pressed="false"' in tag
        assert html.count('data-testid="theme-toggle"') == 1

    def test_theme_script_runs_in_head_before_stylesheet(self, client, path):
        html = client.get(path).text
        head = html.split("</head>", 1)[0]
        script_at = head.find('data-testid="theme-init"')
        assert script_at != -1, path
        assert script_at < head.find("style.css"), "theme must be set before the stylesheet loads"
        script = head[script_at:head.index("</script>", script_at)]
        assert 'localStorage.getItem("theme")' in script
        assert "try {" in script and "catch (e)" in script
        assert "(prefers-color-scheme: dark)" in script
        assert 'setAttribute("data-theme"' in script

    def test_color_scheme_meta(self, client, path):
        assert '<meta name="color-scheme" content="light dark">' in client.get(path).text


class TestThemeAssets:
    def test_css_defines_dark_tokens_for_attribute_and_system(self, client):
        css = client.get("/static/style.css").text
        assert ':root[data-theme="dark"] {' in css
        assert ":root:not([data-theme]) {" in css
        dark = css[css.index(':root[data-theme="dark"] {'):]
        dark = dark[: dark.index("}")]
        for token in ("--bg:", "--surface:", "--surface-solid:", "--fg:", "--muted:", "--border:", "--shadow-pop:", "--src-cnbc:"):
            assert token in dark, token
        assert "color-scheme: dark;" in dark

    def test_components_use_tokens_not_fixed_colours(self, client):
        css = client.get("/static/style.css").text
        # Source colours come from tokens so they can change per theme.
        assert re.search(r'\[data-source="CNBC"\] \{ --src: #', css) is None
        assert ".suggestions {" in css and "box-shadow: var(--shadow-pop);" in css

    def test_toggle_icons_follow_theme(self, client):
        css = client.get("/static/style.css").text
        assert '[data-theme="dark"] .theme-toggle .icon-sun { display: block; }' in css

    def test_script_saves_choice_and_syncs_button(self, client):
        js = client.get("/static/app.js").text
        assert 'getElementById("theme-toggle")' in js
        assert "localStorage.setItem(KEY, next)" in js
        assert 'setAttribute("aria-pressed"' in js
        assert '"(prefers-color-scheme: dark)"' in js
