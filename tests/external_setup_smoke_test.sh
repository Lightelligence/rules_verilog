#!/usr/bin/env bash
set -Eeuo pipefail

trap 'status=$?; printf "ERROR: external_setup_smoke_test.sh failed at line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
fixture_dir="$repo_root/tests/external_setup_smoke"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/rules_verilog_external_setup.XXXXXX")"
http_archive_fixture_dir="$temporary_root/http-archive-consumer"

cleanup() {
  rm -rf -- "$temporary_root"
}
trap cleanup EXIT

python_path="$(command -v python3.12)"

run_fixture() {
  local fixture_path=$1
  local output_root=$2
  (
    cd "$fixture_path"
    bazel \
      --output_user_root="$output_root" \
      test \
      --noenable_bzlmod \
      --incompatible_use_python_toolchains=false \
      --python_path="$python_path" \
      --repository_cache="$temporary_root/repository-cache" \
      --experimental_convenience_symlinks=ignore \
      --test_output=errors \
      //:external_setup_smoke_test \
      //:external_verilog_test
  )
}

if [[ "$(bazel --version)" != "bazel 7.7.1" ]]; then
  echo "ERROR: external setup fixture requires Bazel 7.7.1; found $(bazel --version)." >&2
  exit 1
fi

run_fixture "$fixture_dir" "$temporary_root/local-output-user-root"

"$python_path" "$fixture_dir/prepare_http_archive_fixture.py" \
  --repository-root "$repo_root" \
  --fixture-dir "$fixture_dir" \
  --output-root "$temporary_root"

run_fixture "$http_archive_fixture_dir" "$temporary_root/http-archive-output-user-root"

"$python_path" "$repo_root/tests/discovery_cache_smoke_test.py"

# Resolve real repository rules against small fake installations. No simulator
# executable is present: only the exported homes may supply the DPI headers.
headers_fixture="$temporary_root/simulator-headers"
mkdir -p "$headers_fixture" "$temporary_root/vcs-v1/include" "$temporary_root/vcs-v2/include" \
  "$temporary_root/xcelium/tools.lnx86/include" "$temporary_root/empty-home"
for version in v1 v2; do
  for header in svdpi.h svdpi_src.h; do
    printf 'vcs-%s-%s\n' "$version" "$header" >"$temporary_root/vcs-$version/include/$header"
  done
done
for header in svdpi.h svdpi_compatibility.h; do
  printf 'xcelium-%s\n' "$header" >"$temporary_root/xcelium/tools.lnx86/include/$header"
done
cat >"$headers_fixture/WORKSPACE" <<EOF
workspace(name = "simulator_headers_fixture")
local_repository(name = "rules_verilog", path = "$repo_root")
load("@rules_verilog//:simulator.bzl", "vcs_setup", "xcelium_setup")
vcs_setup(name = "vcs")
xcelium_setup(name = "xcelium")
EOF
cat >"$headers_fixture/BUILD" <<'EOF'
genrule(
    name = "headers",
    srcs = ["@vcs//:dpi_headers", "@xcelium//:dpi_headers"],
    outs = ["headers.txt"],
    cmd = "cat $(SRCS) > $@",
)
EOF
(
  cd "$headers_fixture"
  export XCELIUMHOME="$temporary_root/xcelium"
  for version in v1 v2; do
    export VCS_HOME="$temporary_root/vcs-$version"
    bazel --output_user_root="$temporary_root/headers-output" build --noenable_bzlmod //:headers
    grep -F "vcs-$version-svdpi.h" bazel-bin/headers.txt
    grep -F 'xcelium-svdpi_compatibility.h' bazel-bin/headers.txt
  done
  if env -u VCS_HOME bazel --output_user_root="$temporary_root/headers-output" \
      build --noenable_bzlmod @vcs//:dpi_headers >"$temporary_root/missing-home.log" 2>&1; then
    echo "ERROR: DPI setup accepted a missing VCS_HOME." >&2
    exit 1
  fi
  grep -F 'VCS_HOME must be exported' "$temporary_root/missing-home.log"
  if VCS_HOME="$temporary_root/empty-home" bazel --output_user_root="$temporary_root/headers-output" \
      build --noenable_bzlmod @vcs//:dpi_headers >"$temporary_root/missing-header.log" 2>&1; then
    echo "ERROR: DPI setup accepted an installation without headers." >&2
    exit 1
  fi
  grep -F 'does not provide required DPI header' "$temporary_root/missing-header.log"
)
