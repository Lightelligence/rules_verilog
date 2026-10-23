import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from lib.compile_cache import CompileBuildLease, CompileDirectoryLock


def _lease_worker(directory, shared, acquired, waiting, release, downgrade, downgraded):
    lease = CompileBuildLease(directory, shared=shared, legacy_lock_path=directory + ".legacy")
    try:
        while not lease.acquire():
            waiting.set()
            if release.wait(0.01):
                return
        if not shared:
            Path(directory, "simv").write_text("rebuilt", encoding="ascii")
        acquired.set()
        if not shared:
            while not downgrade.wait(0.01):
                if release.is_set():
                    return
            lease.downgrade()
            downgraded.set()
        release.wait(20)
    finally:
        lease.release()


def _orphan_reader(directory, pid_queue, ready, stop):
    lease = CompileBuildLease(directory, shared=True)
    while not lease.acquire():
        time.sleep(0.01)
    script = ("import pathlib, sys, time; "
              "ready, stop = map(pathlib.Path, sys.argv[1:]); ready.touch(); "
              "exec('while not stop.exists(): time.sleep(0.01)')")
    child = subprocess.Popen([sys.executable, "-B", "-c", script, ready, stop], pass_fds=lease.file_descriptors)
    pid_queue.put(child.pid)
    # Terminated by the test; its child must continue protecting the build.
    time.sleep(30)


@unittest.skipUnless(os.name == "posix", "POSIX flock process semantics")
class CompileBuildLeaseTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = os.path.join(self.temp.name, "tb__VCS_VCOMP")
        os.mkdir(self.directory)
        Path(self.directory, "simv").write_text("original", encoding="ascii")
        self.context = multiprocessing.get_context("spawn")

    def worker(self, shared):
        events = [self.context.Event() for _ in range(5)]
        acquired, waiting, release, downgrade, downgraded = events
        process = self.context.Process(target=_lease_worker, args=(self.directory, shared, *events))
        process.start()

        def cleanup():
            release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)

        self.addCleanup(cleanup)
        return process, acquired, waiting, release, downgrade, downgraded

    def test_readers_overlap_recompile_waits_and_downgrade_allows_new_reader(self):
        first, first_acquired, _, first_release, _, _ = self.worker(True)
        self.assertTrue(first_acquired.wait(5))
        second, second_acquired, _, second_release, _, _ = self.worker(True)
        self.assertTrue(second_acquired.wait(5), "a second no-compile reader was serialized")
        writer, writer_acquired, writer_waiting, writer_release, downgrade, downgraded = self.worker(False)
        self.assertTrue(writer_waiting.wait(5))
        self.assertFalse(writer_acquired.is_set())
        self.assertEqual("original", Path(self.directory, "simv").read_text(encoding="ascii"))

        late, late_acquired, late_waiting, _, _, _ = self.worker(True)
        self.assertTrue(late_waiting.wait(5))
        self.assertFalse(late_acquired.is_set(), "new readers bypassed a waiting writer")
        first_release.set()
        first.join(5)
        self.assertFalse(writer_acquired.wait(0.1), "recompile ignored the remaining reader")
        self.assertEqual("original", Path(self.directory, "simv").read_text(encoding="ascii"))
        second_release.set()
        second.join(5)
        self.assertTrue(writer_acquired.wait(5))
        self.assertEqual("rebuilt", Path(self.directory, "simv").read_text(encoding="ascii"))
        self.assertFalse(late_acquired.is_set())
        downgrade.set()
        self.assertTrue(downgraded.wait(5))
        self.assertTrue(late_acquired.wait(5), "a completed compile retained its exclusive lock")
        self.assertTrue(writer.is_alive(), "the reader only entered after the original run exited")
        self.assertEqual(0, first.exitcode)
        self.assertEqual(0, second.exitcode)

    def test_cancelled_writer_releases_admission_gate(self):
        reader = CompileBuildLease(self.directory, shared=True)
        self.addCleanup(reader.release)
        self.assertTrue(reader.acquire())
        writer, _, waiting, release, _, _ = self.worker(False)
        self.assertTrue(waiting.wait(5))
        release.set()
        writer.join(5)
        self.assertEqual(0, writer.exitcode)
        other = CompileBuildLease(self.directory, shared=True)
        self.addCleanup(other.release)
        self.assertTrue(other.acquire(), "cancelled writer leaked the entry gate")

    def test_legacy_runtime_owner_blocks_new_readers(self):
        legacy = CompileDirectoryLock(self.directory + ".legacy")
        self.addCleanup(legacy.release)
        self.assertTrue(legacy.acquire(blocking=False))
        lease = CompileBuildLease(self.directory, shared=True, legacy_lock_path=legacy.path)
        self.addCleanup(lease.release)
        self.assertFalse(lease.acquire())
        legacy.release()
        self.assertTrue(lease.acquire())
        self.assertFalse(CompileDirectoryLock(legacy.path).acquire(blocking=False))

    def test_canonical_directory_aliases_share_the_build_lock(self):
        alias = os.path.join(self.temp.name, "alias")
        os.symlink(self.directory, alias)
        reader = CompileBuildLease(alias, shared=True)
        writer = CompileBuildLease(self.directory)
        self.addCleanup(reader.release)
        self.addCleanup(writer.release)
        self.assertTrue(reader.acquire())
        self.assertFalse(writer.acquire())
        reader.release()
        self.assertTrue(writer.acquire())

    def test_child_keeps_read_lease_after_controller_is_terminated(self):
        ready = os.path.join(self.temp.name, "child.ready")
        stop = os.path.join(self.temp.name, "child.stop")
        pid_queue = self.context.Queue()
        controller = self.context.Process(target=_orphan_reader, args=(self.directory, pid_queue, ready, stop))
        controller.start()
        child_pid = pid_queue.get(timeout=5)

        def cleanup():
            Path(stop).touch()
            if controller.is_alive():
                controller.terminate()
            controller.join(5)

        self.addCleanup(cleanup)
        deadline = time.monotonic() + 5
        while not os.path.exists(ready) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(os.path.exists(ready))
        controller.terminate()
        controller.join(5)
        os.kill(child_pid, 0)
        writer = CompileBuildLease(self.directory)
        self.addCleanup(writer.release)
        self.assertFalse(writer.acquire(), "simulator lost protection with its controller")
        Path(stop).touch()
        deadline = time.monotonic() + 5
        while not writer.acquire() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(writer.acquired)


if __name__ == "__main__":
    unittest.main()
