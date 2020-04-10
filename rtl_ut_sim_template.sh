#!/usr/bin/bash
# This is a template for the bazel rtl_ut rule
# It is not intended to be run stand-alone
runmod -t xrun -- \
    -libext .sv \
    -libext .svh \
    -libext .v \
    -libext .vams \
    -define TBV \
    -disable_sem2009 \
    -enable_single_yvlib \
    {FLISTS} \
    {TOP} \
    $@
