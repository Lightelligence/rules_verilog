#!/usr/bin/env python

# place holder for run script...
# should be directory independant and use variables or current path to figure out where to run
# output should be stored in /simresults/<proj|chip>/username/bench/testname_seed/ ...
# a link to test dir should be added to bench dir for easy navigation of results
#
# List of input RTL files should come from Make flow
################################################################################

# pylint: disable=line-too-long
# pylint: disable=too-many-lines
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
# pylint: disable=invalid-name
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-statements
# pylint: disable=too-many-branches

################################################################################
# stdlib
import argparse
import bisect
from copy import deepcopy
import enum
import fnmatch
import getpass
from hashlib import sha1
import os
import shlex
import signal
import sys
from tempfile import TemporaryFile
import threading
import time
import datetime
import random
import re
import stat
import subprocess

################################################################################
# Bigger libraries (better to place these later for dependency ordering
import jinja2

################################################################################
# Checkout specific libraries
from lib import cmn_logging
from lib.calc_simresults_location import calc_simresults_location

log = None

################################################################################
# Constants

LOGGER_INDENT = 8 # I'd rather create a "plain" message in the logger that doesn't format, but more work than its worth
BENCHES_REL_DIR = "digital/dv/benches"


@enum.unique
class JobStatus(enum.Enum):
    NOT_STARTED = 0
    TO_BE_BYPASSED = 1
    PASSED = 10
    FAILED = 11
    SKIPPED = 12 # Due to upstream dependency failures, this job was not run
    BYPASSED = 13 # Skipped due to a norun directive, allows downstream jobs to execute assuming the outputs of this job have been previously created

    @property
    def completed(self):
        return self.value >= self.__class__.PASSED.value

    @property
    def successful(self):
        return self in [self.PASSED, self.BYPASSED]

    def __str__(self):
        return self.name

    def _error(self, new_state):
        raise ValueError("May not go from {} to {}".format(self, new_state))

    def update(self, new_state):
        """Check for legal transitions.
        This doesn't actually change this instance, an assignment must be done with retval.
        Example:

          self._jobstatus = self._jobstatus.update(new_jobstatus)
        """
        if new_state == self.NOT_STARTED:
            self._error(new_state)
        if self == new_state:
            pass # No actual transition, ignore
        elif self == self.NOT_STARTED:
            pass # Any transition is legal
        elif self == self.TO_BE_BYPASSED:
            if new_state == self.PASSED:
                return self.BYPASSED # In the case of a bypassed job, part of
                # the job may still be run with a
                # placeholder command. Downstream logic
                # may mark this as passed, but keep
                # bypassed for final formatting.
            if new_state != self.FAILED:
                self._error(new_state)
        elif self == self.PASSED:
            if new_state != self.FAILED:
                self._error(new_state)
        elif self == self.FAILED:
            self._error(new_state)
        elif self == self.SKIPPED:
            if new_state != self.FAILED:
                self._error(new_state)
        elif self == self.BYPASSED:
            if new_state != self.FAILED:
                self._error(new_state)
        else:
            raise ValueError("Unknown current state")
        return new_state


SIM_CMD_TEMPLATE = jinja2.Template("""
{% if options.wave_start -%}
run {{ options.wave_start }} ns
{% endif -%}
{% if options.wave_type == 'shm' -%}
database -open -shm shm_db -into {{ waves_db }} -default
{% for probe in options.probes -%}
probe -database shm_db {{ probe }} -all -dynamic -memories -depth all -packed {{ options.probe_packed }} -unpacked {{ options.probe_unpacked }}
{% endfor -%}
run
{% endif -%}
{% if options.wave_type == 'vcd' -%}
database -open -vcd vcd_db -into {{ waves_db }} -default
{% for probe in options.probes -%}
probe -database vcd_db {{ probe }} -all -memories -depth all -vcd -packed {{ options.probe_packed }} -unpacked {{ options.probe_unpacked }}
{% endfor -%}
run
{% endif -%}
{% if options.wave_type == 'fsdb' -%}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDumpfile {{ waves_db }}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbAll on
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbStruct on
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDelta
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbSvastatus
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbFunctions
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbMda on
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbPackedmda on
{% for probe in probes -%}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDumpvars 0 {{ probe }}
{% endfor -%}
run
{% endif -%}
""")

SIM_TEMPLATE = jinja2.Template("""#!/bin/bash
export PROJ_DIR={{ job.vcomper.rcfg.proj_dir }}
source $PROJ_DIR/env/env.sh

ARGS=$@

function testFunction {
    # Variable to accumulate return codes
    declare -i result=0

 {% for socket_name, socket_command, socket_file in sockets %}
    ##################################################
    cd $PROJ_DIR
    # Remove previous socket file if it exists
    rm -f {{ socket_file }}
    # spawn {{ socket_name }} socket
    {{ socket_command }} > {{ job.job_dir}}/{{ socket_name }}.log 2>&1 &
    {{ socket_name|upper }}_PID=$!
    echo "Socket {{ socket_name }} process: ${{ socket_name|upper}}_PID"
    # Wait for socket to actually be created
    while [ ! -e {{ socket_file }} ];
    do
        echo "Waiting for {{ socket_name }} to create {{ socket_file }}"
        sleep 1
        if ! ps -p ${{socket_name|upper }}_PID > /dev/null
        then
           echo "Error {{ socket_name }} returned without creating {{ socket_file }} see {{ job.job_dir }}/{{ socket_name }}.log"
           exit 1
        fi
    done
 {% endfor %}

    ##################################################
    # Main Simulation
    cd {{ job.job_dir }}
    uname -n
    echo -n "# " >> {{ testscript }} ; uname -n >> {{ testscript }}
    ln -snf {{ job.vcomper.bazel_runfiles_main }} bazel_runfiles_main
    cd bazel_runfiles_main
  {% if options.simulator == 'vcs' -%}
    time runmod -t vcs -- {{ vcomp_dir }}/simv {{ gui }} $ARGS {{ sim_opts }} | tee {{ job._logpath }}
  {% endif -%}
  {% if options.simulator == 'xrun' -%} 
    time runmod -t xrun -- -l {{ job.job_dir}}/cmp.log {{ gui }} -R -xmlibdirname {{ job.vcomper.job_dir }} $ARGS {{ sim_opts }} -f external/rules_verilog/vendors/cadence/verilog_dv_default_sim_opts.f | tee {{ job._log_path }}
  {% endif -%}
    SIMULATION_PID=$!
    wait $SIMULATION_PID
    result+=$?
    cd ../
    echo "TEST END"

    ##################################################
    # Socket process exit code collection
    declare -i socket_result=0
 {%- for socket_name, socket_command, socket_file in sockets %}
    wait ${{ socket_name|upper }}_PID
    socket_result=$?
    echo "socket {{socket_name }} result: $socket_result"
    if [ $socket_result -ne 0 ]; then
      echo "%E- ERROR: {{ socket_name }} returned non-zero status"
    fi
    result+=socket_result
 {% endfor %}

 {% if options.skip_parse_sim_log == 0 -%}
    ##################################################
    # Parse simulation log
    cd {{ job.job_dir }}
    $PROJ_DIR/bazel-bin/external/rules_verilog/bin/check_test {{ job._log_path }}
    result+=$?
 {% endif -%}

    return $result
}

function signal_exit {
	echo  "CTRL-C trapped. Waiting for $myPID"
}

trap "echo trap_signal; signal_exit" TERM HUP INT USR1 USR2 1 2 3 15
ps -p $$

# This needs to be last in file or result shell returns will not be test pass/fail
testFunction
#sleep 20

##################
# Run invocations
##################

""")

RERUN_TEMPLATE = jinja2.Template("""#!/bin/bash
shopt -s expand_aliases
export PROJ_DIR={{ job.vcomper.rcfg.proj_dir }}

ARGS=$@

cd $PROJ_DIR
source $PROJ_DIR/env/env.sh

set -e

simmer -t {{ job.vcomper.name }}:{{ job.name }} --seed {{ seed }} {{ cmd_line_sim_opts }} --verb=UVM_MEDIUM --waves --simulator {{ options.simulator }} $ARGS

""")

COMPILE_TEMPLATE = jinja2.Template("""#!/bin/bash

cd {{bazel_runfiles_main}} && \\
  runmod -t {{ options.simulator }} -- \\
    {% if options.simulator == 'xrun' -%}
    -xmlibdirname {{ VCOMP_DIR }} \\
    {% for define in additional_defines -%}
    -define {{ define }} \\
    {% endfor -%}
    {% if options.xprof -%}
    -xprof \\
    {% endif -%}
    {% endif -%}
    {% if options.simulator == 'vcs' -%}
    -full64 +v2k +vpi -notice -licqueue \\
    -V -DVCS -CFLAGS -LDFLAGS -assert svaext \\
    {% if enable_debug_access == 0 -%}
    -debug_access+pp \\
    {% endif -%}
    -partcomp -pcmakeprof -j4 -reportstats \\
    -lca -lrt -simprofile time \\
    -top tb_top -ntb_opts uvm-1.2 \\
    +lint=PCWM-L,TFIPC-L,PCWM \\
    -xlrm floating_pnt_constraint \\
    -xlrm uniq_prior_final \\
    -Mdir={{ VCOMP_DIR }}/csrc \\
    -Mlib={{ VCOMP_DIR }}/csrc \\
    +libext+.sv+.svh+.v+.vams \\
    +systemverilogext+.sv+.svh \\
    -timescale=1ns/1ns \\
    {% for define in additional_defines -%}
    +define+{{ define }} \\
    {% endfor -%}
    -o {{ VCOMP_DIR }}/simv \\
    {% endif -%}
    {% if xprop_cmd is not none -%}
    {{ xprop_cmd }} \\
    {% endif -%}
    {% if enable_debug_access > 0 -%}
    {% if options.simulator == 'xrun' -%}
    -createdebugdb \\
    {% endif -%}
    {% if options.simulator == 'vcs' -%}
    -kdb \\
    -debug_region=cell+lib \\
    -debug_access+all+designer+simctrl \\
    +define+UVM_VERDI_COMPWAVE \\
    {% endif -%}
    {% endif -%}
    {% if enable_debug_access > 1 -%}
    +fsmdebug \\
    -linedebug \\
    -uvmlinedebug \\
    {% endif -%}
    {% if cov_opts is not none -%}
    {{ cov_opts }} \\
    {% endif -%}
    -f {{ bazel_compile_args }} \\
    -l {{ VCOMP_DIR }}/cmp.log \\
""")

BUGGER_TEMPLATE = jinja2.Template("""#!/bin/bash

ARGS=$@

SOURCE="${BASH_SOURCE[0]}"

# Hack for zsh
if [ -z $SOURCE ]
then
  SOURCE=$0
fi

while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  PROJ_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$ENV_DIR/$SOURCE" # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done
PROJ_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

shopt -s expand_aliases
source $PROJ_DIR/env/env.sh
shopt -s expand_aliases

simmer -t {{ job.vcomper.name }}:{{ job.name }} {{ options.reproduce_args | join(' ') }} --seed {{ seed }} $ARGS --simulator {{ options.simulator }}

""")

# For publishing test results to azure pipeline or jenkins
JUNIT_TEMPLATE = jinja2.Template("""<?xml version="1.0" encoding="UTF-8"?>
<testsuites disabled="" errors="" failures="" name="" tests="" time="">
    {% for bench, (icfg_list, unused_test_list) in benches.items() %}
    <testsuite disabled="" errors="" failures="{{failures[bench]}}" hostname="" id=""
               name="{{bench}}" package="" skipped="" time="" timestamp="">
        {%- for icfg in icfg_list %}
          {%- for test in icfg.jobs %}
        <testcase assertions="" classname="" name="{{test.name}}" status="{% if test.jobstatus.successful %}SUCCESS{% else %}FAILURE{% endif %}" time="{{ test.duration_s }}">
            {%- if not test.jobstatus.successful %}
            <error message="{{test.error}}" type=""/>
            {%- endif %}
        </testcase>
        {% endfor -%}
        {% endfor -%}
        <system-out/>
        <system-err/>
    </testsuite>
    {% endfor %}
</testsuites>
""")

################################################################################
# Helpers


class TestAction(argparse.Action):

    class TestArg():

        def __init__(self, btiglob):
            self.btiglob = btiglob
            self.tag = set()
            self.ntag = set()

        def __repr__(self):
            return "TestArg(btiglob='{}', tags={}, ntags={})".format(self.btiglob, self.tag, self.ntag)

    def __call__(self, parser, namespace, values, option_string=None):
        ta = self.__class__.TestArg(values)
        getattr(namespace, self.dest).append(ta)


class TagAction(argparse.Action):

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            last_test = namespace.tests[-1]
        except IndexError:
            return # The return is actually more graceful than the explicit value error
            # It relies upon argparse to catch the missing option and throw a better formatted error
            # raise ValueError("Attempted to use a test tag filter without any tests specified. Did you forget the '-t' flag?")
        l = getattr(last_test, self.dest)
        l.add(values)


class GlobalTagAction(argparse.Action):

    def __call__(self, parser, namespace, values, option_string=None):
        gt = getattr(namespace, self.dest)
        gt.add(values)


class XpropAction(argparse.Action):
    legal_xprop_options = {
        'C': 'C - Compute as ternary (CAT)',
        'F': 'F - Forward only X (FOX)',
        'D': 'D - Disable xprop',
    }

    def __call__(self, parser, args, values, option_string=None):
        if values in ['C', 'F']:
            setattr(args, self.dest, values)
        elif values == 'D':
            setattr(args, self.dest, None)
        else:
            parser.error("Illegal xprop value {}, only the following are allowed:\n  {}".format(
                values, "\n  ".join(["{} : {}".format(ii, jj) for ii, jj in self.legal_xprop_options.items()])))


def parse_args(argv):
    """
    simmer configuration is handled through a series of command
    line arguments and a handful of environment variables

    historically, simmer has been dependant on an environment
    variable PROJ_DIR.  to remove this scrict dependency, simmer
    will now check if env(PROJ_DIR) is defined, and if not,
    will use the current working directory

    simmer defaults to using Xcelium for model compiles and
    simulations.  however, the user and/or project can define
    an environement varible SIM_PLATFORM to effectively change
    the default.  the use of --vcs or --xrun on the command line
    will always take precedence over env(SIM_PLATFORM)

    simmer does require either env(VCS_LICENSES) or env(XRUN_LICENSES)
    to be defined and have a non-zero value.  these indicate how many
    licenses are available for compile and simulation jobs
    """

    PROJ_DIR = os.environ.get('PROJ_DIR', os.getcwd())
    SIM_PLATFORM = os.environ.get('SIM_PLATFORM', 'xrun')
    VCS_LICENSES = os.environ.get('VCS_LICENSES', 0)
    XRUN_LICENSES = os.environ.get('XRUN_LICENSES', 0)

    parser = argparse.ArgumentParser(description="Runs simulations!", formatter_class=argparse.RawTextHelpFormatter)

    gdebug = parser.add_argument_group('Debug arguments')
    gdebug.add_argument('--waves',
                        default=None,
                        nargs='*',
                        help=('Enable waveform capture. Optionally pass a list of HDL '
                              'paths to reduce probe scope. Default is tb_top.'))
    gdebug.add_argument('--wave-type',
                        type=str,
                        default=None,
                        choices=[None, 'shm', 'fsdb', 'vcd'],
                        help='Specify the waveform format')
    gdebug.add_argument('--wave-start',
                        type=int,
                        default=None,
                        help='Specify the sim time in ns to start the waveform collection.')
    gdebug.add_argument('--probe-packed',
                        type=int,
                        default=2048,
                        help='Packed probe depth. Only used with --waves. Default is 2048.')
    gdebug.add_argument('--probe-unpacked',
                        type=int,
                        default=2048,
                        help='Unpacked probe depth. Only used with --waves. Default is 2048.')
    gdebug.add_argument('--gui',
                        default=False,
                        action='store_true',
                        help='run simulation in gui mode for C/DV debug, only applicable with single test')
    gdebug.add_argument('--profile',
                        default=False,
                        action='store_true',
                        help='Dump simulation profiling information to stdout.')
    gdebug.add_argument('--verbosity',
                        type=str,
                        default=None,
                        choices=['UVM_NONE', 'UVM_LOW', 'UVM_MEDIUM', 'UVM_HIGH', 'UVM_FULL', 'UVM_DEBUG'],
                        help='Adds run time opt of +UVM_VERBOSITY.')
    gdebug.add_argument('--uvm-set-verbosity',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_verbosity=<string> on the simulation to '
                              'enable debug message on a per module\nFormat of <comp>,'
                              '<id>,<verbosity>,<phase>'))
    gdebug.add_argument('--uvm-config-db-trace',
                        default=False,
                        action="store_true",
                        help='add +UVM_CONFIG_DB_TRACE to sim command line for uvm_config_db debugging')
    gdebug.add_argument('--uvm-resource-db-trace',
                        default=False,
                        action="store_true",
                        help='add +UVM_RESOURCE_DB_TRACE to sim command line for uvm_resource_db debugging')
    gdebug.add_argument('--uvm-max-quit-count',
                        type=int,
                        default=10,
                        help='Set UVM_MAX_QUIT_COUNT to the specified value')
    gdebug.add_argument('--skip-parse-sim-log',
                        default=False,
                        action='store_true',
                        help='Skip post-parsing the simulation log for errors')
    gdebug.add_argument('--tool-debug',
                        default=False,
                        action='store_true',
                        help='Set the verbosity of this tool to debug level.')
    gdebug.add_argument('--dir-suffix',
                        type=str,
                        default="",
                        help=("Append suffix to end of directory names to prevent stomping on previous "
                              "results when rerunning. This argument is not cumulative."))
    gdebug.add_argument('--use-color', default=False, action="store_true", help="Use colorcodes in stdout output")
    gdebug.add_argument('--quit-count', default=10, type=int, help="Quit spawning jobs after this many failures.")
    gdebug.add_argument("--allow-no-run",
                        default=False,
                        action='store_true',
                        help='Allow running of tests that have the "no_run" tag set')

    gtestc = parser.add_argument_group("Test configuration arguments:")
    gtestc.add_argument('--seed', type=int, default=None, help='Set random seed, only applicable with single test.')
    gtestc.add_argument('--rtl-defines', type=str, default=None, nargs="+", help='Macro defines for RTL compile stage.')
    gtestc.add_argument('--sim-opts',
                        type=str,
                        default=[],
                        nargs="+",
                        help=('Options passed to simulator execution (e.g. --sim-opts "+wdog=1000000" '
                              '"+assert_reinitialization_delay=60000"). Note, these take '
                              'precedence over bazel verilog_dv_test_cfg sim_opts'))
    gtestc.add_argument('--sim-opts-file',
                        type=str,
                        default=None,
                        help='File that contains options to be passed to simv execution')
    gtestc.add_argument('--uvm-set-int',
                        type=str,
                        default=None,
                        nargs="+",
                        help='Sets the +uvm_set_config_int    to the value specified ')
    gtestc.add_argument('--uvm-set-str',
                        type=str,
                        default=None,
                        nargs="+",
                        help='Sets the +uvm_set_config_string to the value specified ')
    gtestc.add_argument('--uvm-set-config-int',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_config_int=<int> to the sim command for '
                              'setting variables in the simulation'))
    gtestc.add_argument('--uvm-set-config-string',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_config_string=<string> to the sim command '
                              'for setting variables in the simulation'))
    gtestc.add_argument('--xprop',
                        type=str,
                        default='F',
                        action=XpropAction,
                        help=('F=FOX (Forward-Only-X) mode. C=CAT(Compute as Ternary) mode. D=Disable. '
                              'CAT outputs behave exactly like hardware. '
                              'FOX is more pessimistic, and propogates X to the output if X is in the control.'))
    gtestc.add_argument('--timeout',
                        default=12.0,
                        type=float,
                        help="Sets the per-job wallclock timeout for simulation in hours.")

    # FIXME not implemented
    # gtestc.add_argument('--tcl',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='pass <tcl input file> to Cadence runtime -input <tcl_input_file>, disables -run option to xrun and ignores +debug option')
    # FIXME not implemented
    # gtestc.add_argument('--input',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='pass <tcl input file> to Cadence runtime -input <tcl_input_file>')
    # FIXME not implemented (also this should be every cfg file?)
    # gtestc.add_argument('--opts-file',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='file for command line options to simmer')

    gregre = parser.add_argument_group("Regression arguments")

    class CovAction(argparse.Action):
        legal_coverage_options = {
            'B': 'Block - For enabling block coverage',
            'E': 'Expr - For enabling expression coverage',
            'F': 'Fsm - For enabling fsm coverage',
            'T': 'Toggle - For enabling toggle coverage',
            'U': 'fUnctional - For enabling functional coverage',
            'A': 'All - For enabling all supported coverage types'
        }

        @classmethod
        def format_options(cls, indent=2):
            return f"\n{' '*indent}".join(["{} : {}".format(ii, jj) for ii, jj in cls.legal_coverage_options.items()])

        def __call__(self, parser, args, values, option_string=None):
            cov_options = values.split(':')
            for cov_option in cov_options:
                if cov_option not in self.legal_coverage_options:
                    parser.error(
                        "Illegal coverage value {}\nRequires a colon separated list of the following values:\n  {}".
                        format(cov_option, self.format_options()))
            setattr(args, self.dest, values)

    gregre.add_argument('--mce', default=False, action='store_true', help='Multicore license enable for xrun.')
    gregre.add_argument('--coverage',
                        action=CovAction,
                        help=f'Enable Code Coverage.\n{CovAction.format_options(indent=0)}')
    gregre.add_argument('--covfile',
                        default="$PROJ_DIR/digital/dv/scripts/default_coverage_opt.ccf",
                        help='Path to Coverage configuration file')
    gregre.add_argument('--junit-dump',
                        type=str,
                        default=None,
                        help=("Dump a junit xml file with test results. "
                              "For use with CI systems like Jenkins or Azure Pipelines."))
    gregre.add_argument('--python-seed',
                        type=str,
                        default=None,
                        help='Set base seed in python for random seed generation.')
    gregre.add_argument('--idle-print-seconds',
                        type=int,
                        default=60 * 20,
                        help=('Print the state of the queues every few minutes if nothing has finished.\n'
                              'Helpful for debugging hanging tests.\n'))
    gregre.add_argument('--no-stdout',
                        default=False,
                        action='store_true',
                        help=('By default, when running a single test, the vcomp and sim stdout will '
                              'print to screen.\nThis option suppresses the stdout (useful when running '
                              ' a long test with high verbosity.\nIf multiple vcomps or tests are '
                              'discovered, this flag is automatically thrown.\n'))
    gregre.add_argument('--parallel-max',
                        type=int,
                        default=0,
                        help=('The maximum number of jobs to launch in parallel.\n'
                              'Default is the number of sim licenses'))
    gregre.add_argument('--parallel-interval',
                        type=int,
                        default=3,
                        help=('The interval between polling jobs when launch in parallel.\n'
                              'This is balance between the polling thread consuming too much '
                              'CPU by frequent polling vs license optimization by not wasting '
                              'time by being stuck in a polling loop.\nExpected that very short '
                              'sims should set this to a low number, longer sims can deal with '
                              'less frequent polling.\n'))
    gregre.add_argument('--nt',
                        default=False,
                        action='store_true',
                        help=('By default simmer will clean up simulation results when the tests '
                              'pass. This flag prevents that cleanup.'))
    gflowc = parser.add_argument_group("Flow control arguments:")
    gflowc.add_argument('--lmstat',
                        default=False,
                        action="store_true",
                        help='run the lmstat -a command before submitting')
    gflowc.add_argument('--no-run',
                        default=False,
                        action="store_true",
                        help='compile testcase but do not submit job for execution')
    gflowc.add_argument('--no-compile',
                        default=False,
                        action="store_true",
                        help='skip compile phase and submit job for execution')
    gflowc.add_argument('--recompile',
                        default=False,
                        action="store_true",
                        help='delete the inca/xcelium compiled directory and various log files to')
    gflowc.add_argument('--discovery-only',
                        default=False,
                        action='store_true',
                        help='Perform test discovery, but do not compile or simulate')

    parser.add_argument(
        '-t',
        dest='tests',
        default=[],
        action=TestAction,
        help=
        ('Test names to run. This option has some smarts depending on tool invocation directory.\n'
         'If you run in a "bench" directory, just specify a single "glob" of tests that you want to run.\n'
         'E.g. in digital/dv/benches/mosaic_tb to run all tests in mosaic_tb:\n'
         '  > simmer -t *\n'
         'If you run at a higher level, or elsewhere in the checkout, you can specify two globs separated by a colon:\n'
         ' bench_glob:test_glob\n'
         'This will glob for bench names, then test names within each bench.\n'
         'E.g. running all tests in all benches:\n'
         ' > simmer -t *:*\n'
         'You can throw this option multiple times to build up specific lists. For example,\n'
         'if we follow naming conventions, you can run all register and interrupt tests:\n'
         ' > simmer -t *:intr* -t *:reg_walk\n'
         'You could also run only specific benches to create different layers:\n'
         ' > simmer -t mosaic_tb:*quick* -t vector_add_tb:*\n'
         'Finally, the number of iterations may also be specified by an optional "@"\n'
         'The following runs each mosaic test 5 times, which only running the vector_add tests once\n'
         ' > simmer -t mosaic_tb:*quick*@5 -t vector_add_tb:*@1\n'))

    parser.add_argument('--tag',
                        type=str,
                        action=TagAction,
                        help='Only include tests that match this tag. Must specify indepently for each test glob')
    parser.add_argument('--ntag',
                        type=str,
                        action=TagAction,
                        help='Exclude tests that match this tag. Must specify indepently for each test glob')

    parser.add_argument('--global-tag',
                        default=set(),
                        action=GlobalTagAction,
                        help='Only include tests that match this tag. Affects all test globs')
    parser.add_argument('--global-ntag',
                        default=set(),
                        action=GlobalTagAction,
                        help='Exclude tests that match this tag. Affects all test globs')
    parser.add_argument('--simulator',
                        type=str,
                        default=None,
                        choices=[None, 'vcs', 'xrun'],
                        help='Declares the platform to use for compile and simulation.')

    options = parser.parse_args(argv)
    # Remove tests from arg parsing for later single test reproduciblity
    skip_list = ['-t', '--tag', '--ntag', '--seed', '--global-tag', '--global-ntag']
    skip_list.append(str(options.seed))
    for test in options.tests:
        skip_list.append(test.btiglob)
        for tag in test.tag:
            skip_list.append(tag)
        for ntag in test.ntag:
            skip_list.append(ntag)
    reproduce_args = [arg for arg in argv if arg not in skip_list]
    setattr(options, 'reproduce_args', reproduce_args)
    SIM_LICENSES = 0
    if options.simulator == 'vcs' or (SIM_PLATFORM.lower() == 'vcs' and options.simulator != 'xrun'):
        options.simulator = 'vcs'
        if options.waves is not None:
            if options.wave_type is None:
                options.wave_type = 'fsdb'
            if options.wave_type == 'shm':
                print('-E- SHM waveform capture format not supported by VCS!')
                sys.exit(99)
        SIM_LICENSES = int(VCS_LICENSES)
    if options.simulator == 'xrun' or (SIM_PLATFORM.lower() == 'xrun' and options.simulator != 'vcs'):
        options.simulator = 'xrun'
        if options.waves is not None:
            if options.wave_type is None:
                options.wave_type = 'shm'
        SIM_LICENSES = XRUN_LICENSES
    if SIM_LICENSES == 0:
        print('-E- parse_args: No licenses available!')
        sys.exit(99)
    if options.parallel_max == 0:
        options.parallel_max = int(SIM_LICENSES)
    else:
        if options.parallel_max > SIM_LICENSES:
            print('-E- parse_args: --parallel-max is greater than available licenses')
            sys.exit(99)
    options.proj_dir = PROJ_DIR
    return options


class DatetimePrinter():

    def __init__(self, log):
        self.ts = datetime.datetime.now()
        self.log = log

    def reset(self):
        self.ts = datetime.datetime.now()

    def stop_and_print(self):
        stop = datetime.datetime.now()
        delta = stop - self.ts
        self.log.debug("Last time check: %d", delta.total_seconds())


class RegressionConfig():

    def __init__(self, options, log):
        self.options = options
        self.log = log

        self.max_bench_name_length = 20
        self.max_test_name_length = 20

        self.suppress_output = False

        self.proj_dir = self.options.proj_dir
        self.regression_dir = calc_simresults_location(self.proj_dir)
        if not os.path.exists(self.regression_dir):
            os.mkdir(self.regression_dir)

        self.invocation_dir = os.getcwd()

        self.test_discovery()

        total_tests = sum([iterations for vcomp in self.all_vcomp.values() for test, iterations in vcomp.items()])
        if total_tests == 0:
            self.log.critical("Test globbing resulted in no tests to run")

        self.tidy = True
        if total_tests == 1:
            self.tidy = False
        if self.options.waves is not None:
            self.tidy = False
        if self.options.nt:
            self.tidy = False
        if self.tidy:
            log.info("tidy=%s passing tests will automatically be cleaned up. Use --nt to prevent automatic cleanup.",
                     self.tidy)

        self.deferred_messages = []

    def table_format(self, b, t, c, indent=' ' * LOGGER_INDENT):
        return "{}{:{}s}  {:{}s}  {:{}s}".format(indent, b, self.max_bench_name_length, t, self.max_test_name_length, c,
                                                 6)

    def table_format_summary_line(self, bench, test, passed, skipped, failed, indent=' ' * LOGGER_INDENT):
        return f"{indent}{bench:{self.max_bench_name_length}s}  {test:{self.max_test_name_length}s}  {passed:{6}s}  {skipped:{6}s}  {failed:{6}s}"

    def format_test_name(self, b, t, i):
        return "{:{}s}  {:{}s}  {:-4d}".format(b, self.max_bench_name_length, t, self.max_test_name_length, i)

    def test_discovery(self):
        """Look for all tests in the checkout and filter down to what was specified on the CLI"""
        self.log.summary("Starting test discovery")
        dtp = DatetimePrinter(self.log)

        cmd = "bazel query \"kind(dv_tb, //{}/...)\"".format(BENCHES_REL_DIR)
        log.debug(" > %s", cmd)

        dtp.reset()
        with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
            p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=True)
            p.wait()
            stdout_fp.seek(0)
            stderr_fp.seek(0)
            stdout = stdout_fp.read()
            stderr = stderr_fp.read()
            if p.returncode:
                log.critical("bazel bench discovery failed: %s", stderr.decode('ascii'))

        dtp.stop_and_print()
        all_vcomp = stdout.decode('ascii').split('\n')
        all_vcomp = dict([(av, {}) for av in all_vcomp if av])

        tests_to_tags = {}
        vcomp_to_query_results = {}

        for vcomp, tests in all_vcomp.items():
            vcomp_path, _ = vcomp.split(':')
            test_wildcard = os.path.join(vcomp_path, "tests", "...")
            if self.options.allow_no_run:
                cmd = 'bazel cquery "attr(abstract, 0, kind(dv_test_cfg, {test_wildcard} intersect allpaths({test_wildcard}, {vcomp})))"'.format(
                    test_wildcard=test_wildcard, vcomp=vcomp)
            else:
                cmd = 'bazel cquery "attr(no_run, 0, attr(abstract, 0, kind(dv_test_cfg, {test_wildcard} intersect allpaths({test_wildcard}, {vcomp}))))"'.format(
                    test_wildcard=test_wildcard, vcomp=vcomp)

            log.debug(" > %s", cmd)

            dtp.reset()

            with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                cmd = shlex.split(cmd)
                p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=False, bufsize=-1)
                p.wait()
                stdout_fp.seek(0)
                stderr_fp.seek(0)
                stdout = stdout_fp.read()
                stderr = stderr_fp.read()
                if p.returncode:
                    log.critical("bazel test discovery failed:\n%s", stderr.decode('ascii'))

            dtp.stop_and_print()
            query_results = stdout.decode('ascii').replace('\n', ' ')
            query_results = re.sub("\([a-z0-9]{7,64}\) *", "", query_results)
            vcomp_to_query_results[vcomp] = query_results

        for vcomp, tests in all_vcomp.items():
            query_results = vcomp_to_query_results[vcomp]
            cmd = "bazel build {} --aspects @rules_verilog//verilog/private:dv.bzl%verilog_dv_test_cfg_info_aspect".format(
                query_results)
            log.debug(" > %s", cmd)

            dtp.reset()
            with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                cmd = shlex.split(cmd)
                p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=False, bufsize=-1)
                p.wait()
                stdout_fp.seek(0)
                stderr_fp.seek(0)
                stdout = stdout_fp.read()
                stderr = stderr_fp.read()
                if p.returncode:
                    log.critical("bazel test discovery failed:\n%s", stderr.decode('ascii'))

            dtp.stop_and_print()
            text = stdout.decode('ascii').split('\n') + stderr.decode('ascii').split('\n')

            ttv = [
                re.search("verilog_dv_test_cfg_info\((?P<test>.*), (?P<vcomp>.*), \[(?P<tags>.*)\]\)", line)
                for line in text
            ]
            ttv = [match for match in ttv if match]

            matching_tests = [(mt.group('test'), eval("[%s]" % mt.group('tags'))) for mt in ttv
                              if mt.group('vcomp') == vcomp]
            tests_to_tags.update(matching_tests)
            tests.update(dict([(t[0], 0) for t in matching_tests]))

        table_output = []
        table_output.append(self.table_format("bench", "test", "count"))
        table_output.append(self.table_format("-----", "----", "-----"))
        for vcomp, tests in all_vcomp.items():
            bench = vcomp.split(':')[1]
            for i, (test_target, count) in enumerate(tests.items()):
                test = test_target.split(':')[1]
                if i == 0:
                    table_output.append(self.table_format(bench, test, str(count)))
                else:
                    table_output.append(self.table_format('', test, str(count)))

        self.log.debug("Tests available:\n%s", "\n".join(table_output))

        # bti is bench-test-iteration
        for ta in self.options.tests:
            try:
                btglob, iterations = ta.btiglob.split("@")
                try:
                    iterations = int(iterations)
                except ValueError:
                    self.log.critical("iterations (value after after @) was not integer: '%s'", ta.btiglob)
            except ValueError:
                btglob = ta.btiglob
                iterations = 1

            try:
                bglob, tglob = btglob.split(":")
            except ValueError:
                # If inside a testbench directory, it's only necessary to provide a single glob
                pwd = os.getcwd()
                benches_dir = os.path.join(self.proj_dir, BENCHES_REL_DIR)
                if not (benches_dir in pwd and len(benches_dir) < len(pwd)):
                    self.log.critical("Not in a benches/ directory. Must provide bench:test style glob.")
                bglob = pwd[len(benches_dir) + 1:]
                tglob = btglob

            query = "*:{}".format(bglob) # Matching against a bazel label
            vcomp_match = fnmatch.filter(all_vcomp.keys(), query)

            log.debug("Looking for tests matching %s", ta)

            for vcomp in vcomp_match:
                tests = all_vcomp[vcomp]
                query = "*:{}".format(tglob) # Matching against a bazel label
                test_match = fnmatch.filter(tests, query)
                for test in test_match:
                    # Filter tests againsts tags
                    test_tags = set(tests_to_tags[test])
                    if ta.tag and not ((ta.tag & test_tags) == ta.tag):
                        log.debug("  Skipping %s because it did not match --tag=%s", test, ta.tag)
                        continue
                    if ta.ntag and (ta.ntag & test_tags):
                        log.debug("  Skipping %s because it matched --ntags=%s", test, ta.ntag)
                        continue
                    if self.options.global_tag and not (
                        (self.options.global_tag & test_tags) == self.options.global_tag):
                        log.debug("  Skipping %s because it did not match --global-tag=%s", test,
                                  self.options.global_tag)
                        continue
                    if self.options.global_ntag and (self.options.global_ntag & test_tags):
                        log.debug("  Skipping %s because it match --global-ntags=%s", test, self.options.global_ntag)
                        continue
                    log.debug("  %s met tag requirements", test)
                    try:
                        new_max = max(tests[test], iterations)
                    except KeyError:
                        new_max = iterations
                    tests[test] = new_max

        # Now prune down all the tests and benches that aren't active
        for vcomp, tests in all_vcomp.items():
            all_vcomp[vcomp] = dict([(t, i) for t, i in tests.items() if i])
        all_vcomp = dict([(vcomp, tests) for vcomp, tests in all_vcomp.items() if len(tests)])

        table_output = []
        table_output.append(self.table_format("bench", "test", "count"))
        table_output.append(self.table_format("-----", "----", "-----"))
        vcomps = list(all_vcomp.keys())
        vcomps.sort()
        for vcomp in vcomps:
            bench = vcomp.split(':')[1]
            tests = all_vcomp[vcomp]
            test_targets = list(tests.keys())
            test_targets.sort()
            for i, test_target in enumerate(test_targets):
                test = test_target.split(':')[1]
                count = tests[test_target]
                if i == 0:
                    table_output.append(self.table_format(bench, test, str(count)))
                else:
                    table_output.append(self.table_format('', test, str(count)))

        self.log.info("Tests to run:\n%s", "\n".join(table_output))

        self.all_vcomp = all_vcomp

        if self.options.discovery_only:
            self.log.info("Ran with --discovery-only option. Exiting.")
            sys.exit(0)


class Job():

    _priority_cache = {}

    def __init__(self, rcfg, name):
        self.rcfg = rcfg # Regression cfg object
        self.name = name

        # String set by derived class of the directory to run this job in
        self.job_dir = None

        self.job_runner = None

        self.job_start_time = None
        self.job_stop_time = None

        self._jobstatus = JobStatus.NOT_STARTED

        self.suppress_output = False
        # FIXME need to implement a way to actually override this
        # FIXME add multiplier for --gui
        #self.timeout = 12.25 # Float hours
        self.timeout = options.timeout

        self.priority = -3600 # Not sure that making this super negative is necessary if we log more stuff
        self._get_priority()
        log.debug("%s priority=%d", self, self.priority)

        # Implement both directions to make traversal of graph easier
        self._dependencies = [] # Things this job is dependent on
        self._children = [] # Jobs that depend on this jop

    def __lt__(self, other):
        return self.priority < other.priority

    def _get_priority(self):
        """This function is intended to assign a priority to this Job based on statistics of previous runs of this Job.

        However, integration with the external simulation statistics aggregator didn't work well so support was removed.
        """
        return # Default zero priority

    @property
    def jobstatus(self):
        return self._jobstatus

    @jobstatus.setter
    def jobstatus(self, new_jobstatus):
        self._jobstatus = self._jobstatus.update(new_jobstatus)

    def add_dependency(self, dep):
        if not dep:
            log.error("%s added null dep", self)
        else:
            self._dependencies.append(dep)
        dep._children.append(self)
        dep.increase_priority(self.priority)

    def increase_priority(self, value):
        # Recurse up with new value
        self.priority += value
        for dep in self._dependencies:
            dep.increase_priority(value)

    def pre_run(self):
        log.info("Starting %s %s", self.__class__.__name__, self.name)
        self.job_start_time = datetime.datetime.now()

        if not os.path.exists(self.job_dir):
            self.rcfg.log.debug("Creating job_dir: %s", self.job_dir)
            os.mkdir(self.job_dir)

    def post_run(self):
        self.job_stop_time = datetime.datetime.now()
        log.debug("post_run %s %s duration %s", self.__class__.__name__, self.name, self.duration_s)
        self.completed = True

    @property
    def duration_s(self):
        try:
            delta = self.job_stop_time - self.job_start_time
        except TypeError:
            return 0
        return delta.total_seconds()


class BazelShutdownJob(Job):
    """When all vcomps are done, shutdown bazel server to limit memory consumption.

    Once sockets were added, where 'bazel run' may be invoked, there is concern that this may cause
    intermittent failures due to race conditions. Leaving this class and instantiation for posterity,
    but changing the execution to not actually do a shutdown.
    """

    def __init__(self, rcfg):
        super(BazelShutdownJob, self).__init__(rcfg, "bazel shutdown")

        self.job_dir = rcfg.proj_dir
        # self.main_cmdline = "bazel shutdown"
        self.main_cmdline = "echo \"Skipping bazel shutdown\""

        self.suppress_output = True
        if self.rcfg.options.tool_debug:
            self.suppress_output = False

    def post_run(self):
        super(BazelShutdownJob, self).post_run()
        if self.job_runner.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def __repr__(self):
        return 'Bazel Shutdown'


class VCompJob(Job):
    # All found vcomp names to prevent collisions
    all_names = {}

    def __init__(self, rcfg, bazel_vcomp_target):
        self.bazel_vcomp_target = bazel_vcomp_target
        name = os.path.basename(self.bazel_vcomp_target.split(":")[1])
        if name in self.__class__.all_names:
            log.critical("Found duplicate dv_tb name in %s and %s", self.bazel_vcomp_target,
                         self.__class__.all_names[name].bazel_vcomp_target)
        else:
            self.__class__.all_names[name] = self

        super(VCompJob, self).__init__(rcfg, name)

        self.bench_dir = os.path.join(self.rcfg.proj_dir, self.bazel_vcomp_target.split(':')[0][2:])

        job_dir = "{}__VCOMP{}".format(self.name, self.rcfg.options.dir_suffix)
        self.job_dir = os.path.join(self.rcfg.regression_dir, job_dir)
        self.log_path = os.path.join(self.job_dir, "cmp.log")

        self.main_cmdline = None

    def pre_run(self):
        super(VCompJob, self).pre_run()

        enable_debug_access = 0
        if options.waves is not None:
            enable_debug_access = 1
        if options.gui:
            enable_debug_access = 2

        cov_opts = None
        if options.coverage:
            self.cov_work_dir = os.path.join(self.rcfg.regression_dir, self.name + "__COV_WORK")
            os.system("mkdir -p {}".format(self.cov_work_dir))
            merge_exec_tcl = os.path.join(self.cov_work_dir, "merge_exec.tcl")
            merged_output = os.path.join(self.cov_work_dir, "merged_db")
            with open(merge_exec_tcl, 'w') as filep:
                filep.write("merge -initial_model union_all -out {} -overwrite {}".format(
                    merged_output, os.path.join(self.cov_work_dir, "scope", "*")))
            merge_sh = os.path.join(self.cov_work_dir, "merge.sh")
            with open(merge_sh, 'w') as filep:
                filep.write("".join([
                    "#!/usr/bin/env bash\n", "runmod xrun -- imc -exec {} -verbose\n".format(merge_exec_tcl),
                    "runmod xrun -- imc -load {}\n".format(merged_output)
                ]))
            st = os.stat(merge_sh)
            os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
            cov_opts += ' -coverage {} '.format(options.coverage)

            cmd = "bazel build {} --aspects @rules_verilog//verilog/private:dv.bzl%verilog_dv_tb_ccf_aspect".format(
                self.bazel_vcomp_target)
            log.debug(" > %s", cmd)

            with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=True)
                p.wait()
                stdout_fp.seek(0)
                stderr_fp.seek(0)
                stdout = stdout_fp.read()
                stderr = stderr_fp.read()
                if p.returncode:
                    log.critical("bazel coverage ccf mapping failed:\n%s", stderr.decode('ascii'))

                text = stderr.decode('ascii')
                try:
                    covfiles = eval(re.search("verilog_dv_tb_ccf\((.*)\)", text).group(1))
                    cov_opts += " ".join([' -covfile {} '.format(ccf) for ccf in covfiles])
                except (AttributeError):
                    pass # No ccf file declared (bazel query results empty)

            self.rcfg.deferred_messages.append("Launch coverage with {}".format(merge_sh))

        additional_defines = []
        additional_vcs_defines = [
            'TBV',
            'VCS',
            'UVM_REGEX_NO_DPI',
            'UVM_NO_DEPRECATED',
            'UVM_OBJECT_MUST_HAVE_CONSTRUCTOR',
            'TIMESCALE_STEP_FS=100',
            'TIMESCALE_PREC_FS=100',
        ]
        if options.simulator == 'vcs':
            additional_defines.extend(additional_vcs_defines)
        if options.rtl_defines is not None:
            additional_defines.extend(options.rtl_defines)

        log.debug("workdir = %s", self.job_dir)

        if options.lmstat:
            os.system("lmstat -a > lmstat.out")
        else:
            log.debug("Skipping lmstat -a")

        os.system("env > {}".format(os.path.join(self.job_dir, 'env.out')))
        os.system("hostname > {}".format(os.path.join(self.job_dir, 'hostname.out')))

        if options.recompile:
            log.info("Removing vcomp library %s due to --recompile flag", self.job_dir)
            os.system("rm -rf {0}; mkdir -p {0}".format(self.job_dir))

        relpath, bazel_target = self.bazel_vcomp_target.split(':')
        relpath = relpath[2:] # Remove leading //

        # Find bazel-bin
        # FIXME this is repeated elsewhere, make it a lib function
        p = subprocess.Popen("bazel info", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        assert p.returncode == 0
        stdout, stderr = p.communicate()
        bazel_bin = re.search("bazel-bin: (.*)", stdout.decode('ascii')).group(1)

        # This is a gross assumption, but I can't see an easier way to find this in bazel
        self.bazel_runfiles_main = os.path.join(bazel_bin, relpath, "{}.runfiles".format(bazel_target), "__main__")

        self.bazel_compile_args = os.path.join(self.bazel_runfiles_main, relpath,
                                               "{}_compile_args_{}.f".format(bazel_target, options.simulator))
        self.bazel_runtime_args = os.path.join(self.bazel_runfiles_main, relpath,
                                               "{}_runtime_args.f".format(bazel_target))
        self.compile_warning_waivers_path = os.path.join(self.bazel_runfiles_main, relpath,
                                                         "{}_compile_warning_waivers".format(bazel_target))

        xprop_cmd = None
        if options.xprop:
            if options.simulator == 'vcs':
                xprop_file = os.path.join(self.bench_dir, 'vcs_xprop.cfg')
                xprop_cmd = "-xprop={}".format(xprop_file)
            if options.simulator == 'xrun':
                if options.xprop == 'F':
                    xprop_file = 'fox_xprop.txt'
                else:
                    xprop_file = 'cat_xprop.txt'
                xprop_file = os.path.join(self.bench_dir, xprop_file)
                xprop_cmd = '-xfile {} -xverbose'.format(xprop_file)

        vcomp_sh_path = os.path.join(self.job_dir, "vcomp.sh")
        with open(vcomp_sh_path, 'w') as filep:
            filep.write(
                COMPILE_TEMPLATE.render(
                    VCOMP_DIR=self.job_dir,
                    cov_opts=cov_opts,
                    bazel_runfiles_main=self.bazel_runfiles_main,
                    bazel_compile_args=self.bazel_compile_args,
                    enable_debug_access=enable_debug_access,
                    xprop_cmd=xprop_cmd,
                    additional_defines=additional_defines,
                    options=options,
                ))

        log.debug("bazel_runfiles_main: %s", self.bazel_runfiles_main)

        if self.rcfg.options.no_compile:
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile\"".format(self)
        else:
            self.main_cmdline = "bash {}".format(vcomp_sh_path)

        log.debug(" > %s", self.main_cmdline)

    def post_run(self):
        if self.job_runner.returncode == 0:
            log_level = log.info
            self.jobstatus = JobStatus.PASSED
        else:
            log_level = log.error
            self.jobstatus = JobStatus.FAILED

        with open(self.compile_warning_waivers_path, 'r') as compile_warning_waivers_p:
            warning_waivers = compile_warning_waivers_p.read()
            warning_waivers = eval(warning_waivers)

        # Promote warnings to errors
        with open(os.path.join(self.log_path), 'r') as logp:
            text = logp.read()
            warnings = re.findall("\*W.*", text)
            for warning in warnings:
                waived = False
                for ww in warning_waivers:
                    if ww.search(warning):
                        waived = True
                        break
                if not waived:
                    self.jobstatus = JobStatus.FAILED
                    log.error("%s failed due to unwaived warning: %s", self, warning)

        # Don't want to set completed yet
        super(VCompJob, self).post_run()

        log_level("%s vcomp %s in %s", self.name, self.jobstatus, self.job_dir)

    def __repr__(self):
        return 'Vcomp("{}")'.format(self.bazel_vcomp_target)


class BazelTestCfgJob(Job):
    """Bazel build for a testcfg only needs to be run once per test cfg, not per iteration. So split it out into its own job"""

    def __init__(self, rcfg, target, vcomper):
        self.bazel_target = target
        super(BazelTestCfgJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.add_dependency(vcomper)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        self.main_cmdline = "bazel build {}".format(self.bazel_target)

        self.suppress_output = True
        if self.rcfg.options.tool_debug:
            self.suppress_output = False

    def post_run(self):
        super(BazelTestCfgJob, self).post_run()
        if self.job_runner.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def dynamic_args(self):
        """Additional arugmuents to specific to each simulation"""
        path, target = self.bazel_target.split(":")
        path_to_dynamic_args_files = os.path.join(self.rcfg.proj_dir, "bazel-bin", path[2:],
                                                  "{}_dynamic_args.py".format(target))
        with open(path_to_dynamic_args_files, 'r') as filep:
            content = filep.read()
            dynamic_args = eval(content)
        return dynamic_args

    def __repr__(self):
        return 'Bazel("{}")'.format(self.bazel_target)


class BazelTBJob(Job):
    """Runs bazel to build up a tb compile."""

    def __init__(self, rcfg, target, vcomper):
        self.bazel_target = target
        super(BazelTBJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.vcomper.add_dependency(self)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        if self.rcfg.options.no_compile:
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile\"".format(target)
        else:
            self.main_cmdline = "bazel run {}".format(target)

        self.suppress_output = True
        if self.rcfg.options.tool_debug:
            self.suppress_output = False

    def post_run(self):
        super(BazelTBJob, self).post_run()
        if self.job_runner.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def __repr__(self):
        return 'Bazel("{}")'.format(self.bazel_target)


class TestJob(Job):

    LOG_NAME = 'stdout.log'

    class RegexWrap():

        def __init__(self):
            self.match = None

        def search(self, regex, line):
            self.match = re.search(regex, line)
            return self.match

    def __init__(self, rcfg, target, vcomper, icfg, btcj):
        self.target = target
        name = target.split(":")[1]

        self.icfg = icfg
        self.iteration = icfg.spawn_count
        self.icfg.inc(self)
        self.btcj = btcj

        super(TestJob, self).__init__(rcfg, name)
        self.rcfg = rcfg
        self.vcomper = vcomper
        self.sim_opts = None
        if vcomper:
            self.add_dependency(vcomper)
        # Else expected to be added later when vcomper is set
        self._log_path = None

    def clone(self):
        c = TestJob(self.rcfg, self.target, self.vcomper, self.icfg, self.btcj)
        c.sim_opts = deepcopy(self.sim_opts)
        c.suppress_output = self.suppress_output
        return c

    def __repr__(self):
        try:
            return self.rcfg.format_test_name(self.vcomper.name, self.name, self.iteration)
        except AttributeError:
            return self.rcfg.format_test_name("<???>", self.name, self.iteration)

    def _flatten_test_cfg(self, path):
        flattened = []
        with open(path) as filep:
            rw = self.RegexWrap()
            for line in filep.readlines():
                if rw.search("^<INCLUDE>(.*)", line):
                    include = rw.match.group(1).strip()
                    include = os.path.join(os.path.dirname(path), include)
                    flattened.append("# Jumping into {}\n".format(include))
                    flattened.extend(self._flatten_test_cfg(include))
                    flattened.append("# Popping back from {}\n".format(include))
                else:
                    flattened.append(line)
        return flattened

    def pre_run(self):
        log.debug("Preparing test: %s:%s", self.vcomper.name, self.name)

        options = self.rcfg.options

        sim_opts = ""

        seed = options.seed
        if seed is None:
            seed = random.randint(0, 1 << (32 - 1)) # xrun is treating the seed as a signed integer
            # When coverage is generated, it appends the signed version of the seed into the directory name
            # This causes a mismatch between our directory hierarchy and theirs
            # While it doesn't break anything, it is not intuitive to track
            # Thus, only using positive seeds
        sim_opts += " -svseed %d " % seed

        # Using the timestamp as the name uniquifier is causing issues when trying to spawn many jobs at once
        # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
        # simname = "%s__%s__%s" % (self.vcomper.name, self.name, strdate)
        simname = "%s__%s__%d%s" % (self.vcomper.name, self.name, seed, self.rcfg.options.dir_suffix)
        self.job_dir = os.path.join(self.rcfg.regression_dir, simname)
        self._log_path = os.path.join(self.job_dir, self.LOG_NAME)

        super(TestJob, self).pre_run()

        sockets = []
        dynamic_args = self.btcj.dynamic_args()
        for socket_name, socket_command in dynamic_args['sockets'].items():
            # While it would be nice to have the socket live in the job_dir,
            # Unfortunately, the paths are frequently too long resulting in:
            #  OSError: AF_UNIX path too long
            # As such, we'll use that name as the unique value to create hash
            socket_file = os.path.join(self.job_dir, "{}.socket".format(socket_name))
            socket_file = os.path.join("/tmp", sha1(socket_file.encode('ascii')).hexdigest())
            sim_opts += " +SOCKET__{}={}".format(socket_name, socket_file)
            socket_command = socket_command.format(socket_file=socket_file)
            sockets.append((socket_name, socket_command, socket_file))

        if options.coverage:
            sim_opts += ' -covworkdir {} '.format(self.vcomper.cov_work_dir)
            sim_opts += ' -covbaserun {} '.format(self.name)
            if 'A' in options.coverage or 'U' in options.coverage:
                sim_opts += ' +SVFCOV=1 '

        sim_opts += " +UVM_TESTNAME={uvm_testname} ".format(uvm_testname=dynamic_args['uvm_testname'], )
        # extract license tag for resources in LSF

        # The simmer CLI allows sim_opts to not specify a value, e.g "--sim-opts +UVM_CONFIG_DB_TRACE"
        # However, the simmer code that merges CLI sim_opts and verilog_dv_test_cfg sim_opts requires them to have the same formatting
        # Therefore, we need to map the CLI sim_opts to have a value defined for every +arg and use an '=' in formatting
        if options.sim_opts:
            cli_sim_opts = [so.split("=", maxsplit=1) for so in options.sim_opts]
            for cso in cli_sim_opts:
                if len(cso) == 0:
                    raise ValueError("Unexpected split, 0 items")
                elif len(cso) == 1:
                    cso.append("")
                elif len(cso) == 2:
                    cso[0] = cso[0] + "="
                else:
                    raise ValueError("Unexpected split, more than 2 items")
            cli_sim_opts = dict(cli_sim_opts)
        else:
            cli_sim_opts = {}

        bazel_test_cfg_sim_args = dynamic_args['sim_opts']
        # bazel_test_cfg_sim_args is a dictionary, but the key may have equal sign in it to be joined
        bazel_test_cfg_sim_args.update(cli_sim_opts) # Apply the CLI sim_opts on top of the bazel sim_opts
        bazel_test_cfg_sim_args = ["".join(btcsa) for btcsa in bazel_test_cfg_sim_args.items()]
        sim_opts += ' ' + (' '.join(bazel_test_cfg_sim_args)).replace('\"', ' ')

        default_capture = 'tb_top'
        waves_db = self.job_dir
        waves_tcl = os.path.join(self.job_dir, "waves.tcl")
        if options.waves is not None:
            if options.wave_type == 'shm':
                waves_db = os.path.join(waves_db, "waves.shm")
            if options.wave_type == 'vcd':
                default_capture = 'tb_top.dut'
                waves_db = os.path.join(waves_db, "waves.vcd")
            if options.wave_type == 'fsdb':
                waves_db = "waves.fsdb"
                verdi_pli = os.path.join(os.environ['VERDI_HOME'], 'share/PLI/IUS/LINUX64/boot',
                                         'debpli.so:novas_pli_boot')
                sim_opts += " -loadpli1 {} ".format(verdi_pli)
            sim_opts += " -input {} ".format(waves_tcl)
            options.probes = options.waves if options.waves != [] else [default_capture]
            with open(waves_tcl, 'w') as filep:
                tmp = locals()
                del tmp['self']
                tmp['job'] = self
                filep.write(SIM_CMD_TEMPLATE.render(**tmp))
        else:
            nwaves_tcl = os.path.join(self.job_dir, "nwaves.tcl")
            sim_opts += " -input {} ".format(nwaves_tcl)
            with open(nwaves_tcl, 'w') as filep:
                filep.write("run")

        if options.uvm_set_int:
            sim_opts += ' +uvm_set_config_int=' + ' +uvm_set_config_int='.join(options.uvm_set_int)
        if options.uvm_set_str:
            sim_opts += ' +uvm_set_config_string=' + ' +uvm_set_config_string='.join(options.uvm_set_str)
        if options.sim_opts_file:
            fh = open(options.sim_opts_file, 'r')
            for line in fh:
                sim_opts += ' ' + line.strip()

        if options.verbosity:
            if 'UVM_VERBOSITY' not in sim_opts:
                sim_opts += ' +UVM_VERBOSITY=' + options.verbosity
            else:
                sim_opts = re.sub(' \+UVM_VERBOSITY=[A-Z_]+', ' +UVM_VERBOSITY=' + options.verbosity, sim_opts)
        else:
            if 'UVM_VERBOSITY' not in sim_opts:
                sim_opts += ' +UVM_VERBOSITY=UVM_MEDIUM'
        if options.uvm_config_db_trace:
            sim_opts += ' +UVM_CONFIG_DB_TRACE'
        if options.uvm_resource_db_trace:
            sim_opts += ' +UVM_RESOURCE_DB_TRACE'
        if options.uvm_max_quit_count:
            sim_opts += ' +UVM_MAX_QUIT_COUNT={}'.format(options.uvm_max_quit_count)
        if options.uvm_set_verbosity:
            sim_opts += ' +uvm_set_verbosity=' + ' +uvm_set_verbosity='.join(options.uvm_set_verbosity)
        if options.uvm_set_config_int:
            sim_opts += ' +uvm_set_config_int=' + ' +uvm_set_config_int='.join(options.uvm_set_config_int)
        if options.uvm_set_config_string:
            sim_opts += ' +uvm_set_config_string=' + ' +uvm_set_config_string='.join(options.uvm_set_config_string)
        if options.gui:
            sim_opts += " -gui "
            if options.simulator == 'xrun':
                sim_opts += " -R "
        if options.mce:
            sim_opts += " -mce "
            sim_opts += " -mce_nacc_module_with_strength_keywords 0 "

        sim_opts += " -f {} ".format(self.vcomper.bazel_runtime_args)

        self.sim_opts = sim_opts
        log.debug("processJob: submit jobs")

        # try:
        #     self.timeout = found_options['timeout']
        # except KeyError:
        #     pass

        options = self.rcfg.options
        sim_opts = self.sim_opts

        if not os.path.exists(self.job_dir):
            os.mkdir(self.job_dir)

        gui = '' # pylint: disable=possibly-unused-variable
        if options.gui:
            gui = "-gui"

        testscript = os.path.join(self.job_dir, "sim.sh")
        with open(testscript, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            filep.write(SIM_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % testscript)
        log.debug('Created %s', testscript)

        rerun_script = os.path.join(self.job_dir, "rerun.sh")
        with open(rerun_script, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            cmd_line_sim_opts = ""
            if options.sim_opts_file:
                fh = open(options.sim_opts_file, 'r')
                for line in fh:
                    cmd_line_sim_opts += ' ' + line.strip()
            if options.sim_opts:
                cmd_line_sim_opts += ' ' + (' '.join(options.sim_opts)).replace('\"', ' ')
            if cmd_line_sim_opts:
                cmd_line_sim_opts = "--sim-opts \"{}\"".format(cmd_line_sim_opts.lstrip())
            tmp['cmd_line_sim_opts'] = cmd_line_sim_opts
            filep.write(RERUN_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % rerun_script)
        log.debug('Created %s', rerun_script)

        bugger_reproduce_script = os.path.join(self.job_dir, "bugger_reproduce.sh")
        with open(bugger_reproduce_script, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            filep.write(BUGGER_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % bugger_reproduce_script)
        log.debug('Created %s', bugger_reproduce_script)

        # Create a symlink back the vcomp directory for easy reference
        os.system("ln -snf %s %s" % (self.vcomper.job_dir, os.path.join(self.job_dir, '.vcomp')))

        if not self.rcfg.tidy:
            os.system("ln -snf %s .last_sim" % self.job_dir)
            log.debug("created link to sim dir as '.last_sim'")

        self.main_cmdline = '/bin/bash %s' % (testscript)

    def post_run(self):
        super(TestJob, self).post_run()
        # Parse file for duration
        net_time_str, cps_str = self._get_stats_from_log_file()
        total_time_str = self._get_total_time_str()
        time_stats_str = "({} cps / {} net_time / {} total_time)".format(cps_str, net_time_str, total_time_str)
        if self.job_runner.returncode != 0:
            os.system("ln -snf %s .last_fail" % self.job_dir)
            log.debug("created link to sim dir as '.last_fail'")
            log.error(
                "%s %s",
                self.rcfg.table_format(self.vcomper.name,
                                       self.name + ' ' + str(self.iteration),
                                       "FAILED {}".format(time_stats_str),
                                       indent=''), self._log_path)
            self.jobstatus = JobStatus.FAILED
            with open(os.path.join(self.job_dir, "{}.err".format(self.LOG_NAME))) as errors:
                self.error_message = errors.read()
        else:
            if self.rcfg.tidy:
                log_path = ""
            else:
                log_path = self._log_path
            log.info(
                "%s %s",
                self.rcfg.table_format(self.vcomper.name,
                                       self.name + ' ' + str(self.iteration),
                                       "PASSED {} {}".format(time_stats_str,
                                                             datetime.datetime.now().strftime("%H:%M:%S")),
                                       indent=''), log_path)
            self.jobstatus = JobStatus.PASSED
            self.error_message = None
        if options.waves is not None:
            wave_path = self.job_dir
            if options.wave_type == 'shm':
                wave_path = os.path.join(wave_path, 'waves.shm')
            if options.wave_type == 'vcd':
                wave_path = os.path.join(wave_path, 'waves.vcd')
            if options.wave_type == 'fsdb':
                wave_path = os.path.join(wave_path, 'waves.fsdb')
            if os.path.exists(wave_path):
                log.info("Waves available: {}".format(wave_path))
            else:
                log.error("Dumped waves, but waves file doesn't exist.")
        sys.stdout.flush()
        if self.rcfg.tidy and self.jobstatus.successful:
            log.debug("tidy=%s removing %s", self.rcfg.tidy, self.job_dir)
            os.system("rm -rf {}".format(self.job_dir))
            if os.path.exists(".last_sim"):
                os.system("rm .last_sim")

        # If iteration count hasnt been hit yet, add another copy onto the run list
        if self.icfg.spawn_count <= self.icfg.target:
            c = self.clone()
            self.job_runner.manager.add_job(c)

    def _get_total_time_str(self):
        hours = int(self.duration_s // 3600)
        minutes = int((self.duration_s % 3600) // 60)
        seconds = int(self.duration_s % 60)
        return "{:0d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    def _get_stats_from_log_file(self):
        stats_re = re.compile(
            '.*Test Duration: (?P<duration>[0-9]+:[0-9]+:[0-9]+).*Average cycles/sec: (?P<cps>[0-9]+\.[0-9]+).*')
        with open(self._log_path, 'r') as log_file:
            for line in log_file:
                match = stats_re.match(line)
                if match:
                    return match.group('duration'), match.group('cps')
        return '???', '???'

    @property
    def log_path(self):
        if self.jobstatus.completed:
            return self._log_path
        else:
            return "<incomplete>"


class JobRunner():

    def __init__(self, job, manager):
        self.job = job
        self.job.job_runner = self

        self.manager = manager

        self.done = False

    def check_for_done(self):
        raise NotImplementedError

    @property
    def returncode(self):
        raise NotImplementedError

    def print_stderr_if_failed(self):
        raise NotImplementedError


class SubprocessJobRunner(JobRunner):

    def __init__(self, job, manager):
        super(SubprocessJobRunner, self).__init__(job, manager)
        kwargs = {'shell': True, 'preexec_fn': os.setsid}

        if self.job.suppress_output or self.job.rcfg.options.no_stdout:
            self.stdout_fp = open(os.path.join(self.job.job_dir, "stdout.log"), 'w')
            self.stderr_fp = open(os.path.join(self.job.job_dir, "stderr.log"), 'w')
            kwargs['stdout'] = self.stdout_fp
            kwargs['stderr'] = self.stderr_fp
        self._start_time = datetime.datetime.now()
        self._p = subprocess.Popen(self.job.main_cmdline, **kwargs)

    def check_for_done(self):
        if self.done:
            return self.done
        try:
            result = self._check_for_done()
        except Exception as exc:
            log.error("Job failed %s:\n%s", self.job, exc)
            result = True
        if result:
            self.done = result
        return result

    def _check_for_done(self):
        if self._p.poll() is not None:
            if self.job.suppress_output or self.job.rcfg.options.no_stdout:
                self.stdout_fp.close()
                self.stderr_fp.close()
            return True
        delta = datetime.datetime.now() - self._start_time
        if self.job.timeout > 0 and delta > datetime.timedelta(hours=self.job.timeout):
            log.error("%s  exceeded timeout value of %s (job will be killed)", self.job, self.job.timeout)
            os.killpg(os.getpgid(self._p.pid), signal.SIGTERM)
            with open(os.path.join(self.job.job_dir, "stderr.log"), 'a') as filep:
                filep.write("%%E- %s exceeded timeout value of %s (job will be killed)" % (self.job, self.job.timeout))
            with open(os.path.join(self.job.job_dir, "stdout.log"), 'a') as filep:
                filep.write("%%E- %s exceeded timeout value of %s (job will be killed)" % (self.job, self.job.timeout))
            return True
        return False

    @property
    def returncode(self):
        return self._p.returncode

    def kill(self):
        os.killpg(os.getpgid(self._p.pid), signal.SIGTERM)
        # None of the following variants seemed to work (due to shell=True ?)
        # process = psutil.Process(self._p.pid)
        # for proc in process.children(recursive=True):
        #     proc.kill()
        # process.kill()

        # self._p.terminate()

        # self._p.kill()


class JobManager():
    """Manages multiple concurrent jobs"""

    def __init__(self):
        self.max_parallel = options.parallel_max
        self.sleep_interval = options.parallel_interval
        self.idle_print_interval = datetime.timedelta(seconds=options.idle_print_seconds)

        self._quit_count = options.quit_count
        self._error_count = 0
        self._done_grace_exit = False
        self.exited_prematurely = False

        # Jobs must transition from todo->ready->active->done

        # These are jobs ready to be run, but may not dependencies filled yet
        # This list is maintained in sorted priority order
        self._todo = []

        # Jobs ready to launch (all dependencies met)
        # This list is maintained in sorted priority order
        self._ready = []

        # Jobs launched but not yet complete
        self._active = []

        # Completed jobs
        self._done = []

        self._skipped = []

        self._run_jobs_thread = threading.Thread(name="_run_jobs", target=self._run_jobs)
        self._run_jobs_thread.setDaemon(True)
        self._run_jobs_thread_active = True
        self._run_jobs_thread.start()

        self.job_runner_type = SubprocessJobRunner

        self._last_done_or_idle_print = datetime.datetime.now()

    def _print_state(self, log_fn):
        job_queues = ["_todo", "_ready", "_active", "_done", "_skipped"]
        for jq in job_queues:
            log_fn("%s: %s", jq, getattr(self, jq))

    def _run_jobs(self):
        while self._run_jobs_thread_active:
            self._move_todo_to_ready()
            self._move_ready_to_active()
            while len(self._active):
                for i, job in enumerate(self._active):
                    if job.job_runner.check_for_done():
                        log.debug("%s body done", job)
                        try:
                            job.post_run()
                        except Exception as exc:
                            log.error("%s  post_run_failed()\n:%s", job, exc)
                        if not job.jobstatus.successful:
                            self._error_count += 1
                            if self._error_count >= self._quit_count:
                                self._graceful_exit()
                            self._move_children_to_skipped(job)
                        self._active.pop(i)
                        self._last_done_or_idle_print = datetime.datetime.now()
                        self._done.append(job)
                        # Ideally this would be before post_run, but pass_fail status may be set there
                        self._move_todo_to_ready()
                        self._move_ready_to_active()
                time_since_last_done_or_idle_print = datetime.datetime.now() - self._last_done_or_idle_print
                if time_since_last_done_or_idle_print > self.idle_print_interval:
                    self._last_done_or_idle_print = datetime.datetime.now()
                    self._print_state(log.info)

                time.sleep(self.sleep_interval)
            if not len(self._active):
                time.sleep(self.sleep_interval)

    def _move_children_to_skipped(self, job):
        for child in job._children:
            log.info("Skipping job %s due to dependency (%s) failure", child, job)
            try:
                self._todo.remove(child)
                child.jobstatus = JobStatus.SKIPPED
            except ValueError:
                # Initially, this was a nice sanity check, but it doesn't always hold true
                # See azure #924
                # if child not in self._skipped:
                #    raise ValueError("Couldn't find child job to mark as skipped")
                continue
            self._skipped.append(child)
            self._move_children_to_skipped(child)

    def _move_todo_to_ready(self):
        self._print_state(log.debug)
        jobs_that_advanced_state = []
        for i, job in enumerate(self._todo):
            if len(job._dependencies) == 0:
                # There are no dependencies
                bisect.insort_right(self._ready, job)
                jobs_that_advanced_state.append(i)
            else:
                all_dependencies_are_done = all([dep.jobstatus.completed for dep in job._dependencies])
                if not all_dependencies_are_done:
                    continue
                all_dependencies_passed = all([dep.jobstatus.successful for dep in job._dependencies])
                if all_dependencies_passed:
                    bisect.insort_right(self._ready, job)
                    jobs_that_advanced_state.append(i)
                else:
                    log.error("Skipping job %s due dependency failure", job)
                    jobs_that_advanced_state.append(i)
                    self._skipped.append(job)
                    job.jobstatus = JobStatus.SKIPPED

        # Can't iterate and remove in list at the same time easily
        for i in reversed(jobs_that_advanced_state):
            self._todo.pop(i)

    def _move_ready_to_active(self):
        self._print_state(log.debug)

        available_to_run = self.max_parallel - len(self._active)

        jobs_that_advanced_state = []
        for i in range(available_to_run):
            try:
                job = self._ready[i]
            except IndexError:
                # We have more jobs available than todos
                continue # Need to finish loop or final cleanup wont happen
            job.pre_run()
            log.debug("%s priority: %d", job, job.priority)
            self.job_runner_type(job, self)
            jobs_that_advanced_state.append(i)
            self._active.append(job)

        for i in reversed(jobs_that_advanced_state):
            self._ready.pop(i)

    def _graceful_exit(self):
        if self._done_grace_exit:
            return
        self.exited_prematurely = True
        self._done_grace_exit = True
        log.warn("Exceeded quit count. Graceful exit.")
        self._skipped.extend(self._todo)
        self._todo = []
        self._skipped.extend(self._ready)
        self._ready = []

    def add_job(self, job):
        if not isinstance(job, Job):
            raise ValueError("Tried to add a non-Job job {} of type {}".format(job, type(job)))
        if not self._done_grace_exit:
            bisect.insort_right(self._todo, job)
        else:
            self._skipped.append(job)

    def wait(self):
        """Blocks until no jobs are left."""
        log.info("Waiting until all jobs are completed.")
        while len(self._todo) or len(self._ready) or len(self._active):
            log.debug("still waiting")
            time.sleep(10)

    def stop(self):
        """Stop the job runner thread (cpu intenstive). This is really more of a pause than a full stop&exit."""
        self._run_jobs_thread_active = False
        self.exited_prematurely = True

    def kill(self):
        self.stop()
        for job in self._active:
            job.job_runner.kill()


class IterationCfg():

    def __init__(self, target):
        self.target = target # The number or weight of sims to run
        self.spawn_count = 1

        # Used for display at end
        self.jobs = []

    def inc(self, job):
        self.spawn_count += 1
        self.jobs.append(job)

    def __lt__(self, other):
        return self.jobs[0].name < other.jobs[0].name


def print_summary(rcfg, vcomp_jobs, icfgs, jm):
    table_data = [("bench", "test", "passed", "skipped", "failed", "logs")]
    separator = [""] * len(table_data[0])
    table_data.append(separator)

    total_passed = 0
    total_skipped = 0
    total_failed = 0

    last = len(rcfg.all_vcomp) - 1
    for i, (vcomp_name, (icfgs, test_list)) in enumerate(rcfg.all_vcomp.items()):
        vcomp = vcomp_jobs[vcomp_name]
        table_data.append(
            (vcomp.name, "vcomp", '1' if vcomp.jobstatus.successful else '',
             '1' if vcomp.jobstatus == vcomp.jobstatus.SKIPPED else '', '1' if not vcomp.jobstatus.successful else '',
             '' if vcomp.jobstatus.successful else str(vcomp.log_path)))
        if vcomp.jobstatus == vcomp.jobstatus.PASSED:
            total_passed += 1
        elif vcomp.jobstatus == vcomp.jobstatus.FAILED:
            total_failed += 1
        else:
            total_skipped += 1

        if rcfg.options.no_run:
            continue

        icfgs.sort()
        for icfg in icfgs:
            if not icfg.jobs[0].vcomper is vcomp:
                continue
            passed = [j for j in icfg.jobs if j.jobstatus.completed and j.jobstatus.successful]
            failed = [j for j in icfg.jobs if j.jobstatus == j.jobstatus.FAILED]
            skipped = [j for j in icfg.jobs if j.jobstatus not in [j.jobstatus.FAILED, j.jobstatus.PASSED]]

            total_passed += len(passed)
            total_failed += len(failed)
            total_skipped += len(skipped)

            try:
                assert len(passed) + len(failed) + len(skipped) == len(icfg.jobs), print(
                    len(passed), len(failed), len(skipped), len(icfg.jobs))
            except AssertionError as exc:
                if not jm.exited_prematurely:
                    raise exc

            table_data.append(
                ("", icfg.jobs[0].name, str(len(passed)) if passed else "", str(len(skipped)) if skipped else "",
                 str(len(failed)) if failed else "", ""))
            for j in failed:
                table_data.append(("", "", "", "", "", j.log_path if j.log_path else ''))
        if i != last:
            table_data.append(separator)

    # Check that entries are consistent
    assert all(len(i) == len(table_data[0]) for i in table_data)
    columns = list(zip(*table_data))
    column_widths = [max([len(cell) for cell in col]) for col in columns]
    formatter = " " * LOGGER_INDENT + "  ".join(
        ["{{:{}{}s}}".format('>' if i in [2, 3, 4] else '', c) for i, c in enumerate(column_widths)])
    for i, entry in enumerate(table_data):
        if entry == separator:
            table_data[i] = ['-' * cw for cw in column_widths]
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Job Results\n%s", "\n".join(table_data_formatted))

    table_data = [("", "", "passed", "skipped", "failed", "")]
    table_data.append(['-' * len(i) for i in table_data[0]])
    table_data.append(("", "", str(total_passed), str(total_skipped), str(total_failed), ""))
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Simulation Summary\n%s", "\n".join(table_data_formatted))


def main(rcfg):
    """
    Parameters
    ----------
    rcfg : RegressionConfig
         The main configuration knob for the regression
    """
    uname = os.uname()
    rcfg.log.info("Running on %s", uname[1])

    vcomp_jobs = {}
    btcj_jobs = []
    btbj_jobs = []

    bazel_shutdown_job = BazelShutdownJob(rcfg)

    for vcomp, test_list in rcfg.all_vcomp.items():
        vcomper = VCompJob(rcfg, vcomp)
        vcomp_jobs[vcomp] = vcomper

        btbj = BazelTBJob(rcfg, vcomp, vcomper)
        btbj_jobs.append(btbj)

        tests = []
        icfgs = []
        for test, iterations in test_list.items():
            icfg = IterationCfg(iterations)
            icfgs.append(icfg)

            btcj = BazelTestCfgJob(rcfg, test, vcomper)
            btcj_jobs.append(btcj)

            t = TestJob(rcfg, test, vcomper=vcomper, icfg=icfg, btcj=btcj)
            tests.append(t)

            t.add_dependency(btcj)

            for _ in range(1, min(icfg.target, rcfg.options.parallel_max)):
                tclone = t.clone()
                tests.append(tclone)
        rcfg.all_vcomp[vcomp] = (icfgs, tests)

    suppress_via_vcomp_jobs = False
    if len(vcomp_jobs) > 1:
        [setattr(vj, 'suppress_output', True) for vj in vcomp_jobs.values()]
        suppress_via_vcomp_jobs = True
        log.info("Suppressing output due to multiple vcomp begin run")

    total_tests = sum([icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs])
    if total_tests > 1:
        if options.gui:
            rcfg.log.critical("--gui can only be used on one test at a time")
        if options.seed is not None:
            rcfg.log.critical("--seed can only be used if a single test is run")

    try:
        jm = JobManager()

        for job in btbj_jobs:
            if options.no_compile:
                job.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(job)
            bazel_shutdown_job.add_dependency(job)

        for vcomp, vcomper in vcomp_jobs.items():
            if options.no_compile:
                vcomper.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(vcomper)
            bazel_shutdown_job.add_dependency(vcomper)
        jm.add_job(bazel_shutdown_job)

        for btcj in btcj_jobs:
            if options.no_run:
                btcj.jobstatus = JobStatus.TO_BE_BYPASSED
            else:
                jm.add_job(btcj)
                bazel_shutdown_job.add_dependency(btcj)

        if options.python_seed:
            random.seed(options.python_seed)
            log.info("Set python random seed to %s", options.python_seed)

        for vcomp, (icfgs, test_list) in rcfg.all_vcomp.items():
            tests = test_list
            suppress_via_tests = False
            if len(tests) > 1:
                if options.gui:
                    rcfg.log.critical("--gui can only be used on one bench/test at a time")
                if options.seed:
                    rcfg.log.critical("--seed can only be used on one bench/test at a time")
                log.info("Suppressing output due to multiple tests begin run")
                suppress_via_tests = True

            [setattr(t, 'suppress_output', suppress_via_tests or suppress_via_vcomp_jobs) for t in tests]

            for test in tests:
                if options.no_run:
                    test.jobstatus = JobStatus.TO_BE_BYPASSED
                else:
                    jm.add_job(test)

        jm.wait()
        jm.stop()
        if options.no_run:
            rcfg.log.info("run_test:main(): --no_run option selected, exiting")

    except KeyboardInterrupt:
        log.info("Saw keyboard interrupt, attempting to shutdown jobs.")
        jm.kill()
        log.critical("Exiting due to keyboard interrupt")

    print_summary(rcfg, vcomp_jobs, icfgs, jm)

    failures = {}
    for bench, (icfgs, test_list) in rcfg.all_vcomp.items():
        failures[bench] = sum([not j.jobstatus.successful for icfg in icfgs for j in icfg.jobs])

    if options.junit_dump:
        with open(options.junit_dump, 'w') as junit_f:
            junit_f.write(JUNIT_TEMPLATE.render(failures=failures, benches=rcfg.all_vcomp))
            log.info("Wrote junit results to %s", options.junit_dump)

    for message in rcfg.deferred_messages:
        log.info(message)

    rcfg.log.exit_if_warnings_or_errors("Previous errors")


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("sim", level=verbosity, use_color=options.use_color, filehandler="simmer.log")
    rcfg = RegressionConfig(options, log)
    main(rcfg)
