#!/usr/bin/env bash

# This script attempts to automate as many steps as possible for our migration
# from verilog_tools to rules_verilog
# It should be removed before rules_verilog is published

# Manual Steps
# 1. Convert all rtl_shell_dynamic into a genrule + verilog_rtl_shell rule.
#    template_path = "$$PROJ_DIR/digital/rtl/shells/template" + shell_suffix
#    native.genrule(
#        name = "_{}".format(name),
#        outs = ["{}.sv".format(name)],
#        srcs = deps,
#        cmd = "cd $(@D); export LC_ALL=en_US.utf-8; export LANG=en_US.utf-8; cookiecutter --no-input {} module_to_shell={} shell_suffix={}".format(template_path, module_to_shell_name, shell_suffix),
#        output_to_bindir = True,
#    )
#
# 2. Update simmer
#    test_to_vcomp_aspect -> verilog_dv_test_cfg_to_vcomp_aspect
#    dv_tb_ccf_aspect -> verilog_dv_tb_ccf_aspect

find -name BUILD -o -name '*.bzl' | xargs sed -i 's/load("@verilog_tools\/\/:rtl.bzl/load("@verilog_tools\/\/verilog:rtl.bzl/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/load("@verilog_tools\/\/:dv.bzl/load("@verilog_tools\/\/verilog:dv.bzl/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/load("@verilog_tools\/\/:verilog.bzl/load("@verilog_tools\/\/verilog:verilog.bzl/g'

find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_lib/verilog_rtl_library/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_cdc/verilog_rtl_cdc_test/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_pkg/verilog_rtl_pkg/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_shell_static/verilog_rtl_shell/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_unit_test/verilog_rtl_unit_test/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_lint_test/verilog_rtl_lint_test/g'

find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_test_cfg/verilog_dv_test_cfg/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_lib/verilog_dv_library/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_tb/verilog_dv_tb/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_unit_test/verilog_dv_unit_test/g'


find -name BUILD -o -name '*.bzl' | xargs sed -i 's/@verilog_tools/@rules_verilog/g'
