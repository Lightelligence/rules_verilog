load("@rules_python//python:defs.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "lint_parser_hal",
    srcs = ["lint_parser_hal.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "lint_parser_ascent",
    srcs = ["lint_parser_ascent.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "simmer",
    srcs = ["simmer.py"],
    deps = [
        "//bin:check_test",
        "//lib:calc_simresults_location",
        "//lib:cmn_logging",
    ],
)

py_binary(
    name = "check_test",
    srcs = ["check_test.py"],
    deps = ["//lib:cmn_logging"],
)
