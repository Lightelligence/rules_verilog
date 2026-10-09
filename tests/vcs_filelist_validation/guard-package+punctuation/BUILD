load("@rules_verilog//verilog:defs.bzl", "verilog_rtl_library")

verilog_rtl_library(
    name = "guard-target+punctuation",
    modules = ["guard_top.sv"],
    visibility = ["//visibility:public"],
)

verilog_rtl_library(
    name = "guard-target",
    modules = ["guard_hyphen_top.sv"],
    visibility = ["//visibility:public"],
)

verilog_rtl_library(
    name = "guard_target",
    modules = ["guard_underscore_top.sv"],
    visibility = ["//visibility:public"],
)

verilog_rtl_library(
    name = "guard_45_target",
    modules = ["guard_escape_top.sv"],
    visibility = ["//visibility:public"],
)
