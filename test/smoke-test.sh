#!/usr/bin/env bash
# Smoke test for the gpt-jupyter-dns image.
#
# Runs inside a freshly built image and asserts that every CLI tool and
# Python library the notebooks depend on is present and launchable. Exits
# non-zero on the first missing component so CI fails loudly.
#
# Usage (from CI, against a built image tag):
#   docker run --rm --entrypoint bash <image> /workspace/test/smoke-test.sh
# or with the script mounted:
#   docker run --rm -v "$PWD/test:/t" --entrypoint bash <image> /t/smoke-test.sh
set -uo pipefail

fail=0
pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

# A CLI tool passes if it is on $PATH and answers a trivial invocation.
# Some DNS tools return non-zero on --help/--version, so we only require
# that the binary resolves and executes without a "command not found".
check_cli() {
  local name="$1"; shift
  if ! command -v "$name" >/dev/null 2>&1; then
    bad "cli: $name (not on PATH)"
    return
  fi
  if "$@" >/dev/null 2>&1 || [ $? -lt 127 ]; then
    pass "cli: $name"
  else
    bad "cli: $name (present but failed to run)"
  fi
}

echo "== DNS query & debugging tools =="
check_cli dig             dig -v
check_cli kdig            kdig -V
check_cli drill           drill -v
check_cli q               q --help
check_cli dnsviz          dnsviz --help
check_cli stubby          stubby -h
check_cli dot-cert-tester dot-cert-tester --help

echo "== DNS performance tools =="
check_cli flame           flame --help
check_cli dnsperf         dnsperf -h
check_cli dnspyre         dnspyre --help

echo "== DNS server utilities =="
check_cli named-checkconf named-checkconf -h
check_cli named-checkzone named-checkzone

echo "== Misc CLI =="
check_cli jq   jq --version
check_cli tini tini --version
check_cli aws  aws --version
check_cli jupyter jupyter --version

echo "== Python libraries =="
for mod in dns boto3 git matplotlib pandas rich tabulate ipywidgets nbconvert ipynbname jupyterlab; do
  if python -c "import $mod" 2>/dev/null; then
    pass "python: import $mod"
  else
    bad "python: import $mod"
  fi
done

echo "== nbconvert webpdf (headless Chromium) =="
if python -c "import playwright" 2>/dev/null; then
  pass "python: import playwright"
else
  bad "python: import playwright"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "All smoke-test checks passed."
else
  echo "Smoke test FAILED — see FAIL lines above." >&2
fi
exit "$fail"
