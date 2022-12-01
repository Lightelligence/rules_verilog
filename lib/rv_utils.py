#!/usr/bin/env python
"""Utility class definitions."""

import datetime
import getpass
import os
import re

# I'd rather create a "plain" message in the logger
# that doesn't format, but more work than its worth
LOGGER_INDENT = 8
SIMRESULTS = os.environ.get('SIMRESULTS', '')


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


class IterationCfg():

    def __init__(self, target):
        self.target = target
        self.spawn_count = 1
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


def calc_simresults_location(checkout_path):
    """Calculate the path to put regression results."""
    username = getpass.getuser()

    # FIXME, we may want to detect who owns the check to allow
    # for rerunning in someone else's area? # pylint: disable=fixme
    sim_results_home = os.path.join(SIMRESULTS, username)
    if not os.path.exists(sim_results_home):
        os.mkdir(sim_results_home)

    # If username is in the checkout_path try to reduce the name
    # Assume username is somewhere is path
    try:
        checkout_path = re.search("{}/(.*)".format(username), checkout_path).group(1)
    except AttributeError:
        pass
    checkout_path = checkout_path.replace('/', '_')
    # Adding the datetime into the regression directory will force a recompile.
    # Ideally, the vcomp directory will need to have the same name
    # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
    # regression_directory = '{}__{}'.format(checkout_path, strdate)
    regression_directory = checkout_path
    regression_directory = os.path.join(sim_results_home, regression_directory)
    return regression_directory

def run_command(cmd, log, return_stdout=False):
    """Run arbitrary shell command, print results to stdout and stderr, return (returncode, stdout).

    If return_stdout = True, stdout for the shell command is captured in python and returned from this function
    instead of appearing in stdout of the console. The stdout from the shell command is always included
    in the logfile.

    """
    log.debug("Running shell command: %s", cmd)

    # Big workaround for how the FileHandler works while a subprocess is running to get its stdout/stderr
    # in both in the terminal's stdout/stderr and the logfile in (approximately) realtime
    # Without this workaround, the subprocess stdout/stderr wouldn't show up either in the terminal or the log
    # until after the subprocess finishes. This is bad when running a long program (like flowtool)
    # because the program's output would be inaccessible until it finished.
    # Some internet sources recommended using the pexpect module instead of subprocess to solve this problem, but
    # I've never used that module before and we don't have any preference code for pexpect so I didn't
    # want to open that can of worms.
    # You also can't use TemporaryFiles for subprocess stdout/stderr, start the subprocess, enter a polling/sleep loop,
    # read the TemporaryFiles in the loop, and dump those messages to the log in the loop. I wasn't able to get
    # that process to work.
    # Also, adding a | tee to the subprocess command without mucking with the filehandler doesn't work
    # Since the FileHandle the log is writing to is still active when the subprocess is running, tee can't
    # actually write to file so it silently fails.
    # The way we get around this is to temporarily close the stream associated with the FileHandler (but don't
    # actually remove the FileHandler), running the command piped through tee, then opening a new stream for
    # the FileHandler. It's very important to note that this only closes the stream associated with the FileHandler,
    # NOT the FileHandler itself. Closing the FileHandler itself is too big a hammer. If we closed it, we would have to
    # create a new FileHandler and re-configure it from scratch, which would have bad performance. Instead, we only
    # close the stream and force in a new StringIO stream. The original FileHandler still exists and operates as
    # normal, except the messages are sent to this StringIO stream. Since the FileHandler is sending to a StringIO
    # and the actual file is closed, tee can append to the logfile. After the process finishes and tee has relinquished
    # control, open a new stream to the original logfile, and connect that stream back to the FileHandler.
    # It's possible that while the subprocess is running, other messages are sent to the logger. e.g. there was a fork
    # upstream in the code or there were log messages between the Popen creation and the wait() call. Those log messages
    # would be correctly sent to the log StreamHandler and to the StringIO. Read all those messages from that StringIO
    # (which are already formatted correctly) and write them out raw to the re-created file stream in the FileHandler.

    filehandler = log.handlers[1]
    name = filehandler.stream.name
    enc = filehandler.stream.encoding
    filehandler.stream.close()

    # Capture any messages that might happen during the subprocess prevent a:
    #   ValueError: I/O operation on closed file
    # from happening on the closed filehandler.stream
    # The captured messages are replayed to the filehander later when the filehandler.stream is reopened
    sio = StringIO()
    filehandler.stream = sio

    # Need to 'set -o pipefail;' before the actual command. Without it, if tee has a returncode of 0, the subprocess
    # will have a returncode of 0 regardless of if the preceeding command failed.
    formatted_cmd = "set -o pipefail; {} | tee -a {}".format(cmd, name)
    popen_kwargs = {'shell': True}
    stdout_ret_string = ""

    with TemporaryFile() as stdout_fp:
        if return_stdout:
            popen_kwargs['stdout'] = stdout_fp
        pid = subprocess.Popen(formatted_cmd, **popen_kwargs)
        pid.wait()

        log.debug("Messages during subprocess (approximately, it may be out of order due to threading)")
        # Save any log messages that happen between disable and reenable of file stream to replay later
        new_stream = open(name, 'a', encoding=enc)
        filehandler.stream = new_stream

        # Option
        sio.seek(0)
        new_stream.write(sio.read())
        log.debug("Finished message sync")

        # If return_stdout, read the filehandle
        if return_stdout:
            stdout_fp.seek(0)
            stdout = stdout_fp.read()
            if stdout:
                stdout_ret_string = stdout.decode('utf-8')

    returncode = 0
    if pid.returncode:
        log.error("Command failed: %s", cmd)
        returncode = pid.returncode

    return returncode, stdout_ret_string
