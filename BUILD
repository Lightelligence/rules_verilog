load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")

package(default_visibility = ["//visibility:public"])

exports_files([
    "xrun_compile_args_template.txt",
    "xrun_runtime_args_template.txt",
    "ut_sim_template.sh",
    "rtl_unit_test_sim_template.sh",
    "rtl_svunit_test_template.sh",
    "default_sim_opts.f",
    "lint_parser.py",
    "cmn_logging.py",
])

buildifier(
    name = "buildifier_format_diff",
    mode = "diff",
)

buildifier(
    name = "buildifier_lint",
    lint_mode = "warn",
    lint_warnings = [
        "-function-docstring-args",
        "-function-docstring",
    ],
    mode = "fix",
)

buildifier(
    name = "buildifier_fix",
    lint_mode = "fix",
    mode = "fix",
)
