#!/usr/bin/env python
"""Utility class definitions."""

import datetime

# I'd rather create a "plain" message in the logger
# that doesn't format, but more work than its worth
LOGGER_INDENT = 8


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
