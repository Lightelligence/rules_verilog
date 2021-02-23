load(
    "@verilog_tools//verilog/private:verilog.bzl",
    _tool_encapsulation = "tool_encapsulation",
    _verilog_test = "verilog_test",
)

load(
    "@verilog_tools//verilog/private:rtl.bzl",
    _verilog_rtl_library = "verilog_rtl_library",
    _verilog_rtl_unit_test = "verilog_rtl_unit_test",
    _verilog_rtl_lint_test = "verilog_rtl_lint_test",
    _verilog_rtl_cdc_test = "verilog_rtl_cdc_test",
)

load(
    "@verilog_tools//verilog/private:dv.bzl",
    _verilog_dv_library = "verilog_dv_library",
    _verilog_dv_unit_test = "verilog_dv_unit_test",
    _verilog_dv_tb = "verilog_dv_tb",
    _verilog_dv_test_cfg = "verilog_dv_test_cfg",
)

tool_encapsulation = _tool_encapsulation
verilog_test = _verilog_test

verilog_rtl_library = _verilog_rtl_library
verilog_rtl_unit_test = _verilog_rtl_unit_test
verilog_rtl_lint_test = _verilog_rtl_lint_test
verilog_rtl_cdc_test = _verilog_rtl_cdc_test

verilog_dv_library = _verilog_dv_library
verilog_dv_unit_test = _verilog_dv_unit_test
verilog_dv_tb = _verilog_dv_tb
verilog_dv_test_cfg = _verilog_dv_test_cfg
