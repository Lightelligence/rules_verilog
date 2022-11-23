#!/usr/bin/env python

################################################################################
# standard lib imports
import argparse
from copy import deepcopy
import datetime
from hashlib import sha1
import os
import sys
from tempfile import TemporaryFile
import random
import re
import stat
import subprocess

################################################################################
# Bigger libraries (better to place these later for dependency ordering
import jinja2

################################################################################
# rules_verilog lib imports
from lib.job_lib import Job, JobStatus
from lib import cmn_logging
from lib import job_lib
from lib import parser_actions
from lib import regression
from lib import rv_utils

log = None

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
{% for probe in options.probes -%}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDumpvars 0 {{ probe }}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDumpMDA 0 {{ probe }}
{% if options.simulator == 'xrun' -%}call {% endif -%}fsdbDumpSVA 0 {{ probe }}
{% endfor -%}
run
{% endif -%}
""")

SIM_TEMPLATE = jinja2.Template("""#!/bin/bash
export PROJ_DIR={{ job.vcomper.rcfg.proj_dir }}

ARGS=$@

function testFunction {
    # Variable to accumulate return codes
    declare -i result=0

 {% for socket_name, socket_command, socket_file in sockets %}
    ##################################################
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

ARGS=$@

set -e

simmer -t {{ job.vcomper.name }}:{{ job.name }} --seed {{ seed }} {{ cmd_line_sim_opts }} --verbosity=UVM_MEDIUM --waves --simulator {{ options.simulator }} $ARGS

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
    +vpiSyncPerf \\
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
    COVFILE = PROJ_DIR + os.environ.get('COVFILE', "coverage.ccf")

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
                        action=parser_actions.XpropAction,
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

    gregre.add_argument('--mce', default=False, action='store_true', help='Multicore license enable for xrun.')
    gregre.add_argument('--coverage',
                        action=parser_actions.CovAction,
                        help=f'Enable Code Coverage.\n{parser_actions.CovAction.format_options(indent=0)}')
    gregre.add_argument('--covfile', default=COVFILE, help='Path to Coverage configuration file')
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
        action=parser_actions.TestAction,
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
                        action=parser_actions.TagAction,
                        help='Only include tests that match this tag. Must specify indepently for each test glob')
    parser.add_argument('--ntag',
                        type=str,
                        action=parser_actions.TagAction,
                        help='Exclude tests that match this tag. Must specify indepently for each test glob')

    parser.add_argument('--global-tag',
                        default=set(),
                        action=parser_actions.GlobalTagAction,
                        help='Only include tests that match this tag. Affects all test globs')
    parser.add_argument('--global-ntag',
                        default=set(),
                        action=parser_actions.GlobalTagAction,
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
        if options.parallel_max > int(SIM_LICENSES):
            print('-E- parse_args: --parallel-max is greater than available licenses')
            sys.exit(99)
    options.proj_dir = PROJ_DIR
    return options


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

        cov_opts = ''
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
        if self.job_lib.returncode == 0:
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
                waves_db = os.path.join(waves_db, "waves.fsdb")
                verdi_pli = os.path.join(os.environ['VERDI_HOME'], 'share/PLI/IUS/LINUX64/boot',
                                         'debpli.so:novas_pli_boot')
                sim_opts += " -loadpli1 {} ".format(verdi_pli)
                sim_opts += " +UVM_VERDI_TRACE=UVM_AWARE+HIER+RAL+TLM+COMPWAVE "
                sim_opts += " +fsdb+delta +fsdb+force +fsdb+functions +fsdb+struct=on "
                sim_opts += " +fsdb+parameter=on +fsdb+sva_status +fsdb+sva_success "
                sim_opts += " +fsdb+autoflush "
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
                if options.verbosity == 'UVM_DEBUG':
                    sim_opts += " +UVM_TR_RECORD +UVM_LOG_RECORD "
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
        if self.job_lib.returncode != 0:
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
            self.job_lib.manager.add_job(c)

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

    bazel_shutdown_job = job_lib.BazelShutdownJob(rcfg)

    for vcomp, test_list in rcfg.all_vcomp.items():
        vcomper = VCompJob(rcfg, vcomp)
        vcomp_jobs[vcomp] = vcomper

        btbj = job_lib.BazelTBJob(rcfg, vcomp, vcomper)
        btbj_jobs.append(btbj)

        tests = []
        icfgs = []
        for test, iterations in test_list.items():
            icfg = rv_utils.IterationCfg(iterations)
            icfgs.append(icfg)

            btcj = job_lib.BazelTestCfgJob(rcfg, test, vcomper)
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
        jm_opts = {
            'parallel_max': options.parallel_max,
            'parallel_interval': options.parallel_interval,
            'idle_print_seconds': options.idle_print_seconds,
            'quit_count': options.quit_count
        }
        jm = job_lib.JobManager(jm_opts, log)

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

    rv_utils.print_summary(rcfg, vcomp_jobs, icfgs, jm)

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
    rcfg = regression.RegressionConfig(options, log)
    main(rcfg)
