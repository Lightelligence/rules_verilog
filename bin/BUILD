load("@rules_python//python:defs.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "simmer",
    srcs = ["simmer.py"],
    deps = [
        "//lib:calc_simresults_location",
        "//lib:cmn_logging",
    ],
)

py_binary(
    name = "check_test",
    srcs = ["check_test.py"],
    deps = [
        "//lib:cmn_logging",
    ],
)
