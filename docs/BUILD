load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")

bzl_library(
    name = "defs_rules",
    srcs = [
        "@rules_verilog//verilog:defs.bzl",
        "@rules_verilog//verilog/private:dv.bzl",
        "@rules_verilog//verilog/private:rtl.bzl",
        "@rules_verilog//verilog/private:verilog.bzl",
    ],
)

stardoc(
    name = "defs_docs",
    out = "defs.md",
    input = "@rules_verilog//verilog:defs.bzl",
    deps = [":defs_rules"],
)
