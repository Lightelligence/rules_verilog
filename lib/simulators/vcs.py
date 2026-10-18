# lib/simulators/vcs.py
import json
import hashlib
import html
import os
import stat
import logging
import platform
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager

from lib.coverage_data import aggregate_coverage_metrics, parse_coverage_summary
from lib import job_lib, vcs_coverage
from .base import SimulatorInterface, ValidationErrorParser, run_bounded_process
from .options import validate_explicit_switches
from .vcs_options import validate_vcs_runtime_options
from .vso import VsoWorkflow
from .vcs_jobs import IcoInitJob, VsoAskJob, VsoInitJob

log = logging.getLogger(__name__)

PARTCOMP_MANIFEST_FILENAME = ".rules_verilog_partcomp.json"

# Compile-time -debug_access flag for each --vcs-debug-access / vcs_debug_access level.
# "full" keeps UVM HDL deposit/force and DUT memory backdoor access working.
_VCS_DEBUG_ACCESS_FLAGS = {
    "full": "-debug_access+r+w+f",
    "r": "-debug_access+r",
    "none": "",
}
_MAX_BENIGN_MAKE_CLOCK_SKEW_SECONDS = 0.1

# Sentinel for "this cached value has not been resolved yet". None is a real
# result for both partcomp and csrc job counts (meaning "do not pass a flag"),
# so it cannot double as "unresolved".
_UNRESOLVED = object()
_INCR_VLOGAN_IGNORED_ENVIRONMENT = (
    "HOST",
    "HOSTNAME",
    "LSB_AFFINITY_HOSTFILE",
    "LSB_BIND_CPU_LIST",
    "LSB_DJOB_HOSTFILE",
    "LSB_HOSTS",
    "LSB_JOBFILENAME",
    "LSB_JOBID",
    "LSB_JOBINDEX",
    "LSB_MCPU_HOSTS",
    "LSB_QUEUE",
    "LSB_SUB_HOST",
    "LS_SUBCWD",
)
_VCS_COMPILER_VERSION_RE = re.compile(
    r"(?im)\bCompiler[ \t]+version[ \t]*(?:=|:)?[ \t]*(.+?)(?=[ \t]+Runtime[ \t]+version\b|[;\r\n]|$)")


def _stable_vcs_compiler_identity(output):
    match = _VCS_COMPILER_VERSION_RE.search(output or "")
    if match is None:
        return None
    version = " ".join(match.group(1).split())
    return "Compiler version = {}".format(version) if version else None


def _tcl_quote(value):
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    escaped = escaped.replace("[", "\\[").replace("]", "\\]").replace("\n", "\\n").replace("\r", "\\r")
    return '"{}"'.format(escaped)


def detect_allocated_cpus(environment=None):
    return job_lib.detect_allocated_cpus(
        environment,
        hostname=socket.gethostname(),
        affinity_getter=getattr(os, "sched_getaffinity", None),
        host_cpu_count=os.cpu_count(),
    )


class VcsSimulator(SimulatorInterface):
    """Implementation for Synopsys VCS simulator."""

    VCS_XPROP_CONFIG_BY_MODE = {
        'F': ['vcs_fox_xprop.cfg', 'fox_xprop.cfg'],
        'C': ['vcs_cat_xprop.cfg', 'cat_xprop.cfg'],
    }

    VCS_XPROP_FALLBACK_BY_MODE = {
        'F': '-xprop=xmerge',
        'C': '-xprop=tmerge',
    }

    VCS_PARTCOMP_OPTION_BY_MODE = {
        'adaptive': '-partcomp=adaptive_sched',
        'auto': '-partcomp',
        'low': '-partcomp=autopart_low',
        'high': '-partcomp=autopart_high',
        'relax': '-partcomp=autopart_relax',
    }

    def __init__(self, options, rcfg, env):
        super().__init__(options, rcfg, env)
        if self.env is not None:
            self.env.filters['tcl_quote'] = _tcl_quote
        self.vso_workflow = VsoWorkflow(options, rcfg)
        self._vso_init_job = None
        self._vso_ask_job = None
        self._resolved_partcomp_jobs = _UNRESOLVED
        self._resolved_make_jobs = _UNRESOLVED
        self._allocation_and_source = None
        self._vcs_tool_identity = None
        self._vcs_home = None

    def get_name(self):
        return "vcs"

    def get_compile_template(self, vcomp_job):
        if getattr(vcomp_job, "tb_options", {}).get("vcs_three_step", False):
            return self.env.get_template('vcs_three_step_compile_template.sh.j2')
        return self.env.get_template('vcs_compile_template.sh.j2')

    def get_sim_template(self):
        # Assuming a single sim_template works for now, driven by options
        return self.env.get_template('sim_template.sh.j2')

    def get_wave_cmd_template(self):
        return self.env.get_template('vcs_wave_cmd_template.tcl.j2')

    def get_tool_runner(self):
        runner = self.options.vcs_runner or os.environ.get("RV_VCS_RUNNER") or "runmod vcs --"
        return "" if runner.lower() in ("none", "") else runner

    def get_vcs_home(self):
        """Return the VCS installation root, resolved once per simulator instance.

        The environment is authoritative when the regression already runs inside
        the VCS environment; otherwise the runner is asked once per regression
        rather than once per compile step. Returns an empty string when VCS is
        not resolvable so the generated script can fail with its own message.
        """
        if self._vcs_home is not None:
            return self._vcs_home
        environment_home = os.environ.get("VCS_HOME")
        if environment_home:
            self._vcs_home = environment_home
            return self._vcs_home
        runner = self.get_tool_runner()
        command = shlex.split(runner) + ["printenv", "VCS_HOME"] if runner else ["printenv", "VCS_HOME"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            log.warning("Unable to resolve VCS_HOME with '%s'; leaving it empty", shlex.join(command))
            self._vcs_home = ""
            return self._vcs_home
        home = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
        if result.returncode != 0 or not home:
            log.warning("Unable to resolve VCS_HOME with '%s'; leaving it empty", shlex.join(command))
            home = ""
        self._vcs_home = home
        return self._vcs_home

    def get_tool_command(self, tool_name):
        return "{} {}".format(self.get_tool_runner(), tool_name).strip()

    def get_tool_identity(self):
        if self._vcs_tool_identity is not None:
            return self._vcs_tool_identity
        configured_identity = os.environ.get("RV_VCS_TOOL_ID")
        if configured_identity:
            self._vcs_tool_identity = configured_identity
            return self._vcs_tool_identity

        command = shlex.split(self.get_tool_runner()) + ["vcs", "-full64", "-ID"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Unable to resolve the VCS build ID with '{}'. Set RV_VCS_TOOL_ID to the site VCS release ID: {}".
                format(shlex.join(command), exc)) from exc
        diagnostic = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        if result.returncode != 0:
            raise RuntimeError(
                "Unable to resolve the VCS build ID with '{}'. Set RV_VCS_TOOL_ID to the site VCS release ID.\n{}".
                format(shlex.join(command), diagnostic))
        identity = _stable_vcs_compiler_identity(result.stdout)
        if identity is None:
            raise RuntimeError(
                "Unable to find a stable 'Compiler version' in the output from '{}'. Set RV_VCS_TOOL_ID to the "
                "site VCS release ID.\n{}".format(shlex.join(command), diagnostic))
        self._vcs_tool_identity = identity
        log.info("Resolved VCS tool identity: %s", identity)
        return self._vcs_tool_identity

    def validate_resolved_options(self):
        parser = ValidationErrorParser()
        validate_explicit_switches(self.options.xcelium_explicit_switches, "Xcelium", "VCS", parser)
        validate_vcs_runtime_options(self.options, parser)

    def validate_run_options(self, vcomp_count):
        if not self.options.vso:
            return
        if not os.environ.get("VSO_HOME"):
            raise ValueError("VSO_HOME is not set. Source the VSO.ai environment before using --vso.")
        if self.options.vso_buildname and vcomp_count > 1:
            raise ValueError("--vso-buildname can only be used with one selected VCS build.")

    def uses_dynamic_test_plan(self):
        return self.options.vso

    def create_regression_jobs(self, vcomp_jobs):
        if self.options.no_run:
            return []

        jobs = []
        if self.options.ico:
            ico_init_job = IcoInitJob(self.rcfg, self)
            for vcomp_job in vcomp_jobs.values():
                ico_init_job.add_dependency(vcomp_job)
            for _, tests in self.rcfg.all_vcomp.values():
                for test in tests:
                    test.add_dependency(ico_init_job)
            jobs.append(ico_init_job)

        if self.options.vso:
            self._vso_init_job = VsoInitJob(self.rcfg, self, vcomp_jobs)
            for vcomp_job in vcomp_jobs.values():
                self._vso_init_job.add_dependency(vcomp_job)
            self._vso_ask_job = VsoAskJob(self.rcfg, self)
            self._vso_ask_job.add_dependency(self._vso_init_job)
            for _, tests in self.rcfg.all_vcomp.values():
                for test in tests:
                    test.add_dependency(self._vso_ask_job)
            jobs.extend([self._vso_init_job, self._vso_ask_job])
        return jobs

    def finalize_regression_workflow(self):
        if not self.options.vso or self.options.no_run:
            return False
        if not self._vso_init_job.jobstatus.successful or not self._vso_ask_job.jobstatus.successful:
            return False
        try:
            self.vso_workflow.finalize_merge(self.rcfg.all_vcomp)
        except (OSError, RuntimeError) as exc:
            log.error("%s", exc)
            return True
        return False

    def prepare_test_job(self, test_job):
        return self.vso_workflow.prepare_test(test_job) if self.options.vso else None

    def should_spawn_test_job(self, test_job):
        return self.options.vso and test_job.icfg.spawn_count <= test_job.icfg.target

    def coverage_enabled(self):
        return bool(self.options.cm)

    def get_debug_access(self, vcomp_job):
        """Resolve the compile debug-access level: CLI, then bench attribute, then full."""
        level = self.options.vcs_debug_access or getattr(vcomp_job, "tb_options", {}).get("vcs_debug_access") or "full"
        if level not in _VCS_DEBUG_ACCESS_FLAGS:
            raise ValueError("Unsupported vcs_debug_access '{}'; expected one of {}.".format(
                level, ", ".join(sorted(_VCS_DEBUG_ACCESS_FLAGS))))
        if level == "none" and (self.options.gui or self.options.waves is not None):
            raise ValueError("vcs_debug_access 'none' cannot be combined with --waves or --gui because wave dumping "
                             "and the GUI need debug access. Use 'r' or 'full'.")
        return level

    def get_compile_template_context(self, vcomp_job):
        vso_workdir = self.vso_workflow.workdir() if self.options.vso_cbv else ''
        if vso_workdir:
            os.makedirs(vso_workdir, exist_ok=True)
        context = {
            'vcs_runner': self.get_tool_runner(),
            'vcs_debug_access_opt': _VCS_DEBUG_ACCESS_FLAGS[self.get_debug_access(vcomp_job)],
            'vso_build_name': self.vso_workflow.build_name(vcomp_job) if self.options.vso else '',
            'vso_workdir': vso_workdir,
        }
        if getattr(vcomp_job, "vcs_three_step", False):
            context.update({
                'vcs_home':
                self.get_vcs_home(),
                'vcs_analysis_work_dir':
                self.get_analysis_work_dir(vcomp_job),
                'vcs_elab_args':
                vcomp_job.vcs_elab_args,
                'vcs_incr_vlogan_ignore_env':
                shlex.quote("-vts_ignore_env={}".format(",".join(_INCR_VLOGAN_IGNORED_ENVIRONMENT))),
                'vcs_setup_file':
                self.get_analysis_setup_file(vcomp_job),
                'vcs_vlogan_args':
                vcomp_job.vcs_vlogan_args,
                'vcs_vlogan_filelists':
                vcomp_job.vcs_vlogan_filelists,
            })
        return context

    def get_compile_fingerprint_inputs(self, vcomp_job):
        inputs = super().get_compile_fingerprint_inputs(vcomp_job)
        # The rendered VCS command and its resolved tool identity own compiler
        # selection.  Interactive shell setup is not a compile input: PATH and
        # module variables routinely contain editors, user utilities, and
        # module ordering that can change without changing the VCS tool.
        for key in ("LOADEDMODULES", "MODULEPATH", "PATH"):
            inputs["environment"].pop(key, None)
        if self.options.vcs_cm_hier:
            inputs["extra_input_paths"].append(self.options.vcs_cm_hier)
        xprop_config = getattr(vcomp_job, "vcs_xprop_config_path", None)
        if xprop_config:
            inputs["extra_input_paths"].append(xprop_config)
        inputs["environment"].update({key: os.environ.get(key, "") for key in ("VCS_HOME", "VSO_HOME")})
        inputs["environment"]["VCS_TOOL_ID"] = self.get_tool_identity()
        return inputs

    def compile_script_for_fingerprint(self, compile_script):
        # Both job counts are re-derived from the current allocation on every
        # run, so a slot change must not invalidate an otherwise identical
        # script. Only a standalone option token is normalized: a path or a
        # +define+ value that merely ends in -jN is a real compile input.
        normalized = re.sub(r"(?<!\S)-fastpartcomp=j\d+(?=\s|$)", "-fastpartcomp=jAUTO", compile_script)
        return re.sub(r"(?<!\S)-j\d+(?=\s|$)", "-jAUTO", normalized)

    def should_auto_reuse_compile(self):
        return self.options.vcs_auto_compile_cache

    def get_scheduler_threads_per_test(self):
        return self.options.fgp if self.options.fgp is not None else 1

    def use_smartlog(self):
        return self.options.smartlog

    def get_wave_view_command(self, wave_file_path, job_dir=None):
        argv = shlex.split(self.get_tool_runner()) + ["verdi", "-apex", "-ssf", wave_file_path]
        if job_dir is not None and self.use_smartlog():
            smartlog_path = os.path.join(job_dir, "stdout.log")
            if os.path.exists(smartlog_path):
                argv.extend(["-smlog", smartlog_path])
        if any("\n" in arg or "\r" in arg for arg in argv):
            raise ValueError("Wave viewer arguments cannot contain newlines")
        return "\n".join(argv)

    def get_wave_view_script_options(self, wave_file_path, job_dir):
        # stdout.log does not exist when pre_run prepares the viewer. Decide
        # whether to attach SmartLog when the user actually opens the waves.
        options = {
            "wave_view_command": self.get_wave_view_command(wave_file_path),
            "optional_wave_view_args": [],
        }
        if self.use_smartlog():
            smartlog_path = os.path.join(job_dir, "stdout.log")
            options["optional_wave_view_args"].append({
                "path": smartlog_path,
                "args": ["-smlog", smartlog_path],
            })
        return options

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args.f".format(bazel_target))

    def get_vcomp_job_dir(self, default_job_dir):
        # --waves and --gui need their own -kdb options, which invalidate the
        # default csrc database. Give each mode a sibling compile directory so a
        # debug rerun keeps the batch simv, fingerprint, and partition database
        # instead of evicting them. get_debug_mode_dir_suffix() reports which of
        # these directories belongs to the current run.
        suffix = self.get_debug_mode_dir_suffix()
        return default_job_dir + suffix if suffix else default_job_dir

    def get_debug_mode_dir_suffix(self):
        """Return the compile-directory suffix for the active debug mode."""
        if self.options.gui:
            return "_GUI"
        if self.options.waves is not None:
            return "_WAVES"
        return ""

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args.f".format(bazel_target))

    def prepare_compile_job(self, vcomp_job):
        vcomp_job.vcs_three_step = bool(vcomp_job.tb_options.get("vcs_three_step", False))
        if not vcomp_job.vcs_three_step:
            return
        if self.options.compile_args_file:
            raise ValueError(
                "VCS three-step analysis does not accept --file because analysis and elaboration options are "
                "separate. Put source-analysis options in vcs_vlogan_args and elaboration options in vcs_elab_args.")
        for attribute, option_key in (
            ("vcs_vlogan_args", "vcs_vlogan_args"),
            ("vcs_vlogan_filelists", "vcs_vlogan_filelists"),
            ("vcs_elab_args", "vcs_elab_args"),
        ):
            relative_path = vcomp_job.tb_options.get(option_key)
            if not relative_path:
                raise ValueError("VCS three-step testbench metadata is missing '{}'".format(option_key))
            resolved_path = os.path.join(vcomp_job.bazel_runfiles_main, relative_path)
            if not os.path.isfile(resolved_path):
                raise FileNotFoundError("VCS three-step input is missing: {}".format(resolved_path))
            setattr(vcomp_job, attribute, resolved_path)

    def get_analysis_work_dir(self, vcomp_job):
        dirname = "vlogan_work_gui" if self.options.gui else "vlogan_work"
        return os.path.join(vcomp_job.job_dir, dirname)

    def get_analysis_setup_file(self, vcomp_job):
        dirname = "synopsys_sim_gui.setup" if self.options.gui else "synopsys_sim.setup"
        return os.path.join(vcomp_job.job_dir, dirname)

    def _get_ico_artifact_dir(self):
        artifact_dir = os.path.join(self.rcfg.regression_dir, "ico_artifacts")
        os.makedirs(artifact_dir, exist_ok=True)
        return artifact_dir

    def _get_ico_workdir(self):
        if self.options.ico_workdir is not None:
            return os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.ico_workdir))
        return os.path.join(self._get_ico_artifact_dir(), "workdir")

    def _get_ico_shared_record(self):
        if self.options.ico_shared_record is not None:
            return os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.ico_shared_record))
        return os.path.join(self._get_ico_artifact_dir(), "shared_record")

    def build_ico_init_command(self):
        workdir = self._get_ico_workdir()
        dbdir = self._get_ico_shared_record()
        os.makedirs(workdir, exist_ok=True)
        log_path = os.path.join(self._get_ico_artifact_dir(), "ico_init.log")
        if os.path.isfile(os.path.join(dbdir, "readme.txt")):
            return None, log_path
        os.makedirs(os.path.dirname(dbdir), exist_ok=True)
        return shlex.split(self.get_tool_runner()) + ["crg", "-dir", dbdir, "-shared", "init"], log_path

    def prepare_regression_runtime(self, vcomp_jobs):
        runtime_jobs = {}
        for vcomp_job in vcomp_jobs.values():
            # simv and its companion files remain inputs to queued and active
            # simulations after the compile lock is released. Keep ownership
            # until those consumers finish so another run cannot rebuild them.
            paths = [vcomp_job.job_dir]
            if self.options.cm:
                vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK_VCS.vdb")
                paths.append(vcomp_job.cov_work_dir)
            for path in paths:
                runtime_jobs.setdefault(os.path.normcase(os.path.realpath(path)), vcomp_job)
        for runtime_path, vcomp_job in sorted(runtime_jobs.items()):
            vcomp_job.acquire_shared_runtime_lock(runtime_path)

    def generate_compile_options(self, vcomp_job):
        opts = {
            'cov_opts': '',
            'partcomp_opts': self.get_partition_compile_options(vcomp_job),
            'make_jobs_opts': self.get_make_jobs_options(),
            'xprop_cmd': None,
            'additional_defines': [],
        }
        additional_vcs_defines = [] # Add VCS specific defines here if any

        # Coverage (Functional/Code)
        if self.options.cm:
            if getattr(vcomp_job, "cov_work_dir", None) is None:
                vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK_VCS.vdb")
            vcomp_job.acquire_shared_runtime_lock(vcomp_job.cov_work_dir)
            cov_args = ["-cm_dir", vcomp_job.cov_work_dir]
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            cov_args.extend(["-cm", cm_level])
            if self.options.vcs_cm_line is not None:
                cov_args.extend(["-cm_line", self.options.vcs_cm_line])
            for report_mode in self.options.vcs_cm_report or []:
                cov_args.extend(["-cm_report", report_mode])
            if self.options.vcs_cm_cond is not None:
                cov_args.extend(["-cm_cond", self.options.vcs_cm_cond])
            if self.options.vcs_cm_tgl is not None:
                cov_args.extend(["-cm_tgl", self.options.vcs_cm_tgl])
            cm_hier = self.options.vcs_cm_hier or getattr(vcomp_job, "tb_options", {}).get("vcs_cm_hier")
            if cm_hier:
                cov_args.extend(["-cm_hier", cm_hier])
            opts['cov_opts'] = " " + shlex.join(cov_args) + " "
            self.setup_coverage_merge(vcomp_job) # Setup merge script

        # XPROP
        if self.options.xprop_was_explicit and self.options.xprop and not self.options.mce:
            xprop_mode = self.options.xprop
            xprop_cmds = []
            xprop_cfg_path = self._find_vcs_xprop_config(vcomp_job.bench_dir, xprop_mode)
            vcomp_job.vcs_xprop_config_path = xprop_cfg_path
            if xprop_cfg_path is not None:
                xprop_cmds.append("-xprop={}".format(xprop_cfg_path))
            else:
                xprop_fallback = self.VCS_XPROP_FALLBACK_BY_MODE.get(xprop_mode)
                if xprop_fallback is None:
                    log.warning("Unsupported VCS XPROP mode '%s'; XPROP disabled.", xprop_mode)
                else:
                    xprop_cmds.append(xprop_fallback)

            if xprop_cmds:
                if self.options.vcs_xprop_flowctrl:
                    xprop_cmds.append("-xprop=flowctrl")
                if self.options.vcs_xprop_mmsopt:
                    xprop_cmds.append("-xprop=mmsopt")
                opts['xprop_cmd'] = shlex.join(xprop_cmds)

        # Defines
        opts['additional_defines'].extend(additional_vcs_defines)
        if self.options.rtl_defines is not None:
            opts['additional_defines'].extend(self.options.rtl_defines)

        return opts

    def get_partition_compile_options(self, vcomp_job):
        effective_mode = self.get_effective_partcomp_mode()
        if effective_mode == 'disabled':
            # -Mupdate comes from the vendored .f template, and any csrc
            # parallelism is carried separately by get_make_jobs_options().
            log.info("VCS Partition Compile is disabled; using -Mupdate")
            return ''

        if self.options.dtl:
            jobs = '-fastpartcomp=j{}'.format(self.get_partcomp_jobs())
            dtl_dir = os.path.join(vcomp_job.job_dir, self._debug_partition_dirname('dtl_static'))
            return shlex.join([
                '-partcomp',
                '-dir={}'.format(dtl_dir),
                jobs,
            ])

        mode_option = self.VCS_PARTCOMP_OPTION_BY_MODE.get(effective_mode)
        if mode_option is None:
            return ''

        job_count = self.get_partcomp_jobs()
        jobs = '-fastpartcomp=j{}'.format(job_count)
        partition_dir = self.get_partition_compile_dir(vcomp_job)
        args = [
            mode_option,
            '-partcomp_dir={}'.format(os.path.abspath(partition_dir)),
            '-partcomp=incr_clean',
            jobs,
        ]
        if self.options.vcs_partcomp_sharedlib is not None:
            args.append('-partcomp_sharedlib={}'.format(os.path.abspath(self.options.vcs_partcomp_sharedlib)))
        return shlex.join(args)

    def get_effective_partcomp_mode(self):
        if not self.options.vcs_partcomp:
            return 'disabled'
        explicit = self.options.vcs_explicit_switches
        requested = any(switch == '--vcs-partcomp' or switch.startswith('--vcs-partcomp-') for switch in explicit)
        # A site Y-2026.03-1 single-slot compile crashed with automatic partcomp.
        # Keep defaults conservative without probing licensed tools during generation.
        # DTL requires partitions, and explicit tuning remains a diagnostic opt-in.
        if not self.options.dtl and not requested and self.get_partcomp_jobs() == 1:
            return 'disabled'
        return self.options.vcs_partcomp_mode

    def get_partcomp_jobs(self):
        if self._resolved_partcomp_jobs is not _UNRESOLVED:
            return self._resolved_partcomp_jobs
        if self.options.vcs_partcomp_jobs != 'auto':
            self._resolved_partcomp_jobs = self.options.vcs_partcomp_jobs
        else:
            self._resolved_partcomp_jobs = self.get_allocation_and_source()[0]
        return self._resolved_partcomp_jobs

    def get_allocation_and_source(self):
        """Return (slots, source) for the CPUs allocated to this job.

        Resolved once per simulator instance. -fastpartcomp=jN and -jN both size
        themselves from this, so a single probe keeps them consistent.
        """
        if self._allocation_and_source is None:
            self._allocation_and_source = detect_allocated_cpus()
            log.info("VCS auto-selected %d allocated CPUs from %s", self._allocation_and_source[0],
                     self._allocation_and_source[1])
        return self._allocation_and_source

    def get_make_jobs(self):
        """Return the csrc -jN worker count, or None when -j must not be passed.

        The count shares the allocation resolver with Partition Compile so both
        paths respect LSF/Slurm slots and CPU affinity. -j parallelizes the
        generated C compile and the link; with Partition Compile enabled
        -fastpartcomp=jN already owns that parallelism, so -j is omitted.
        """
        if self._resolved_make_jobs is not _UNRESOLVED:
            return self._resolved_make_jobs
        self._resolved_make_jobs = self._resolve_make_jobs()
        return self._resolved_make_jobs

    def _resolve_make_jobs(self):
        if self.options.vcs_make_jobs is None:
            log.info("VCS csrc -j is disabled by --no-vcs-make-jobs")
            return None
        if self.get_effective_partcomp_mode() != 'disabled':
            return None
        request = self.options.vcs_make_jobs
        if request == 'auto':
            # Resolve the allocation once and reuse it, so -fastpartcomp and -j
            # never disagree about how many slots this job actually owns.
            jobs, source = self.get_allocation_and_source()
        else:
            jobs, source = request, "--vcs-make-jobs"
        if jobs <= 1:
            log.info("VCS csrc -j is omitted; %s reports a single allocated CPU", source)
            return None
        log.info("VCS csrc compile and link selected -j%d from %s", jobs, source)
        return jobs

    def get_make_jobs_options(self):
        jobs = self.get_make_jobs()
        return '-j{}'.format(jobs) if jobs else ''

    def get_partition_compile_dir(self, vcomp_job):
        partition_dir = self.options.vcs_partcomp_dir or os.path.join(
            vcomp_job.job_dir,
            self._debug_partition_dirname('partitionlib'),
        )
        if not os.path.isabs(partition_dir):
            partition_dir = os.path.join(self.rcfg.proj_dir, partition_dir)
        return os.path.abspath(partition_dir)

    def _debug_partition_dirname(self, base_name):
        if self.options.gui:
            return base_name + '_gui'
        if self.options.waves is not None:
            return base_name + '_waves'
        return base_name

    def _find_vcs_xprop_config(self, bench_dir, xprop_mode):
        for cfg_name in self.VCS_XPROP_CONFIG_BY_MODE.get(xprop_mode, []):
            cfg_path = os.path.join(bench_dir, cfg_name)
            if os.path.exists(cfg_path):
                return cfg_path

        generic_cfg_path = os.path.join(bench_dir, 'vcs_xprop.cfg')
        if os.path.exists(generic_cfg_path):
            log.info(
                "Using generic VCS XPROP config '%s'; merge mode is controlled inside the config file.",
                generic_cfg_path,
            )
            return generic_cfg_path

        return None

    def generate_sim_options(self, test_job, seed):
        sim_args = []
        coverage_name = "{}_sv{}_i{}".format(test_job.name, seed, test_job.iteration)
        if self.options.cm:
            # Basenames, seeds and iteration numbers can coincide across distinct
            # configured tests (including VSO assignments). Bind the VDB entry to
            # the complete test identity and the claimed simulation directory.
            identity = [
                getattr(test_job, "target", test_job.name),
                os.path.basename(getattr(test_job, "job_dir", "")),
                getattr(test_job, "vso_run_id", None),
            ]
            digest = hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode("utf-8")).hexdigest()[:20]
            stem = re.sub(r"[^A-Za-z0-9_.-]", "_", test_job.name)[:64] or "test"
            coverage_name = "{}_{}_sv{}_i{}".format(stem, digest, seed, test_job.iteration)
        test_job.test_name_seed = coverage_name
        if self.options.vso:
            sim_args.extend(self.vso_workflow.sim_options(test_job))
        if self.options.vso_ccex:
            sim_args.extend(["-vso", "ccex"])
            if self.options.vso_ccex_rca:
                sim_args.extend(["-ccex_opts", "rca"])
            if self.options.vso_ccex_auto_merge_dir:
                merge_dir = os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.vso_ccex_auto_merge_dir))
                os.makedirs(merge_dir, exist_ok=True)
                sim_args.extend(["-ccex_opts", "auto_merge_dir={}".format(merge_dir)])
        if self.options.ico:
            sim_args.extend([
                "+ntb_solver_bias_mode_auto_config=2",
                "+ntb_solver_bias_shared_record={}".format(self._get_ico_shared_record()),
                "+ntb_solver_bias_wdir={}".format(self._get_ico_workdir()),
                "+ntb_solver_bias_test_type=uvm",
                "+ntb_solver_bias_test_name={}".format(coverage_name),
            ])
        if self.options.waves is not None:
            # VCS enables force-value capture at runtime. The generated UCLI Tcl
            # separately enables per-file glitch dumping on the returned FSDB ID.
            sim_args.extend(["+fsdb+glitch=0", "+fsdb+force"])
        sim_args.extend(["+ntb_random_seed={}".format(seed), "-xlrm", "hier_inst_seed", "-assert", "nopostproc"])
        if self.options.fgp is not None:
            sim_args.append("-fgp=num_threads:{}".format(self.options.fgp))
        if self.options.vcs_xprop_banner:
            sim_args.append("-xprop=banner")
        if self.options.vcs_xprop_report:
            sim_args.append("-report=xprop")
        # Coverage
        if self.options.cm:
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            sim_args.extend([
                "-cm",
                cm_level,
                "-cm_dir",
                test_job.vcomper.cov_work_dir,
                "-cm_name",
                coverage_name,
            ])
            test_job.coverage_db_path = os.path.join(
                test_job.vcomper.cov_work_dir,
                "snps",
                "coverage",
                "db",
                "testdata",
                coverage_name,
            )

        return shlex.join(sim_args)

    def get_wave_capture_options(self, test_job, wave_tcl_path):
        requested_wave_format = self.options.wave_type.lower()
        wave_database_path = test_job.job_dir
        default_capture_scope = 'hdl_top'

        if self.options.wave_tcl:
            if os.path.exists(self.options.wave_tcl):
                wave_tcl_path = os.path.abspath(self.options.wave_tcl)
                log.info(f"Using user-provided wave Tcl: {wave_tcl_path}")
            else:
                raise ValueError("{} not exists".format(self.options.wave_tcl))

        if requested_wave_format == 'fsdb':
            wave_database_path = os.path.join(wave_database_path, "waves.fsdb")
        else:
            raise ValueError("{} wave dumping is not supported for VCS".format(self.options.wave_type))

        # UCLI owns both generated and user-provided FSDB dump scripts. Keeping
        # this option here prevents VCS-specific runtime arguments reaching XRUN.
        simulation_options = " " + shlex.join(["-ucli", "-do", wave_tcl_path])
        return {
            'sim_opts': simulation_options,
            'wave_tcl_path': wave_tcl_path,
            'waves_db': wave_database_path,
            'default_capture': default_capture_scope,
            'render_template': not self.options.wave_tcl,
        }

    def get_no_wave_capture_options(self, test_job, nwaves_tcl_path):
        if not self.options.gui:
            return {
                'sim_opts': "",
                'tcl_commands': [],
            }

        tcl_commands = ["config reversedebug on", "run"]
        return {
            'sim_opts': " " + shlex.join(["-ucli", "-do", nwaves_tcl_path]),
            'tcl_commands': tcl_commands,
        }

    def get_wave_artifact_path(self, job_dir, wave_type):
        wave_type = wave_type.lower()
        if wave_type == 'fsdb':
            return os.path.join(job_dir, 'waves.fsdb')
        raise ValueError("{} wave dumping is not supported for VCS".format(wave_type))

    def setup_coverage_merge(self, vcomp_job):
        # Only create merge script if coverage was enabled
        if not self.options.cm or not hasattr(vcomp_job, 'cov_work_dir') or not vcomp_job.cov_work_dir:
            return

        merge_sh = os.path.join(self.rcfg.regression_dir, "{}_vcs_cov_merge.sh".format(vcomp_job.name))
        vcomp_job.coverage_merge_script = merge_sh
        vcomp_job.coverage_merge_log = os.path.splitext(merge_sh)[0] + ".log"
        vcomp_job.coverage_report_dir = os.path.join(self.rcfg.regression_dir,
                                                     "{}__vcs_cov_report".format(vcomp_job.name))
        vcomp_job.merged_coverage_dir = os.path.join(self.rcfg.regression_dir,
                                                     "{}__MERGED_COV.vdb".format(vcomp_job.name))
        vcomp_job.coverage_merge_succeeded = False
        self._render_coverage_merge(vcomp_job)
        self.rcfg.deferred_messages.append("VCS coverage merge script: {}".format(merge_sh))

    def _render_coverage_merge(self, vcomp_job):
        merge_sh = vcomp_job.coverage_merge_script
        cov_db_path = vcomp_job.cov_work_dir
        report_format = getattr(self.options, "vcs_urg_format", None) or "summary"
        summary_depth = getattr(self.options, "vcs_urg_summary_depth", None)
        if summary_depth is None and report_format == "summary":
            summary_depth = 1
        merge_template = self.env.get_template('vcs_cov_merge_template.sh.j2')

        with open(merge_sh, 'w') as filep:
            filep.write(
                merge_template.render(
                    cov_db_path=cov_db_path,
                    cov_db_paths=getattr(vcomp_job, "coverage_input_vdbs", [cov_db_path]),
                    merged_db_path=vcomp_job.merged_coverage_dir,
                    report_dir=vcomp_job.coverage_report_dir,
                    urg_command=self.get_tool_command("urg"),
                    urg_parallel=self.options.vcs_urg_parallel,
                    urg_show_tests=self.options.vcs_urg_show_tests,
                    urg_format=report_format,
                    urg_summary_depth=summary_depth,
                    verdi_command=shlex.join(self._coverage_viewer_argv()),
                ))
        st = os.stat(merge_sh)
        os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)

    def run_report_coverage_merge(self, vcomp_jobs):
        if not self.options.cm:
            return False
        failed = False
        incremental = getattr(self.options, "vcs_coverage_incremental", False)
        signature = {
            key: getattr(self.options, key, None)
            for key in ("cm", "vcs_cm_line", "vcs_cm_report", "vcs_cm_cond", "vcs_cm_tgl")
        }
        for label, job in vcomp_jobs.items():
            job.coverage_merge_succeeded = False
            job.coverage_merge_metrics = {}
            work = job
            started = time.perf_counter()
            status = getattr(job, "jobstatus", None)
            if incremental and (getattr(job, "coverage_cleanup_failed", False) or
                                (status is not None and not status.successful)):
                log.error("Incremental VCS coverage blocked after compilation or data cleanup failed for %s", job)
                failed = True
                continue
            try:
                with vcs_coverage.merge_lock(self.rcfg.regression_dir, str(job.name)):
                    if incremental:
                        with vcs_coverage.CoverageUpdate(job, self.rcfg.regression_dir, signature) as update:
                            work = update.job
                            prepare_duration = time.perf_counter() - started
                            if update.reuse:
                                log.info("No new VCS coverage datasets for %s; retaining the previous generation",
                                         job.name)
                                work.coverage_merge_succeeded = True
                            else:
                                self._render_coverage_merge(work)
                                merge_failed = self._run_coverage_merges({label: work})
                                work.coverage_merge_metrics["coverage_state_prepare_duration_s"] = prepare_duration
                                if merge_failed:
                                    failed = True
                                    job.coverage_merge_metrics = work.coverage_merge_metrics
                                    continue
                                with self._coverage_phase(work, "coverage_publish_duration_s"):
                                    vcs_coverage.write_json(vcs_coverage.history_path(work), work.coverage_history_data)
                                    update.publish()
                            work.coverage_merge_metrics["coverage_state_prepare_duration_s"] = prepare_duration
                            job.coverage_merge_metrics = work.coverage_merge_metrics
                            job.coverage_merge_metrics.update(
                                added_dataset_count=len(work.coverage_history_data["added_tests"])
                                if not update.reuse else 0,
                                duplicate_dataset_count=len(update.current["datasets"]) -
                                (len(work.coverage_history_data["added_tests"]) if not update.reuse else 0))
                            job.coverage_view_script_path = os.path.join(self.rcfg.regression_dir,
                                                                         "{}__run_coverage.sh".format(job.name))
                    else:
                        history_path = vcs_coverage.history_path(job) if getattr(job, "merged_coverage_dir",
                                                                                 None) else None
                        if history_path and os.path.lexists(history_path):
                            os.unlink(history_path)
                        if self._run_coverage_merges({label: job}):
                            failed = True
                            continue
                        with self._coverage_phase(job, "coverage_history_write_duration_s"):
                            history = vcs_coverage.make_history(job, signature)
                            if history is not None and history_path:
                                vcs_coverage.write_json(history_path, history)
                    job.coverage_merge_succeeded = True
                    self.rcfg.deferred_messages.append("Open VCS coverage: {} (report: {} --report)".format(
                        job.coverage_view_script_path, job.coverage_view_script_path))
            except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
                job.coverage_merge_succeeded = False
                job.coverage_merge_metrics = work.coverage_merge_metrics
                log.error("VCS coverage update failed for %s: %s", job.name, exc)
                failed = True
            finally:
                job.coverage_merge_metrics["coverage_total_duration_s"] = time.perf_counter() - started
        return failed

    def _run_coverage_merges(self, vcomp_jobs):
        if not self.options.cm:
            return False
        failed = False
        for vcomp_job in vcomp_jobs.values():
            vcomp_job.coverage_merge_succeeded = False
            vcomp_job.coverage_merge_metrics = {}
            viewer_path = self._coverage_viewer_path(vcomp_job)
            vcomp_job.coverage_view_script_path = None
            try:
                if os.path.lexists(viewer_path):
                    os.unlink(viewer_path)
            except OSError as exc:
                log.error("Cannot invalidate previous VCS coverage viewer %s: %s", viewer_path, exc)
                failed = True
                continue
            if getattr(vcomp_job, "coverage_cleanup_failed", False):
                log.error("VCS coverage merge blocked after data cleanup failed for %s", vcomp_job)
                failed = True
                continue
            status = getattr(vcomp_job, "jobstatus", None)
            if status is not None and not status.successful:
                log.error("VCS coverage merge skipped after unsuccessful compilation for %s", vcomp_job)
                failed = True
                continue
            merge_script = getattr(vcomp_job, "coverage_merge_script", None)
            if not merge_script:
                log.error("VCS coverage merge script is unavailable for %s", vcomp_job)
                failed = True
                continue
            try:
                with self._coverage_phase(vcomp_job, "coverage_total_duration_s"):
                    # Require outputs from this run, never an earlier dashboard.
                    with self._coverage_phase(vcomp_job, "output_cleanup_duration_s"):
                        for attribute in ("coverage_report_dir", "merged_coverage_dir"):
                            output_dir = getattr(vcomp_job, attribute, None)
                            if output_dir and os.path.isdir(output_dir):
                                shutil.rmtree(output_dir)
                    profile = getattr(self.options, "vcs_coverage_profile", False)
                    report_format = getattr(self.options, "vcs_urg_format", None) or "summary"
                    if profile:
                        self._record_coverage_size(vcomp_job, "input_db_bytes",
                                                   getattr(vcomp_job, "cov_work_dir", None))
                    log.info("Starting VCS coverage merge for %s", getattr(vcomp_job, "name", vcomp_job))
                    merge_log = getattr(vcomp_job, "coverage_merge_log",
                                        None) or os.path.splitext(merge_script)[0] + ".log"
                    vcomp_job.coverage_merge_log = merge_log
                    # Stream tool output to disk so cancellation keeps diagnostics
                    # and large reports do not accumulate console output in RAM.
                    with self._coverage_phase(vcomp_job, "urg_duration_s"), open(merge_log, "w",
                                                                                 encoding="utf-8") as output:
                        if profile == "phases" or report_format == "none":
                            phases = ("merge", ) if report_format == "none" else ("merge", "report")
                            for phase in phases:
                                output.write("=== URG {} ===\n".format(phase))
                                output.flush()
                                with self._coverage_phase(vcomp_job, "urg_{}_duration_s".format(phase)):
                                    result = run_bounded_process(["bash", merge_script, phase],
                                                                 stdout=output,
                                                                 stderr=subprocess.STDOUT,
                                                                 text=True)
                                if result.returncode != 0:
                                    break
                                if phase == "merge":
                                    self._validate_coverage_model(getattr(vcomp_job, "merged_coverage_dir", None))
                        else:
                            result = run_bounded_process(["bash", merge_script],
                                                         stdout=output,
                                                         stderr=subprocess.STDOUT,
                                                         text=True)
                    if result.returncode == 0:
                        with self._coverage_phase(vcomp_job, "model_validation_duration_s"):
                            self._validate_coverage_model(getattr(vcomp_job, "merged_coverage_dir", None))
                        if report_format != "none":
                            with self._coverage_phase(vcomp_job, "dashboard_parse_duration_s"):
                                report_dir = getattr(vcomp_job, "coverage_report_dir", None)
                                metrics = parse_coverage_summary(os.path.join(report_dir,
                                                                              "dashboard.txt")) if report_dir else {}
                                if not metrics:
                                    raise OSError("VCS coverage merge did not produce a complete dashboard.txt summary")
                            if report_format == "summary":
                                with self._coverage_phase(vcomp_job, "summary_write_duration_s"):
                                    self._write_coverage_summary(vcomp_job, metrics)
                                with self._coverage_phase(vcomp_job, "summary_cleanup_duration_s"):
                                    # URG summary still emits large module/group
                                    # tables. Keep the dashboard and provenance;
                                    # detailed analysis reads the final VDB.
                                    with os.scandir(report_dir) as entries:
                                        for entry in entries:
                                            if entry.name in ("dashboard.txt", "dashboard.html", "summary.json"):
                                                continue
                                            if entry.is_dir(follow_symlinks=False):
                                                shutil.rmtree(entry.path)
                                            else:
                                                os.unlink(entry.path)
                        if profile:
                            self._record_coverage_size(vcomp_job, "merged_db_bytes", vcomp_job.merged_coverage_dir)
                        with self._coverage_phase(vcomp_job, "viewer_script_write_duration_s"):
                            self._write_coverage_viewer(vcomp_job)
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.error("VCS coverage merge or output validation failed for %s: %s (log: %s)", vcomp_job, exc,
                          getattr(vcomp_job, "coverage_merge_log", "unavailable"))
                failed = True
                continue
            if result.returncode != 0:
                log.error("VCS coverage merge failed for %s (full log: %s):\n%s", vcomp_job, merge_log,
                          self._coverage_log_tail(merge_log))
                failed = True
            else:
                vcomp_job.coverage_merge_succeeded = True
        return failed

    def _coverage_viewer_argv(self):
        """Allow a coverage reader release independent of the VCS compiler."""
        command = os.environ.get("RV_VCS_COVERAGE_VIEWER")
        if command is None:
            return shlex.split(self.get_tool_runner()) + ["verdi"]
        if "\n" in command or "\r" in command:
            raise ValueError("RV_VCS_COVERAGE_VIEWER cannot contain newlines")
        argv = shlex.split(command)
        if not argv:
            raise ValueError("RV_VCS_COVERAGE_VIEWER cannot be empty")
        return argv

    def _coverage_viewer_path(self, job):
        return getattr(job, "coverage_view_script_output_path",
                       os.path.join(self.rcfg.regression_dir, "{}__run_coverage.sh".format(job.name)))

    def _write_coverage_viewer(self, job):
        """Publish a viewer only after this run's merged outputs were validated."""
        directory = os.path.abspath(self.rcfg.regression_dir)
        template = self.env.get_template("run_coverage_template.sh.j2")
        path = self._coverage_viewer_path(job)
        contents = template.render(
            merged_db_relative=os.path.relpath(getattr(job, "coverage_published_merged_dir", job.merged_coverage_dir),
                                               directory),
            report_dir_relative=os.path.relpath(getattr(job, "coverage_published_report_dir", job.coverage_report_dir),
                                                directory),
            viewer_argv=self._coverage_viewer_argv(),
        )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w",
                                             encoding="utf-8",
                                             newline="\n",
                                             dir=os.path.dirname(path),
                                             delete=False) as output:
                temporary = output.name
                output.write(contents)
                output.write("\n")
            os.chmod(temporary, os.stat(temporary).st_mode | stat.S_IEXEC)
            os.replace(temporary, path)
            job.coverage_view_script_path = path
        finally:
            if temporary and os.path.lexists(temporary):
                os.unlink(temporary)
        log.info("Open merged VCS coverage with %s", path)
        log.info("View the existing coverage report with %s --report", path)

    def _write_coverage_summary(self, job, metrics):
        """Keep one HTML page and source-test provenance beside the final VDB."""
        testdata = os.path.join(job.cov_work_dir, "snps", "coverage", "db", "testdata")
        tests = None
        if os.path.isdir(testdata):
            with os.scandir(testdata) as entries:
                tests = sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
        tests = getattr(job, "coverage_input_tests", tests)
        published_merged = getattr(job, "coverage_published_merged_dir", job.merged_coverage_dir)
        summary = {
            "bench":
            job.name,
            "metrics":
            metrics,
            "input_vdb":
            job.cov_work_dir,
            "merged_vdb":
            published_merged,
            "input_test_count":
            len(tests) if tests is not None else None,
            "input_tests":
            tests,
            "scores_from":
            "merged_vdb" if
            (getattr(self.options, "vcs_coverage_profile", False) == "phases"
             or getattr(job, "coverage_history_data", {}).get("merge_mode") == "incremental") else "input_tests",
        }
        if hasattr(job, "coverage_history_data"):
            history = job.coverage_history_data
            summary.update(merge_mode=history["merge_mode"],
                           previous_generation=history["previous_generation"],
                           added_tests=history["added_tests"])
        with open(os.path.join(job.coverage_report_dir, "summary.json"), "w", encoding="utf-8") as output:
            json.dump(summary, output, indent=2)
            output.write("\n")
        rows = "".join("<tr><th>{}</th><td>{}</td></tr>".format(html.escape(metric), html.escape(value))
                       for metric, value in metrics.items())
        command = "{} -cov -covdir {}".format(shlex.join(self._coverage_viewer_argv()), shlex.quote(published_merged))
        viewer = shlex.quote(
            os.path.abspath(getattr(job, "coverage_published_viewer_path", self._coverage_viewer_path(job))))
        contents = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} coverage summary</title>
<style>body{{font:16px system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#17212b}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px}}p{{line-height:1.6}}</style>
<h1>{name} coverage summary</h1>
<p>Contributing test datasets: <strong>{count}</strong>. Scores below summarize their combined coverage.
URG may represent these datasets as one merged test. This page does not establish regression pass status.</p>
<table><caption>Coverage scores</caption>{rows}</table>
<h2>Analyze the merged database</h2><p>Run the generated viewer script:</p><pre>{viewer}</pre>
<p>The script loads the merged database with this Verdi command:</p><pre>{command}</pre>
<p>Original test identities and database paths are recorded in summary.json. Use Verdi for coverage holes,
source annotation and hierarchy details.</p></html>
""".format(name=html.escape(str(job.name)),
           count=len(tests) if tests is not None else "N/A",
           rows=rows,
           viewer=html.escape(viewer),
           command=html.escape(command))
        with open(os.path.join(job.coverage_report_dir, "dashboard.html"), "w", encoding="utf-8") as output:
            output.write(contents)

    @staticmethod
    def _coverage_log_tail(path, limit=65536):
        try:
            with open(path, "rb") as stream:
                stream.seek(max(0, os.fstat(stream.fileno()).st_size - limit))
                return stream.read(limit).decode("utf-8", errors="replace")
        except OSError as exc:
            return "Unable to read coverage log: {}".format(exc)

    @staticmethod
    @contextmanager
    def _coverage_phase(vcomp_job, metric):
        """Keep partial timing evidence when a phase fails or is interrupted."""
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            vcomp_job.coverage_merge_metrics[metric] = elapsed
            log.info("VCS coverage %s for %s took %.3fs", metric.removesuffix("_duration_s"),
                     getattr(vcomp_job, "name", vcomp_job), elapsed)

    def cleanup_test_coverage(self, test_job):
        path = getattr(test_job, "coverage_db_path", None)
        if path:
            try:
                self._remove_coverage_directory(path)
            except OSError:
                test_job.vcomper.coverage_cleanup_failed = True
                raise

    @staticmethod
    def _remove_coverage_directory(path):
        """Remove owned data and surface errors instead of merging stale entries."""
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(mode):
            raise OSError("Coverage cleanup requires an owned directory: {}".format(path))
        shutil.rmtree(path)
        try:
            os.lstat(path)
        except FileNotFoundError:
            return
        raise OSError("Coverage cleanup left data at '{}'".format(path))

    @staticmethod
    def _validate_coverage_model(vdb_path):
        """Require the static design model, separately from per-test data."""
        design_path = os.path.join(vdb_path, "snps", "coverage", "db", "design") if vdb_path else ""
        if design_path and os.path.isdir(design_path):
            for directory, _subdirs, files in os.walk(design_path):
                if any(
                        os.path.isfile(os.path.join(directory, filename))
                        and os.path.getsize(os.path.join(directory, filename)) > 0 for filename in files):
                    return
        raise FileNotFoundError("VCS coverage requires a nonempty static design model at '{}'; "
                                "recompile with coverage enabled.".format(design_path or vdb_path))

    @staticmethod
    def _record_coverage_size(vcomp_job, metric, path):
        """Opt-in logical byte inventory; diagnostics must not invalidate a merge."""
        started = time.perf_counter()
        size = None

        def identity(path, metadata):
            # Windows DirEntry.stat can omit inode numbers. Obtain the real
            # identity there without adding stat calls on the EDA filesystem.
            if not metadata.st_ino:
                metadata = os.stat(path)
            return ((metadata.st_dev, metadata.st_ino) if metadata.st_ino else os.path.normcase(os.path.realpath(path)))

        try:
            metadata = os.stat(path) if path else None
            if metadata and stat.S_ISDIR(metadata.st_mode):
                size = 0
                pending = [(path, metadata)]
                directories, files = set(), set()
                while pending:
                    directory, metadata = pending.pop()
                    directory_id = identity(directory, metadata)
                    if directory_id in directories:
                        continue
                    directories.add(directory_id)
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            metadata = entry.stat(follow_symlinks=True)
                            if stat.S_ISDIR(metadata.st_mode):
                                # Partition compilation links its VDB models
                                # into the work VDB. Follow them once, including
                                # aliases and cycles, without another stat.
                                pending.append((entry.path, metadata))
                            elif stat.S_ISREG(metadata.st_mode):
                                file_id = identity(entry.path, metadata)
                                if file_id not in files:
                                    files.add(file_id)
                                    size += metadata.st_size
        except OSError as exc:
            size = None
            log.info("Could not inventory VCS coverage %s at %s: %s", metric, path, exc)
        vcomp_job.coverage_merge_metrics[metric] = size
        vcomp_job.coverage_merge_metrics[metric + "_scan_s"] = time.perf_counter() - started
        log.info("VCS coverage %s for %s: %s (scan %.3fs)", metric, getattr(vcomp_job, "name", vcomp_job),
                 size if size is not None else "N/A", vcomp_job.coverage_merge_metrics[metric + "_scan_s"])

    def collect_coverage_data(self, vcomp_jobs):
        if not self.options.cm or getattr(self.options, "vcs_urg_format", None) == "none":
            return {
                getattr(job, "name",
                        vcomp.split(":")[-1]): aggregate_coverage_metrics({})
                for vcomp, job in vcomp_jobs.items()
            }
        coverage = {}
        for vcomp, job in vcomp_jobs.items():
            report_dir = getattr(job, "coverage_report_dir", None)
            metrics = (parse_coverage_summary(os.path.join(report_dir, "dashboard.txt"))
                       if report_dir and getattr(job, "coverage_merge_succeeded", True) else {})
            coverage[getattr(job, "name", vcomp.split(":")[-1])] = aggregate_coverage_metrics(metrics)
        return coverage

    def get_log_parsing_info(self):
        return {'warning_regex': r"(?i)^(?:\s*(?:Warning|Error)(?:-|\s*:)|.+:\s*(?:warning|error):).*"}

    def get_ignored_compile_warning_line_numbers(self, log_path):
        # Pre-screen with cheap substring checks: the common case (no make
        # clock-skew warnings) avoids the full regex pass and early-exits.
        try:
            with open(log_path, 'rb') as probe:
                content = probe.read()
        except (OSError, IOError):
            return set()
        if b"make" not in content or b"warning" not in content:
            return set()
        # At least one "make" and one "warning" → run the regex pass.
        future_mtime_regex = re.compile(r"(?i)\bmake(?:\[\d+\])?:\s*warning:\s*file .+ has modification time "
                                        r"([0-9]+(?:\.[0-9]+)?)\s+s in the(?:\s+future\b|(?P<continued>\s*\\\s*$))")
        future_mtime_continuation_regex = re.compile(r"(?i)^\s*future\b")
        clock_skew_regex = re.compile(r"(?i)\bmake(?:\[\d+\])?:\s*warning:\s*clock skew detected\.\s*"
                                      r"your build may be incomplete\.")
        benign_future_mtime_lines = set()
        clock_skew_summary_lines = set()
        continued_future_mtime = None

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as logp:
            for line_number, line in enumerate(logp, start=1):
                if continued_future_mtime is not None:
                    warning_line_number, skew_seconds = continued_future_mtime
                    if (future_mtime_continuation_regex.search(line)
                            and skew_seconds < _MAX_BENIGN_MAKE_CLOCK_SKEW_SECONDS):
                        benign_future_mtime_lines.add(warning_line_number)
                    continued_future_mtime = None

                match = future_mtime_regex.search(line)
                if match:
                    skew_seconds = float(match.group(1))
                    if match.group("continued") is not None:
                        continued_future_mtime = (line_number, skew_seconds)
                    elif skew_seconds < _MAX_BENIGN_MAKE_CLOCK_SKEW_SECONDS:
                        benign_future_mtime_lines.add(line_number)
                if clock_skew_regex.search(line):
                    clock_skew_summary_lines.add(line_number)

        if benign_future_mtime_lines:
            return benign_future_mtime_lines | clock_skew_summary_lines
        return set()

    def get_gui_command_options(self):
        # Enable Verdi debug features along with DVE/Verdi GUI
        return " -gui=verdi +UVM_VERDI_TRACE=UVM_AWARE +UVM_CONFIG_TRACE +UVM_PHASE_TRACE +UVM_OBJECTION_TRACE +UVM_RESOURCE_DB_TRACE +UVM_LOG_TRACE "

    def _partcomp_manifest_identity(self, vcomp_job):
        fingerprint = vcomp_job.compile_fingerprint
        try:
            os_release = platform.freedesktop_os_release()
        except (AttributeError, OSError):
            os_release = {}
        return {
            "schema_version": 1,
            "tool": {
                "vcs_home": os.environ.get("VCS_HOME", ""),
                "vcs_tool_id": self.get_tool_identity(),
                "runner": self.get_tool_runner(),
                "platform": platform.system(),
                "machine": platform.machine(),
                "os_id": os_release.get("ID", ""),
                "os_version": os_release.get("VERSION_ID", ""),
            },
            "inputs": {
                "compile_args_sha256": fingerprint.get("compile_args_sha256"),
                "compile_inputs_manifest_sha256": fingerprint.get("compile_inputs_manifest_sha256"),
                "extra_inputs_content_sha256": fingerprint.get("extra_inputs_content_sha256"),
            },
            "configuration": {
                "partcomp_mode": self.options.vcs_partcomp_mode,
                "three_step": bool(getattr(vcomp_job, "vcs_three_step", False)),
                "debug_mode": "gui" if self.options.gui else "waves" if self.options.waves is not None else "default",
                "debug_access": self.get_debug_access(vcomp_job),
                "coverage": self.options.cm,
                "coverage_line": self.options.vcs_cm_line,
                "coverage_report": self.options.vcs_cm_report or [],
                "coverage_cond": self.options.vcs_cm_cond,
                "coverage_tgl": self.options.vcs_cm_tgl,
                "fgp": self.options.fgp is not None,
                "smartlog": self.use_smartlog(),
                "xprop": self.options.xprop if self.options.xprop_was_explicit else None,
                "xprop_flowctrl": self.options.vcs_xprop_flowctrl,
                "xprop_mmsopt": self.options.vcs_xprop_mmsopt,
                "rtl_defines": self.options.rtl_defines or [],
                "vso": self.options.vso,
                "vso_cbv": self.options.vso_cbv,
                "vso_build_name": self.vso_workflow.build_name(vcomp_job) if self.options.vso else None,
                "vso_workdir": self.vso_workflow.workdir() if self.options.vso_cbv else None,
                "vso_ccex": self.options.vso_ccex,
                "vso_ccex_rca": self.options.vso_ccex_rca,
            },
        }

    def validate_compile_cache_context(self, vcomp_job):
        sharedlib = self.options.vcs_partcomp_sharedlib
        if sharedlib is None:
            return
        manifest_path = os.path.join(os.path.abspath(sharedlib), PARTCOMP_MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            log.warning("VCS Partition Compile shared library has no rules_verilog manifest: %s", manifest_path)
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as filep:
                actual = json.load(filep)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Cannot read VCS Partition Compile manifest '{}': {}".format(manifest_path,
                                                                                            exc)) from exc
        expected = self._partcomp_manifest_identity(vcomp_job)
        if actual != expected:
            mismatches = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
            raise RuntimeError("VCS Partition Compile shared library is incompatible ({}): {}".format(
                ", ".join(mismatches), manifest_path))

    def prepare_compile_execution(self, vcomp_job, reusing_compile):
        if not self.options.cm:
            return
        # An invoked VCS compile can still reuse partition objects or -Mupdate
        # outputs. Those may not regenerate the static coverage model, so keep
        # it and its partition links for both compilation and executable reuse.
        path = os.path.join(vcomp_job.cov_work_dir, "snps", "coverage", "db", "testdata")
        try:
            self._remove_coverage_directory(path)
        except OSError:
            vcomp_job.coverage_cleanup_failed = True
            raise
        vcomp_job.coverage_cleanup_failed = False

    def validate_reusable_compile_artifacts(self, vcomp_job):
        simv_path = os.path.join(vcomp_job.job_dir, "simv")
        if not os.path.isfile(simv_path) or not os.access(simv_path, os.X_OK):
            raise FileNotFoundError(
                "VCS --no-compile requires an existing elaborated executable at '{}'".format(simv_path))
        if self.options.cm:
            self._validate_coverage_model(getattr(vcomp_job, "cov_work_dir", None))
        if getattr(vcomp_job, "vcs_three_step", False):
            setup_path = self.get_analysis_setup_file(vcomp_job)
            work_dir = self.get_analysis_work_dir(vcomp_job)
            if not os.path.isfile(setup_path) or not os.path.isdir(work_dir):
                raise FileNotFoundError(
                    "VCS --no-compile requires the three-step analysis library and setup file at '{}' and '{}'".format(
                        work_dir, setup_path))

    def record_compile_artifacts(self, vcomp_job):
        self.validate_reusable_compile_artifacts(vcomp_job)
        if (self.options.dtl or self.get_effective_partcomp_mode() == 'disabled'
                or (self.options.vcs_partcomp_dir is None and self.options.vcs_partcomp_sharedlib is None)):
            return
        partition_dir = self.get_partition_compile_dir(vcomp_job)
        os.makedirs(partition_dir, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".partcomp-manifest-", dir=partition_dir, text=True)
        manifest_path = os.path.join(partition_dir, PARTCOMP_MANIFEST_FILENAME)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
                json.dump(self._partcomp_manifest_identity(vcomp_job), filep, indent=2, sort_keys=True)
                filep.write("\n")
            os.replace(temporary_path, manifest_path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    def collect_compile_metrics(self, vcomp_job):
        reused = bool(self.options.no_compile or getattr(vcomp_job, "compile_cache_hit", False))
        effective_partcomp_mode = self.get_effective_partcomp_mode()
        metrics = {
            "compile_cache_hit": bool(getattr(vcomp_job, "compile_cache_hit", False)),
            "compile_reused": reused,
            "partcomp_mode": effective_partcomp_mode,
            "partcomp_jobs": self.get_partcomp_jobs() if effective_partcomp_mode != 'disabled' and not reused else None,
            "make_jobs": self.get_make_jobs() if not reused else None,
        }
        if reused or not self.options.vcs_profile or not os.path.isfile(vcomp_job.log_path):
            return metrics
        markers = {"PC_SHARED": 0, "PC_RECOMPILE": 0}
        with open(vcomp_job.log_path, "r", encoding="utf-8", errors="ignore") as filep:
            for line in filep:
                for marker in markers:
                    if marker in line:
                        markers[marker] += 1
        metrics["profile_marker_lines"] = markers
        return metrics

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for VCS, including logging.
        """
        cmd_parts = shlex.split(self.get_tool_runner())
        cmd_parts.append(os.path.join(vcomp_job_dir, "simv"))
        if self.use_smartlog():
            cmd_parts.append("-sml")
        cmd_parts.extend(["-l", log_path])
        if user_args_list:
            cmd_parts.extend(user_args_list)
        full_command = shlex.join(cmd_parts)
        if sim_opts:
            full_command += " " + sim_opts

        log.debug(f"Constructed VCS sim command: {full_command}")
        return full_command

    def get_sim_working_dir(self, test_job):
        """Run each VCS simulation from its own test job directory."""
        return test_job.job_dir

    def get_pre_sim_commands(self, test_job):
        if getattr(test_job.vcomper, "vcs_three_step", False):
            setup_path = shlex.quote(self.get_analysis_setup_file(test_job.vcomper))
            return ["export SYNOPSYS_SIM_SETUP={}".format(setup_path)]
        return []

    def get_post_sim_commands(self, test_job):
        return []
