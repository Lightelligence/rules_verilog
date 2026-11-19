#!/usr/bin/env bash
set -uo pipefail

if [[ $# -ne 0 ]]; then
  echo "Documentation is maintained directly; doc_test.sh accepts no arguments." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3.12 "${repo_root}/tests/docs_test.py"
