load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")
load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@verilog_tools//verilog:defs.bzl", "tool_encapsulation")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "cmn_logging",
    srcs = ["cmn_logging.py"],
)

py_binary(
    name = "lint_parser_hal",
    srcs = ["lint_parser_hal.py"],
    deps = [":cmn_logging"],
)

exports_files([
    "default_sim_opts.f",
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

tool_encapsulation(
    name = "verilog_dv_unit_test_command",
    build_setting_default = "xrun",
)

tool_encapsulation(
    name = "verilog_rtl_cdc_test_command",
    build_setting_default = "jg",
)

tool_encapsulation(
    name = "verilog_rtl_lint_test_command",
    build_setting_default = "xrun",
)

tool_encapsulation(
    name = "verilog_rtl_unit_test_command",
    build_setting_default = "xrun",
)
