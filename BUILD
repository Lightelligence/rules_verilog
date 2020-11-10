package(default_visibility = ["//visibility:public"])

load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")
load(":doc.bzl", "markdown_to_html")

bzl_library(
    name = "rtl-rules",
    srcs = [
        "rtl.bzl",
        "verilog.bzl",
    ],
)

stardoc(
    name = "rtl-docs",
    input = "rtl.bzl",
    out = "rtl_doc.md",
    deps = [":rtl-rules"],
)

markdown_to_html(
    name = "rtl_doc_html",
    srcs = [":rtl-docs"],
    imgs = [],
    html_file = "rtl_doc.html",
)


exports_files([
    "xrun_compile_args_template.txt",
    "xrun_runtime_args_template.txt",
    "ut_sim_template.sh",
    "rtl_unit_test_sim_template.sh",
    "rtl_svunit_test_template.sh",
    "default_sim_opts.f",
    "lint_parser.py",
    "cmn_logging.py",
])

