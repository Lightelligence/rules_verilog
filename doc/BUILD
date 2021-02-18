load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")


bzl_library(
    name = "rtl_rules",
    srcs = [
        "@verilog_tools//:rtl.bzl",
        "@verilog_tools//:verilog.bzl",
    ],
)

stardoc(
    name = "rtl_docs",
    input = "@verilog_tools//:rtl.bzl",
    out = "rtl.md",
    deps = [":rtl_rules"],
)


bzl_library(
    name = "dv_rules",
    srcs = [
        "@verilog_tools//:dv.bzl",
        "@verilog_tools//:verilog.bzl",
    ],
)

stardoc(
    name = "dv_docs",
    input = "@verilog_tools//:dv.bzl",
    out = "dv.md",
    deps = [":dv_rules"],
)

bzl_library(
    name = "verilog_rules",
    srcs = [
        "@verilog_tools//:verilog.bzl",
    ],
)

stardoc(
    name = "verilog_docs",
    input = "@verilog_tools//:verilog.bzl",
    out = "verilog.md",
)
