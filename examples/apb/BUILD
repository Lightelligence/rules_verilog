load("@//:rtl.bzl", "verilog_rtl_library", "rtl_lint_test", "rtl_pkg", "rtl_unit_test")

verilog_rtl_library(
    name = "apb",
    modules = [
        "apb.sv",
    ]
)

verilog_rtl_library(
    name = "unit_test_top",
    modules = ["unit_test_top.sv"],
    deps = [":apb"],
)

rtl_unit_test(
    name = "test",
    tags = [
        "lic_xcelium",
        "requires_license",
    ],
    deps = [":unit_test_top"],
)
