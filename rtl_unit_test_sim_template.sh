#!/usr/bin/bash
# This is a template for the bazel rtl_ut rule
# It is not intended to be run stand-alone
runmod -t xrun -- \
    -define TBV \
    -libext .sv \
    -libext .svh \
    -libext .v \
    -libext .vams \
    -disable_sem2009 \
    -enable_single_yvlib \
    -timescale 100fs/100fs \
    -vtimescale 100fs/100fs \
    -define TIMESCALE_STEP_FS=100 \
    -define TIMESCALE_PREC_FS=100 \
    {FLISTS} \
    {TOP} \
    $@
