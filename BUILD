load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@rules_verilog//verilog:defs.bzl", "verilog_tool_encapsulation")

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

verilog_tool_encapsulation(
    name = "verilog_dv_unit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_cdc_test_command",
    build_setting_default = "jg",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_lint_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_unit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_svunit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_wave_viewer_command",
    build_setting_default = "simvision",
)
