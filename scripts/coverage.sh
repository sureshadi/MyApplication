#!/usr/bin/env bash
# One combined code coverage report for the unit, API and browser (Playwright) tests.
#
#   ./scripts/coverage.sh          run all the tests with coverage, then combine and report
#   ./scripts/coverage.sh report   only combine the data files already in coverage-data/ and report (used by CI)
#
# Output:
#   terminal       total % and a per-file table with the missing lines
#   coverage-report/html/index.html   browsable report (open it in a browser)
#   coverage-report/coverage.xml      Cobertura XML, for tools that read it
#   coverage-report/summary.md        the same table in Markdown (shown on the GitHub Actions run page)
#
# The browser tests start the app in a thread of the pytest process, so the server code they exercise is
# measured too. Against a deployed site (BASE_URL set) there is no local server to measure, so this script
# refuses to run then.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -n "${BASE_URL:-}" ]]; then
  echo "BASE_URL is set ($BASE_URL): server coverage can only be measured against the local test server. Unset it and try again." >&2
  exit 2
fi

# Use the project's virtualenv when there is one and none is active.
if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

DATA=coverage-data
OUT=coverage-report

if [[ "${1:-}" != "report" ]]; then
  rm -rf "$DATA" "$OUT"
  mkdir -p "$DATA"
  status=0
  echo "== Unit and API tests =="
  COVERAGE_FILE="$DATA/unit-api.cov" pytest -q --cov --cov-report= || status=$?
  echo "== Browser tests (Playwright) =="
  COVERAGE_FILE="$DATA/e2e.cov" pytest -q -m e2e --cov --cov-report= || status=$?
fi

shopt -s nullglob
files=("$DATA"/*.cov)
if (( ${#files[@]} == 0 )); then
  echo "No coverage data in $DATA/" >&2
  exit 1
fi

mkdir -p "$OUT"
export COVERAGE_FILE="$OUT/.coverage"
coverage combine --keep --quiet "${files[@]}"
coverage html --quiet
coverage xml --quiet

total=$(coverage report --format=total)
runs=$(for f in "${files[@]}"; do basename "$f" .cov; done | sed 's/^unit-api$/unit + API/; s/^e2e$/browser/' | paste -sd, - | sed 's/,/, /g')
{
  echo "## Code coverage: ${total}%"
  echo
  echo "Combined from: ${runs} tests. Statements and branches in \`app/\`."
  echo
  coverage report --format=markdown
} > "$OUT/summary.md"

echo
coverage report
echo
echo "Combined coverage (${runs}): ${total}%"
echo "HTML report: $OUT/html/index.html"
exit "${status:-0}"
