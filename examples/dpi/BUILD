load("//verilog:dv.bzl", "verilog_dv_library", "verilog_dv_unit_test")
load("//verilog:rtl.bzl", "verilog_rtl_library")

cc_library(
    name = "dpi_c",
    hdrs = ["dpi.h"],
    srcs = ["dpi.c"],
)

cc_test(
    name = "dpi_c_test",
    srcs = ["dpi_test.c"],
    deps = [":dpi_c"],
)            

verilog_dv_library(
    name = "pkg",
    srcs = glob(["*.sv"], exclude=["unit_test_top.sv"]),
    in_flist = ["dpi_pkg.sv"],
    dpi = [":dpi_c"],
)
    
verilog_rtl_library(
    name = "unit_test_top",
    direct = ["unit_test_top.sv"],
    deps = [":pkg"],
)

verilog_dv_unit_test(
    name = "test",
    deps = [":unit_test_top"],
    tags = [
        "lic_xcelium",
        "requires_license",
    ],
)
