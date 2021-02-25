load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")

bzl_library(
    name = "defs_rules",
    srcs = [
        "@verilog_tools//verilog:defs.bzl",
        "@verilog_tools//verilog/private:dv.bzl",
        "@verilog_tools//verilog/private:rtl.bzl",
        "@verilog_tools//verilog/private:verilog.bzl",
    ],
)

stardoc(
    name = "defs_docs",
    out = "defs.md",
    input = "@verilog_tools//verilog:defs.bzl",
    deps = [":defs_rules"],
)
