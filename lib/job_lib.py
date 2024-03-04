#!/usr/bin/env python
"""Definitions for Job-running and Job-related classes."""

################################################################################
# standard lib imports
import bisect
import datetime
import enum
import os
import signal
import subprocess
import threading
import time


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


class Job():

    _priority_cache = {}

    def __init__(self, rcfg, name):
        self.rcfg = rcfg # Regression cfg object
        self.name = name

        # String set by derived class of the directory to run this job in
        self.job_dir = None

        self.job_lib = None

        self.job_start_time = None
        self.job_stop_time = None

        self._jobstatus = JobStatus.NOT_STARTED

        self.suppress_output = False
        # FIXME need to implement a way to actually override this
        # FIXME add multiplier for --gui
        #self.timeout = 12.25 # Float hours
        self.timeout = rcfg.options.timeout

        self.priority = -3600 # Not sure that making this super negative is necessary if we log more stuff
        self._get_priority()
        self.log = self.rcfg.log
        self.log.debug("%s priority=%d", self, self.priority)

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
            self.log.error("%s added null dep", self)
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
        self.log.info("Starting %s %s", self.__class__.__name__, self.name)
        self.job_start_time = datetime.datetime.now()

        if not os.path.exists(self.job_dir):
            self.log.debug("Creating job_dir: %s", self.job_dir)
            os.mkdir(self.job_dir)

    def post_run(self):
        self.job_stop_time = datetime.datetime.now()
        self.log.debug("post_run %s %s duration %s", self.__class__.__name__, self.name, self.duration_s)
        self.completed = True

    @property
    def duration_s(self):
        try:
            delta = self.job_stop_time - self.job_start_time
        except TypeError:
            return 0
        return delta.total_seconds()


class JobRunner():

    def __init__(self, job, manager):
        self.job = job
        self.job.job_lib = self

        self.manager = manager

        self.done = False
        self.log = job.log

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
        self.log = job.log

    def check_for_done(self):
        if self.done:
            return self.done
        try:
            result = self._check_for_done()
        except Exception as exc:
            self.log.error("Job failed %s:\n%s", self.job, exc)
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
            self.log.error("%s  exceeded timeout value of %s (job will be killed)", self.job, self.job.timeout)
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

    def __init__(self, options, log):
        self.log = log
        self.max_parallel = options['parallel_max']
        self.sleep_interval = options['parallel_interval']
        self.idle_print_interval = datetime.timedelta(seconds=options['idle_print_seconds'])

        self._quit_count = options['quit_count']
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

        self.job_lib_type = SubprocessJobRunner

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
                    if job.job_lib.check_for_done():
                        self.log.debug("%s body done", job)
                        try:
                            job.post_run()
                        except Exception as exc:
                            self.log.error("%s  post_run_failed()\n:%s", job, exc)
                        if not job.jobstatus.successful:
                            self._error_count += 1
                            if self._error_count >= self._quit_count:
                                self._graceful_exit()
                            self._move_children_to_skipped(job)
                        self._active.pop(i)
                        self._last_done_or_idle_print = datetime.datetime.now()
                        #self._done.append(job)
                        # Ideally this would be before post_run, but pass_fail status may be set there
                        self._move_todo_to_ready()
                        self._move_ready_to_active()
                time_since_last_done_or_idle_print = datetime.datetime.now() - self._last_done_or_idle_print
                if time_since_last_done_or_idle_print > self.idle_print_interval:
                    self._last_done_or_idle_print = datetime.datetime.now()
                    self._print_state(self.log.info)

                time.sleep(self.sleep_interval)
            if not len(self._active):
                time.sleep(self.sleep_interval)

    def _move_children_to_skipped(self, job):
        for child in job._children:
            self.log.info("Skipping job %s due to dependency (%s) failure", child, job)
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
        self._print_state(self.log.debug)
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
                    self.log.error("Skipping job %s due dependency failure", job)
                    jobs_that_advanced_state.append(i)
                    self._skipped.append(job)
                    job.jobstatus = JobStatus.SKIPPED

        # Can't iterate and remove in list at the same time easily
        for i in reversed(jobs_that_advanced_state):
            self._todo.pop(i)

    def _move_ready_to_active(self):
        self._print_state(self.log.debug)

        available_to_run = self.max_parallel - len(self._active)

        jobs_that_advanced_state = []
        for i in range(available_to_run):
            try:
                job = self._ready[i]
            except IndexError:
                # We have more jobs available than todos
                continue # Need to finish loop or final cleanup wont happen
            job.pre_run()
            self.log.debug("%s priority: %d", job, job.priority)
            self.job_lib_type(job, self)
            jobs_that_advanced_state.append(i)
            self._active.append(job)

        for i in reversed(jobs_that_advanced_state):
            self._ready.pop(i)

    def _graceful_exit(self):
        if self._done_grace_exit:
            return
        self.exited_prematurely = True
        self._done_grace_exit = True
        self.log.warn("Exceeded quit count. Graceful exit.")
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
        self.log.info("Waiting until all jobs are completed.")
        while len(self._todo) or len(self._ready) or len(self._active):
            self.log.debug("still waiting")
            time.sleep(30)

    def stop(self):
        """Stop the job runner thread (cpu intenstive). This is really more of a pause than a full stop&exit."""
        self._run_jobs_thread_active = False
        self.exited_prematurely = True

    def kill(self):
        self.stop()
        for job in self._active:
            job.job_lib.kill()


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
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def __repr__(self):
        return 'Bazel("{}")'.format(self.bazel_target)


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
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

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
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def __repr__(self):
        return 'Bazel Shutdown'
