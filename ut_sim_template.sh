#!/usr/bin/bash
# This is a template for the bazel rtl_ut rule
# It is not intended to be run stand-alone
xrun \
    -disable_sem2009 \
    -timescale 100fs/100fs \
    -vtimescale 100fs/100fs \
    -define TIMESCALE_STEP_FS=100 \
    -define TIMESCALE_PREC_FS=100 \
    {DEFAULT_SIM_OPTS} \
    {FLISTS} \
    {SIM_ARGS} \
    $@
