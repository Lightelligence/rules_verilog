#!/usr/bin/env bash

# This script attempts to automate as many steps as possible for our migration
# from verilog_tools to rules_verilog
# It should be removed before rules_verilog is published


find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_lib/verilog_rtl_library/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_cdc/verilog_rtl_cdc_test/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_pkg/verilog_rtl_pkg/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_shell_dynamic/verilog_rtl_shell_dynamic/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_shell_static/verilog_rtl_static/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/rtl_unit_test/verilog_rtl_unit_test/g'

find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_test_cfg/verilog_dv_test_cfg/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_lib/verilog_dv_library/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_tb/verilog_dv_tb/g'
find -name BUILD -o -name '*.bzl' | xargs sed -i 's/dv_unit_test/verilog_dv_unit_test/g'

