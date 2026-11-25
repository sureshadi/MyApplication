"""The testing agent's guardrails, skip rule, result parsing, commit decision and PR comment.

The Claude agent itself isn't called here: these cover the plain code around it that decides what it may do and
what gets reported and committed."""

from pathlib import Path

import pytest

from agents import testing_agent as ta
from agents.testing_agent import CaseResult, Verification

PR = 25


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests/e2e/agent").mkdir(parents=True)
    return tmp_path


# --- which PRs run -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changed, skip",
    [
        (["app/main.py"], False),
        (["README.md", "app/static/app.js"], False),
        (["requirements.txt"], False),
        (["README.md", "docs/screenshots/a.png"], True),
        (["tests/e2e/test_login.py", ".github/workflows/tests.yml"], True),
        (["agents/testing_agent.py", "requirements-agent.txt"], True),
        ([], True),
    ],
)
def test_runs_only_when_the_web_app_changes(changed, skip):
    assert ta.should_skip(changed) is skip


# --- guardrails ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["tests/e2e/agent/test_pr25_sort.py", "tests/e2e/agent/test_pr25_dark_mode_2.py"])
def test_agent_may_write_its_own_test_files(repo, path):
    assert ta.check_tool("Write", {"file_path": path}, repo, PR) is None
    assert ta.check_tool("Edit", {"file_path": str(repo / path)}, repo, PR) is None


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py",                              # app code
        "tests/e2e/conftest.py",                    # shared test setup
        "tests/e2e/agent/test_pr26_other.py",       # another PR's file
        "tests/e2e/agent/conftest.py",              # not a test file
        "tests/e2e/agent/sub/test_pr25_x.py",       # nested folder
        "tests/e2e/agent/../../../app/main.py",     # path escape
        "/etc/passwd",
        ".github/workflows/tests.yml",
    ],
)
def test_agent_cannot_write_anywhere_else(repo, path):
    assert ta.check_tool("Write", {"file_path": path}, repo, PR) is not None
    assert ta.check_tool("Edit", {"file_path": path}, repo, PR) is not None


def test_agent_may_read_the_repo_but_not_outside_it(repo):
    assert ta.check_tool("Read", {"file_path": "app/main.py"}, repo, PR) is None
    assert ta.check_tool("Grep", {"pattern": "data-testid"}, repo, PR) is None
    assert ta.check_tool("Glob", {"pattern": "**/*.py", "path": "tests"}, repo, PR) is None
    assert ta.check_tool("Read", {"file_path": "/etc/passwd"}, repo, PR) is not None
    assert ta.check_tool("Grep", {"pattern": "x", "path": "/home"}, repo, PR) is not None


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest -m e2e tests/e2e/agent/test_pr25_sort.py -q",
        "pytest -m e2e tests/e2e/agent/test_pr25_sort.py::test_sorts_biggest_mover_first -x",
        "git diff origin/main...HEAD -- app/static/app.js",
        "git log --oneline -5",
    ],
)
def test_allowed_commands(command):
    assert ta._check_command(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest -m e2e",                                        # whole suite, not just the agent's tests
        "pytest tests/unit",                                    # other tests
        "python -m pytest tests/e2e/agent/x.py; rm -rf app",    # chained command
        "pytest tests/e2e/agent/x.py | tee out",                # pipe
        "pytest tests/e2e/agent/$(whoami).py",                  # subshell
        "curl https://example.com",
        "pip install requests",
        "git push origin HEAD",
        "git commit -am x",
        "env",
    ],
)
def test_refused_commands(command):
    assert ta._check_command(command) is not None


def test_other_tools_are_refused(repo):
    for tool in ("WebFetch", "WebSearch", "Task", "NotebookEdit"):
        assert ta.check_tool(tool, {}, repo, PR) is not None


def test_final_report_tool_is_allowed(repo):
    # With output_format set, the agent returns its report through the StructuredOutput tool.
    assert ta.check_tool("StructuredOutput", {"summary": "x"}, repo, PR) is None


# --- results ---------------------------------------------------------------------------------------------------

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.e2e.agent.test_pr25_sort" name="test_button_shows[chromium]" time="1.2"/>
  <testcase classname="tests.e2e.agent.test_pr25_sort" name="test_sorts_biggest_first[chromium]" time="2.0">
    <failure message="AssertionError: Locator expected to have text 'NVDA'&#10;Actual: 'AAPL'">trace</failure>
  </testcase>
  <testcase classname="tests.e2e.agent.test_pr25_sort" name="test_phone[chromium]" time="0.1">
    <skipped message="skip"/>
  </testcase>
</testsuite></testsuites>"""


def test_parse_junit(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(JUNIT)
    results = ta.parse_junit(path)
    assert [(r.nodeid, r.status) for r in results] == [
        ("tests/e2e/agent/test_pr25_sort.py::test_button_shows[chromium]", "passed"),
        ("tests/e2e/agent/test_pr25_sort.py::test_sorts_biggest_first[chromium]", "failed"),
        ("tests/e2e/agent/test_pr25_sort.py::test_phone[chromium]", "skipped"),
    ]
    assert results[1].message == "AssertionError: Locator expected to have text 'NVDA'"
    assert ta.parse_junit(tmp_path / "missing.xml") == []


NODE = "tests/e2e/agent/test_pr25_sort.py::"


def verification(*statuses, flaky=()):
    return Verification([CaseResult(NODE + name, status) for name, status in statuses], list(flaky))


BUG = {"test": "test_sorts_biggest_first", "problem": "Sorts ascending.", "file": "app/static/app.js",
       "suggested_fix": "-  a - b\n+  b - a"}


def test_commit_when_all_pass():
    assert ta.should_commit(verification(("test_a[chromium]", "passed")), {}) == (True, "")


def test_commit_when_every_failure_is_a_confirmed_app_bug():
    v = verification(("test_a[chromium]", "passed"), ("test_sorts_biggest_first[chromium]", "failed"))
    assert ta.should_commit(v, {"app_bugs": [BUG]})[0] is True


def test_no_commit_when_a_failure_is_unexplained():
    v = verification(("test_sorts_biggest_first[chromium]", "failed"))
    commit, why = ta.should_commit(v, {"app_bugs": []})
    assert commit is False and "not confirmed" in why


def test_no_commit_when_flaky_or_empty():
    v = verification(("test_a[chromium]", "failed"), flaky=[NODE + "test_a[chromium]"])
    assert ta.should_commit(v, {})[0] is False
    assert ta.should_commit(Verification(), {}) == (False, "the agent wrote no tests")


def test_comment_reports_results_and_the_suggested_fix():
    v = verification(("test_button_shows[chromium]", "passed"), ("test_sorts_biggest_first[chromium]", "failed"))
    report = {
        "summary": "Adds a sort button to Portfolio.",
        "tests": [{"name": "test_button_shows", "checks": "The button is visible | labelled"},
                  {"name": "test_sorts_biggest_first", "checks": "Biggest mover comes first"}],
        "app_bugs": [BUG], "notes": "", "_cost_usd": 0.8312, "_turns": 17,
    }
    comment = ta.render_comment(PR, report, v, True, "")
    assert "Adds a sort button to Portfolio." in comment
    assert "**2 tests** in `tests/e2e/agent/test_pr25_*.py`: 1 passed, 1 failed" in comment
    assert "| `test_button_shows[chromium]` | The button is visible \\| labelled | passed |" in comment
    assert "### Likely bugs in this PR" in comment
    assert "```diff\n-  a - b\n+  b - a\n```" in comment
    assert "Failures not explained" not in comment
    assert "17 turns · $0.83" in comment
    assert comment.endswith(ta.COMMENT_MARKER)


def test_comment_explains_why_tests_were_not_committed():
    v = verification(("test_x[chromium]", "failed"))
    v.results[0].message = "Timeout 5000ms"
    comment = ta.render_comment(PR, {"_error": "error_max_turns"}, v, False, "some failing tests were not confirmed")
    assert "stopped early (error_max_turns)" in comment
    assert "- `test_x[chromium]`: Timeout 5000ms" in comment
    assert "Tests were not committed because some failing tests were not confirmed" in comment


def test_prompt_inlines_small_diffs_only():
    small = ta.build_prompt(PR, "Sort button", ["app/static/app.js"], "+ sort")
    assert "```diff\n+ sort\n```" in small and "- app/static/app.js" in small
    big = ta.build_prompt(PR, "Big", ["app/main.py"], "x" * (ta.MAX_INLINE_DIFF_CHARS + 1))
    assert "too long to paste" in big and "git diff {base}...HEAD" in big


def test_skipped_pr_gets_a_short_comment_and_no_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "git", lambda repo, *args: "README.md\n")
    out = tmp_path / "out"
    assert ta.main(["--pr", "25", "--out", str(out), "--repo", str(tmp_path)]) == 0
    assert "doesn't change the web app" in (out / "comment.md").read_text()
    assert (out / "outcome.json").read_text() == '{"commit": false}'


def test_missing_api_key_is_reported_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "git", lambda repo, *args: "app/main.py\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gh_output = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    out = tmp_path / "out"
    assert ta.main(["--pr", "25", "--out", str(out), "--repo", str(tmp_path)]) == 0
    assert "ANTHROPIC_API_KEY" in (out / "comment.md").read_text()
    assert gh_output.read_text() == "commit=false\n"
