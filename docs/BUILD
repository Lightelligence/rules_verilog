load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")

bzl_library(
    name = "rtl_rules",
    srcs = [
        "@verilog_tools//verilog/private:rtl.bzl",
        "@verilog_tools//verilog/private:verilog.bzl",
    ],
)

stardoc(
    name = "rtl_docs",
    out = "rtl.md",
    input = "@verilog_tools//verilog/private:rtl.bzl",
    deps = [":rtl_rules"],
)

bzl_library(
    name = "dv_rules",
    srcs = [
        "@verilog_tools//verilog/private:dv.bzl",
        "@verilog_tools//verilog/private:verilog.bzl",
    ],
)

stardoc(
    name = "dv_docs",
    out = "dv.md",
    input = "@verilog_tools//verilog/private:dv.bzl",
    deps = [":dv_rules"],
)

bzl_library(
    name = "verilog_rules",
    srcs = [
        "@verilog_tools//verilog/private:verilog.bzl",
    ],
)

stardoc(
    name = "verilog_docs",
    out = "verilog.md",
    input = "@verilog_tools//verilog/private:verilog.bzl",
)
