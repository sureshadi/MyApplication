"""Testing agent: writes and runs Playwright tests for a pull request, then reports back.

Runs in GitHub Actions on every pull request that changes the web app (see .github/workflows/testing-agent.yml):

    python -m agents.testing_agent --base origin/main --pr 25 --out test-results/agent

1. Collects the files the PR changes. A PR that doesn't touch the app (app/, requirements.txt) is skipped.
2. Starts a Claude coding agent (Claude Agent SDK, Claude Opus 5.5) with the diff and the repo's test conventions.
   The agent may read the repo, write test files only as tests/e2e/agent/test_pr<N>_*.py, and run only pytest
   and read-only git commands. Every tool call goes through `check_tool`, so these limits are enforced in code,
   not just asked for in the prompt.
3. Runs the agent's tests again itself (the agent's own claims are not trusted), reruns failures once to spot
   flaky tests, and writes:
     - comment.md:   the PR comment (tests written, results, likely app bugs with a suggested fix)
     - outcome.json: whether the workflow should commit the tests to the PR branch
     - junit XML files and the agent's structured report
The workflow, not the agent, commits the tests and posts the comment, so the agent never holds a GitHub token.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "claude-opus-5-5"
AGENT_DIR = Path("tests/e2e/agent")
MAX_TURNS = 40
MAX_BUDGET_USD = 3.0
# Above this size the diff isn't pasted into the prompt; the agent reads it file by file with `git diff`.
MAX_INLINE_DIFF_CHARS = 40_000
COMMENT_MARKER = "<!-- testing-agent -->"

# Changes under these paths are the web app. A PR that touches none of them has nothing new to browser-test.
APP_PATHS = ("app/",)
APP_FILES = ("requirements.txt",)

READ_TOOLS = {"Read", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}
ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "MultiEdit", "Bash"]
SHELL_METACHARACTERS = re.compile(r"[;&|`$<>(){}\n\\]")
GIT_READ_ONLY = {"diff", "log", "show", "status"}


# ---------------------------------------------------------------------------------------------------------------
# Which PRs to test


def is_app_change(path: str) -> bool:
    return path.startswith(APP_PATHS) or path in APP_FILES


def should_skip(changed: list[str]) -> bool:
    """True when the PR changes nothing in the web app (only docs, tests, CI or the agent itself)."""
    return not any(is_app_change(p) for p in changed)


def test_file_prefix(pr: int) -> str:
    return f"test_pr{pr}_"


# ---------------------------------------------------------------------------------------------------------------
# Guardrails: every tool call the agent makes is checked here first


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve(raw: str, repo: Path) -> Path:
    p = Path(raw)
    return (p if p.is_absolute() else repo / p).resolve()


def check_tool(name: str, tool_input: dict, repo: Path, pr: int) -> str | None:
    """None when the call is allowed, otherwise the reason it is refused (shown to the agent)."""
    repo = repo.resolve()
    agent_dir = (repo / AGENT_DIR).resolve()

    if name in READ_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("path")
        if raw and not _inside(_resolve(raw, repo), repo):
            return "Only files inside the repository can be read."
        return None

    if name in WRITE_TOOLS:
        raw = tool_input.get("file_path") or ""
        target = _resolve(raw, repo)
        if target.parent != agent_dir:
            return f"Tests may only be written directly in {AGENT_DIR}/."
        if not re.fullmatch(rf"{test_file_prefix(pr)}[a-z0-9_]+\.py", target.name):
            return f"Test files must be named {test_file_prefix(pr)}<topic>.py (lowercase letters, digits, _)."
        return None

    if name == "Bash":
        return _check_command(tool_input.get("command", ""))

    if name == "StructuredOutput":  # how the agent hands back its final report (output_format)
        return None

    return f"The {name} tool is not available to the testing agent."


def _check_command(command: str) -> str | None:
    if SHELL_METACHARACTERS.search(command):
        return "Run one plain command: no pipes, redirects, variables, subshells or chained commands."
    try:
        argv = shlex.split(command)
    except ValueError:
        return "The command could not be parsed."
    if argv[:3] == ["python", "-m", "pytest"]:
        args = argv[3:]
    elif argv[:1] == ["pytest"]:
        args = argv[1:]
    elif argv[:1] == ["git"] and len(argv) > 1 and argv[1] in GIT_READ_ONLY:
        return None
    else:
        return f"Only `python -m pytest {AGENT_DIR}/...` and read-only git commands (diff, log, show, status) may run."
    paths = [a for a in args if not a.startswith("-") and ("/" in a or a.endswith(".py"))]
    if not paths or not all(p.split("::")[0].startswith(f"{AGENT_DIR}/") for p in paths):
        return f"pytest may only run tests under {AGENT_DIR}/ (add -m e2e to select browser tests)."
    return None


# ---------------------------------------------------------------------------------------------------------------
# Running tests ourselves (ground truth for the comment)


@dataclass
class CaseResult:
    nodeid: str
    status: str  # passed | failed | skipped
    message: str = ""


@dataclass
class Verification:
    results: list[CaseResult] = field(default_factory=list)
    flaky: list[str] = field(default_factory=list)

    def by_status(self, status: str) -> list[CaseResult]:
        return [r for r in self.results if r.status == status]


def parse_junit(path: Path) -> list[CaseResult]:
    if not path.exists():
        return []
    results = []
    for case in ET.parse(path).getroot().iter("testcase"):
        module = case.get("classname", "").replace(".", "/")
        nodeid = f"{module}.py::{case.get('name', '')}"
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is not None:
            text = (failure.get("message") or failure.text or "").strip()
            results.append(CaseResult(nodeid, "failed", text.splitlines()[0][:300] if text else ""))
        elif case.find("skipped") is not None:
            results.append(CaseResult(nodeid, "skipped"))
        else:
            results.append(CaseResult(nodeid, "passed"))
    return results


def agent_test_files(repo: Path, pr: int) -> list[Path]:
    return sorted((repo / AGENT_DIR).glob(f"{test_file_prefix(pr)}*.py"))


def run_pytest(repo: Path, targets: list[str], junit: Path) -> None:
    cmd = [sys.executable, "-m", "pytest", "-m", "e2e", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}",
           "--screenshot", "only-on-failure", "--output", str(junit.parent / "playwright"), *targets]
    subprocess.run(cmd, cwd=repo, check=False)


def verify(repo: Path, pr: int, out: Path) -> Verification:
    files = agent_test_files(repo, pr)
    if not files:
        return Verification()
    first = out / "junit-run1.xml"
    run_pytest(repo, [str(f.relative_to(repo)) for f in files], first)
    results = parse_junit(first)
    failed = [r.nodeid for r in results if r.status == "failed"]
    flaky: list[str] = []
    if failed:
        second = out / "junit-rerun.xml"
        run_pytest(repo, failed, second)
        rerun = {r.nodeid: r for r in parse_junit(second)}
        for r in results:
            if r.status == "failed" and rerun.get(r.nodeid) and rerun[r.nodeid].status == "passed":
                flaky.append(r.nodeid)
    return Verification(results, flaky)


# ---------------------------------------------------------------------------------------------------------------
# The agent

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two or three sentences: what the PR changes and what you tested."},
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Test function name"},
                    "checks": {"type": "string", "description": "One sentence: the behaviour it checks"},
                },
                "required": ["name", "checks"],
                "additionalProperties": False,
            },
        },
        "app_bugs": {
            "type": "array",
            "description": "Failing tests that you are confident show a bug in the app, not in the test.",
            "items": {
                "type": "object",
                "properties": {
                    "test": {"type": "string"},
                    "problem": {"type": "string", "description": "What the app does wrong, in one or two sentences"},
                    "file": {"type": "string", "description": "App file that needs the fix"},
                    "suggested_fix": {"type": "string", "description": "A short unified diff or code snippet"},
                },
                "required": ["test", "problem", "file", "suggested_fix"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "Anything the reviewer should know, or an empty string"},
    },
    "required": ["summary", "tests", "app_bugs", "notes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the testing agent for Market Headlines, a FastAPI financial news site. A pull request changed \
the web app. Your job: write Playwright browser tests (pytest-playwright, Python, sync API) for what this PR changes, \
run them, and decide for every failure whether the test or the app is wrong.

How this repo's browser tests work (read the files before writing anything):
- tests/e2e/conftest.py starts the real app on a local port with every outside HTTP call mocked (news feeds, quotes, \
SEC). Fixtures: `page` (already signed in to Portfolio), `live_server` (the base URL), `anon_page` (signed out). \
tests/conftest.py holds the mocked data helpers.
- Look at one or two existing tests in tests/e2e/ that cover the same page, and copy their style: \
`pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]`, `expect(...)` assertions (never sleeps), and locators by \
`data-testid` or role. Mark tests that check exact mocked values with `pytest.mark.local_only`.
- Page objects live in tests/e2e/pages/.

Rules:
- Write tests only as {agent_dir}/{prefix}<topic>.py. Files there from earlier runs of this PR are yours to update.
- Test the behaviour the PR adds or changes, as a user sees it. Three to six focused tests is usually right. Do not \
re-test what existing tests already cover.
- Run them with: python -m pytest -m e2e {agent_dir}/<file>.py -q
- When a test fails, read the error and the app code. If the test is wrong, fix it (at most two attempts per test). \
If the app is wrong, keep the test exactly as the correct behaviour demands and report it in app_bugs with a \
suggested fix. Never weaken a test to make it pass.
- You cannot change app code, install packages or use the network. Do not try.
- Finish with the structured report."""


def build_prompt(pr: int, title: str, changed: list[str], diff: str) -> str:
    files = "\n".join(f"- {p}" for p in changed)
    if len(diff) <= MAX_INLINE_DIFF_CHARS:
        diff_part = f"The diff:\n\n```diff\n{diff}\n```"
    else:
        diff_part = (f"The diff is {len(diff):,} characters, too long to paste here. Read it file by file with "
                     f"`git diff {{base}}...HEAD -- <file>`.")
    return f"Pull request #{pr}: {title or '(no title)'}\n\nChanged files:\n{files}\n\n{diff_part}"


async def run_agent(repo: Path, pr: int, prompt: str, log) -> dict:
    """Runs the Claude agent and returns its structured report plus cost and turn count."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query

    async def guard(hook_input, tool_use_id, context):
        reason = check_tool(hook_input["tool_name"], hook_input["tool_input"], repo, pr)
        if reason is None:
            return {}
        log(f"refused {hook_input['tool_name']}: {reason}")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}

    options = ClaudeAgentOptions(
        model=MODEL,
        effort="high",
        cwd=str(repo),
        system_prompt=SYSTEM_PROMPT.format(agent_dir=AGENT_DIR, prefix=test_file_prefix(pr)),
        tools=ALLOWED_TOOLS,
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        output_format={"type": "json_schema", "schema": REPORT_SCHEMA},
        stderr=lambda line: log(f"[claude] {line}"),
    )
    report: dict = {}
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            report = dict(message.structured_output or {})
            report["_cost_usd"] = message.total_cost_usd
            report["_turns"] = message.num_turns
            report["_error"] = message.subtype if message.is_error else None
        else:
            for block in getattr(message, "content", None) or []:
                if getattr(block, "name", None):  # a tool call: log it so the Actions log shows what the agent does
                    detail = block.input.get("command") or block.input.get("file_path") or block.input.get("pattern") or ""
                    log(f"{block.name} {detail}")
    return report


# ---------------------------------------------------------------------------------------------------------------
# Deciding what to commit, and writing the PR comment


def matches(nodeid: str, test_name: str) -> bool:
    name = nodeid.split("::")[-1]
    return name == test_name or name.split("[")[0] == test_name or nodeid.endswith(test_name)


def should_commit(v: Verification, report: dict) -> tuple[bool, str]:
    """Commit the tests when they are trustworthy: none flaky, and every failure is a confirmed app bug."""
    if not v.results:
        return False, "the agent wrote no tests"
    if v.flaky:
        return False, "some tests are flaky (failed, then passed on a rerun)"
    bugs = [b["test"] for b in report.get("app_bugs", [])]
    unexplained = [r.nodeid for r in v.by_status("failed") if not any(matches(r.nodeid, b) for b in bugs)]
    if unexplained:
        return False, "some failing tests were not confirmed as app bugs, so they may be wrong"
    return True, ""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_comment(pr: int, report: dict, v: Verification, commit: bool, why_not: str) -> str:
    lines = ["## Testing agent", ""]
    if report.get("_error"):
        lines += [f"The agent stopped early ({report['_error']}). Results below cover what it finished.", ""]
    if report.get("summary"):
        lines += [report["summary"], ""]

    if not v.results:
        lines += ["No tests were written for this PR."]
    else:
        passed, failed, skipped = (len(v.by_status(s)) for s in ("passed", "failed", "skipped"))
        counts = f"**{len(v.results)} tests** in `{AGENT_DIR}/{test_file_prefix(pr)}*.py`: {passed} passed, {failed} failed"
        counts += f", {skipped} skipped" if skipped else ""
        counts += f", {len(v.flaky)} flaky" if v.flaky else ""
        lines += [counts, "", "| Test | What it checks | Result |", "| --- | --- | --- |"]
        checks = {t["name"]: t["checks"] for t in report.get("tests", [])}
        for r in v.results:
            name = r.nodeid.split("::")[-1]
            what = next((c for n, c in checks.items() if matches(r.nodeid, n)), "")
            result = "flaky" if r.nodeid in v.flaky else r.status
            lines.append(f"| `{_cell(name)}` | {_cell(what)} | {result} |")
        lines.append("")

    bugs = report.get("app_bugs") or []
    if bugs:
        lines += ["### Likely bugs in this PR", ""]
        for b in bugs:
            lines += [f"**`{b['test']}`**: {b['problem']}", "", f"Suggested fix in `{b['file']}`:", "",
                      "```diff" if b["suggested_fix"].lstrip().startswith(("---", "@@", "-", "+")) else "```",
                      b["suggested_fix"].strip(), "```", ""]

    other = [r for r in v.by_status("failed") if not any(matches(r.nodeid, b["test"]) for b in bugs)]
    if other:
        lines += ["### Failures not explained", ""]
        lines += [f"- `{r.nodeid.split('::')[-1]}`: {r.message or 'see the test log'}" for r in other] + [""]

    if report.get("notes"):
        lines += [f"**Notes:** {report['notes']}", ""]
    if v.results and not commit:
        lines += [f"Tests were not committed because {why_not}. They are in the workflow artifact.", ""]
    footer = "Model: Claude Opus 5.5"
    if report.get("_cost_usd") is not None:
        footer += f" · {report.get('_turns', 0)} turns · ${report['_cost_usd']:.2f}"
    lines += [f"<sub>{footer} · suggestions only, review before applying</sub>", "", COMMENT_MARKER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def write_outputs(out: Path, comment: str, commit: bool) -> None:
    (out / "comment.md").write_text(comment)
    (out / "outcome.json").write_text(json.dumps({"commit": commit}))
    gh_output = os.getenv("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"commit={'true' if commit else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="branch the PR merges into")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--out", default="test-results/agent")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)

    repo, out = Path(args.repo).resolve(), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "agent.log").open("a")

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_file.write(msg + "\n")

    changed = [p for p in git(repo, "diff", "--name-only", f"{args.base}...HEAD").splitlines() if p]
    if should_skip(changed):
        log("No app files changed: skipping.")
        write_outputs(out, f"## Testing agent\n\nThis PR doesn't change the web app (`app/`), so no new browser tests "
                           f"were needed.\n\n{COMMENT_MARKER}", False)
        return 0
    if not os.getenv("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY is not set: skipping.")
        write_outputs(out, "## Testing agent\n\nThe agent didn't run: add an `ANTHROPIC_API_KEY` repository secret "
                           f"(Settings, Secrets and variables, Actions).\n\n{COMMENT_MARKER}", False)
        return 0

    diff = git(repo, "diff", f"{args.base}...HEAD")
    prompt = build_prompt(args.pr, args.title, changed, diff).replace("{base}", args.base)
    try:
        report = asyncio.run(run_agent(repo, args.pr, prompt, log))
    except Exception as exc:  # report the failure on the PR rather than failing silently
        log(f"agent failed: {exc!r}")
        report = {"_error": type(exc).__name__}
    (out / "report.json").write_text(json.dumps(report, indent=2))

    v = verify(repo, args.pr, out)
    commit, why_not = should_commit(v, report)
    write_outputs(out, render_comment(args.pr, report, v, commit, why_not), commit)
    log(f"{len(v.results)} tests, {len(v.by_status('failed'))} failed, {len(v.flaky)} flaky; commit={commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
