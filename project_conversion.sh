#!/usr/bin/env bash

# This script attempts to automate as many steps as possible for our migration
# from verilog_tools to rules_verilog
# It should be removed before rules_verilog is published

find . -name BUILD | xargs sed -i 's/^rtl_cdc(/rtl_cdc_test(/g'
