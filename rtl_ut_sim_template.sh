#!/usr/bin/bash
# This is a template for the bazel rtl_ut rule
# It is not intended to be run stand-alone
xrun \
    -define TBV \
    -disable_sem2009 \
    +libext+.sv \
    {FLISTS} \
    $@
