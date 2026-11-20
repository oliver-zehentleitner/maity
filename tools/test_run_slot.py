"""tools/run_slot.sh: at most MAITY_RUN_SLOTS commands at a time; a further one waits, says so
and starts once a slot is free; a command inside a slot keeps it; each run's start and end go to
the slot directory's log."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "run_slot.sh"


@unittest.skipIf(shutil.which("flock") is None, "needs util-linux flock")
class RunSlotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {k: v for k, v in os.environ.items() if k != "MAITY_RUN_SLOT"}
        self.env["MAITY_RUN_SLOTS_DIR"] = str(self.tmp / "slots")
        self.env.pop("PYTEST_XDIST_AUTO_NUM_WORKERS", None)

    def holder(self, name: str, gate: Path, ready: Path) -> subprocess.Popen[str]:
        """A command that holds its slot until `gate` exists."""
        command = f"touch {ready}; until [ -f {gate} ]; do sleep 0.05; done"
        env = {**self.env, "MAITY_RUN_NAME": name}
        return subprocess.Popen([SCRIPT, "sh", "-c", command], env=env, text=True)

    def wait_for(self, path: Path) -> None:
        deadline = time.monotonic() + 30
        while not path.exists():
            self.assertLess(time.monotonic(), deadline, f"{path} never appeared")
            time.sleep(0.02)

    def test_a_third_run_waits_says_who_holds_the_slots_and_then_runs(self) -> None:
        gate = self.tmp / "gate"
        holders: list[subprocess.Popen[str]] = []

        def release() -> None:
            # Runs before the directory is removed (cleanups run last-in first), and waits for
            # the holders: a failed assert must not leave them waiting for a gate that is gone.
            gate.touch()
            for proc in holders:
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        self.addCleanup(release)
        for name in ("alpha", "beta"):
            ready = self.tmp / f"ready-{name}"
            holders.append(self.holder(name, gate, ready))
            self.wait_for(ready)
        third = subprocess.Popen(
            [SCRIPT, "sh", "-c", f"touch {self.tmp / 'third'}"],
            env=self.env,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1)
        self.assertIsNone(third.poll(), "the third run must wait, not fail")
        self.assertFalse((self.tmp / "third").exists())
        gate.touch()
        _, err = third.communicate(timeout=30)
        self.assertEqual(third.returncode, 0)
        self.assertTrue((self.tmp / "third").exists())
        self.assertIn("all 2 run slots are taken", err)
        self.assertIn("alpha", err)
        self.assertIn("beta", err)
        for proc in holders:
            self.assertEqual(proc.wait(timeout=30), 0)

    def test_a_command_inside_a_slot_keeps_it(self) -> None:
        env = {**self.env, "MAITY_RUN_SLOTS": "1"}
        inner = f"{SCRIPT} sh -c 'echo inner=$MAITY_RUN_SLOT'"
        out = subprocess.run(
            [SCRIPT, "sh", "-c", inner], env=env, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "inner=0")

    def test_pytest_auto_starts_two_workers_unless_set(self) -> None:
        def workers(env: dict[str, str]) -> str:
            return subprocess.run(
                [SCRIPT, "sh", "-c", 'echo "$PYTEST_XDIST_AUTO_NUM_WORKERS"'],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        self.assertEqual(workers(self.env), "2")
        self.assertEqual(workers({**self.env, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1"}), "1")

    def test_the_commands_exit_status_is_kept(self) -> None:
        result = subprocess.run([SCRIPT, "sh", "-c", "exit 5"], env=self.env)
        self.assertEqual(result.returncode, 5)

    def test_a_slot_count_that_is_no_number_is_refused(self) -> None:
        for value in ("0", "x", "08", "010", ""):
            result = subprocess.run(
                [SCRIPT, "true"],
                env={**self.env, "MAITY_RUN_SLOTS": value},
                capture_output=True,
                text=True,
                timeout=30,  # 08 once passed the check and then waited forever
            )
            if value == "":
                self.assertEqual(result.returncode, 0, "empty means the default")
                continue
            self.assertEqual(result.returncode, 2, value)
            self.assertIn("MAITY_RUN_SLOTS", result.stderr)

    # The log: a start and an end line per run that got a slot.

    def log_lines(self, count: int) -> list[list[str]]:
        """The log's lines split at tabs, once it holds `count` (the end lines come from a
        watcher that checks every second)."""
        log = self.tmp / "slots" / "log"
        deadline = time.monotonic() + 30
        while True:
            lines = log.read_text().splitlines() if log.exists() else []
            if len(lines) >= count:
                return [line.split("\t") for line in lines]
            self.assertLess(time.monotonic(), deadline, f"the log has {lines}")
            time.sleep(0.1)

    def test_a_run_logs_its_start_and_its_end(self) -> None:
        env = {**self.env, "MAITY_RUN_NAME": "coder#ab\tcd"}
        result = subprocess.run(
            [SCRIPT, "sh", "-c", "sleep 1.2; echo $$"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        pid = result.stdout.strip()  # exec keeps the pid: the shell's is the run's
        start, end = self.log_lines(2)
        self.assertEqual(len(start), 7, start)
        self.assertEqual(start[0], "start")
        self.assertRegex(start[1], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(start[2:4], ["slot=0", f"pid={pid}"])
        # bash's SECONDS counts whole seconds of the clock: a run that did not wait shows 0 or 1.
        self.assertRegex(start[4], r"^wait=[01]$")
        self.assertEqual(start[5:], ["who=coder#ab cd", "cmd=sh -c"])
        self.assertEqual(len(end), 5, end)
        self.assertEqual(end[0], "end")
        self.assertRegex(end[1], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(end[2:4], ["slot=0", f"pid={pid}"])
        self.assertRegex(end[4], r"^secs=[1-9]\d*$")
        self.assertEqual((self.tmp / "slots" / "log").stat().st_mode & 0o777, 0o640)

    def test_tabs_and_line_breaks_in_who_and_cmd_become_spaces(self) -> None:
        env = {**self.env, "MAITY_RUN_NAME": "coder#a\tb\nc\rd"}
        subprocess.run([SCRIPT, "true", "x\ty\nz\rw"], env=env, check=True, timeout=30)
        lines = self.log_lines(2)
        self.assertEqual(len(lines), 2, lines)  # a start and an end line, nothing broken off
        start, end = lines
        self.assertEqual(len(start), 7, start)
        self.assertEqual(start[0], "start")
        self.assertEqual(start[5:], ["who=coder#a b c d", "cmd=true x y z w"])
        self.assertEqual(end[0], "end")
        text = (self.tmp / "slots" / "log").read_text()
        self.assertEqual(text.count("\n"), 2, text)
        self.assertNotIn("\r", text)

    def test_only_the_program_and_its_first_argument_are_kept(self) -> None:
        subprocess.run(
            [SCRIPT, "sh", "-c", "exit 0", "later", "arguments"], env=self.env, check=True, timeout=30
        )
        self.assertEqual(self.log_lines(1)[0][6], "cmd=sh -c")
        who = (self.tmp / "slots" / "slot0.who").read_text()
        self.assertTrue(who.endswith(": sh -c\n"), who)
        self.assertNotIn("later", (self.tmp / "slots" / "log").read_text() + who)
        subprocess.run([SCRIPT, "true"], env=self.env, check=True, timeout=30)
        starts = [line for line in self.log_lines(3) if line[0] == "start"]
        self.assertEqual(starts[1][6], "cmd=true")

    def test_who_defaults_to_the_user_and_a_long_command_is_cut(self) -> None:
        env = {k: v for k, v in self.env.items() if k != "MAITY_RUN_NAME"}
        env["USER"] = "agents"
        subprocess.run([SCRIPT, "true", "a" * 300], env=env, check=True, timeout=30)
        start = self.log_lines(1)[0]
        self.assertEqual(start[5], "who=agents")
        self.assertEqual(start[6], "cmd=" + ("true " + "a" * 300)[:200])  # a long first one

    def test_a_run_that_waited_logs_the_wait(self) -> None:
        gate = self.tmp / "gate"
        ready = self.tmp / "ready"
        env = {**self.env, "MAITY_RUN_SLOTS": "1"}
        holder = subprocess.Popen(
            [SCRIPT, "sh", "-c", f"touch {ready}; until [ -f {gate} ]; do sleep 0.05; done"],
            env=env,
        )
        self.addCleanup(holder.wait, 30)
        self.addCleanup(gate.touch)
        self.wait_for(ready)
        second = subprocess.Popen([SCRIPT, "true"], env=env, stderr=subprocess.DEVNULL)
        time.sleep(2.5)
        gate.touch()
        self.assertEqual(second.wait(timeout=30), 0)
        starts = [line for line in self.log_lines(3) if line[0] == "start"]
        self.assertEqual(starts[0][3], f"pid={holder.pid}")
        self.assertRegex(starts[0][4], r"^wait=[01]$")
        self.assertEqual(starts[1][3], f"pid={second.pid}")
        self.assertRegex(starts[1][4], r"^wait=[2-9]$")

    def test_runs_at_once_write_whole_lines(self) -> None:
        env = {**self.env, "MAITY_RUN_SLOTS": "8"}
        runs = [subprocess.Popen([SCRIPT, "true", str(n) * 190], env=env) for n in range(8)]
        for run in runs:
            self.assertEqual(run.wait(timeout=30), 0)
        lines = self.log_lines(16)
        self.assertEqual(len(lines), 16)
        for line in lines:
            self.assertIn(line[0], ("start", "end"))
            self.assertEqual(len(line), 7 if line[0] == "start" else 5, line)
        self.assertEqual(
            sorted(line[3] for line in lines if line[0] == "start"),
            sorted(line[3] for line in lines if line[0] == "end"),
        )

    def test_a_log_that_cannot_be_written_does_not_stop_the_run(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        (slots / "log").mkdir()  # not a file: every append fails, whoever runs the test
        result = subprocess.run(
            [SCRIPT, "sh", "-c", "exit 3"], env=self.env, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stderr, "")

    @unittest.skipIf(os.geteuid() == 0, "root writes a read-only file")
    def test_a_log_file_that_is_read_only_does_not_stop_the_run(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        (slots / "log").touch()
        (slots / "log").chmod(0o400)  # a regular file: the append is tried and fails
        marker = self.tmp / "ran"
        result = subprocess.run(
            [SCRIPT, "sh", "-c", f"touch {marker}; exit 3"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 3)
        self.assertTrue(marker.exists(), "the command never ran")
        self.assertEqual(result.stderr, "")

    def test_a_log_that_is_a_fifo_does_not_hold_the_run(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        os.mkfifo(slots / "log")  # no reader: opening it for appending would block
        marker = self.tmp / "ran"
        result = subprocess.run(
            [SCRIPT, "sh", "-c", f"touch {marker}; exit 3"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 3)
        self.assertTrue(marker.exists(), "the command never ran")
        self.assertEqual(result.stderr, "")

    # A slot directory the run may not write (a sandboxed agent session): the command runs
    # without a slot and without a log line, and says so.

    def run_without_a_slot(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        marker = self.tmp / "ran"
        result = subprocess.run(
            [SCRIPT, "sh", "-c", f'touch {marker}; echo "slot=$MAITY_RUN_SLOT"; exit 3'],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 3)
        self.assertTrue(marker.exists(), "the command never ran")
        self.assertEqual(result.stdout, "slot=none\n")
        self.assertIn("running without a slot and without a log line", result.stderr)
        self.assertIn("MAITY_RUN_SLOTS_DIR", result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        return result

    @unittest.skipIf(os.geteuid() == 0, "root writes a read-only directory")
    def test_a_slot_directory_that_cannot_be_created_runs_the_command_without_a_slot(
        self,
    ) -> None:
        locked = self.tmp / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        slots = locked / "slots"
        result = self.run_without_a_slot({**self.env, "MAITY_RUN_SLOTS_DIR": str(slots)})
        self.assertIn(str(slots), result.stderr)
        self.assertFalse(slots.exists())

    @unittest.skipIf(os.geteuid() == 0, "root writes a read-only directory")
    def test_a_slot_directory_that_is_read_only_runs_the_command_without_a_slot(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        slots.chmod(0o500)  # mkdir -p succeeds, opening the slot file fails
        self.addCleanup(slots.chmod, 0o700)
        result = self.run_without_a_slot(self.env)
        self.assertIn(str(slots / "slot0"), result.stderr)
        self.assertEqual(list(slots.iterdir()), [])

    def test_a_slot_file_that_cannot_be_opened_runs_the_command_without_a_slot(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        (slots / "slot0").mkdir()  # not a file: the open fails, whoever runs the test
        env = {**self.env, "MAITY_RUN_SLOTS": "1"}
        result = self.run_without_a_slot(env)
        self.assertIn(str(slots / "slot0"), result.stderr)
        self.assertEqual(sorted(p.name for p in slots.iterdir()), ["slot0"])

    @unittest.skipIf(os.geteuid() == 0, "root writes a read-only directory")
    def test_a_holder_name_that_cannot_be_written_does_not_stop_the_run(self) -> None:
        slots = self.tmp / "slots"
        slots.mkdir()
        (slots / "slot0").touch()  # left from before; the directory then turned read-only
        slots.chmod(0o500)
        self.addCleanup(slots.chmod, 0o700)
        result = subprocess.run(
            [SCRIPT, "sh", "-c", 'echo "slot=$MAITY_RUN_SLOT"; exit 3'],
            env={**self.env, "MAITY_RUN_SLOTS": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "slot=0\n")
        self.assertEqual(result.stderr, "")

    def watcher_ids(self, pid: int) -> tuple[int, int]:
        """The process group and session of the watcher for the run `pid`, found in /proc."""
        deadline = time.monotonic() + 30
        while True:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    args = (entry / "cmdline").read_bytes().split(b"\0")[:-1]
                    stat = (entry / "stat").read_text()
                except OSError:
                    continue
                if b"run_slot-watcher" in args and args[-1] == str(pid).encode():
                    # pid (comm) state ppid pgrp session ...: comm may hold spaces, so split
                    # after its closing parenthesis.
                    fields = stat[stat.rindex(")") + 2 :].split()
                    return int(fields[2]), int(fields[3])
            self.assertLess(time.monotonic(), deadline, "no watcher found")
            time.sleep(0.05)

    def cancel_group_and_expect_the_end(
        self, sig: signal.Signals, env: dict[str, str], in_own_session: bool
    ) -> None:
        """Starts a run in a session of its own, as a supervisor would (the run leads its
        process group), checks where its watcher runs, sends `sig` to the run's group and
        expects the end line all the same."""
        ready = self.tmp / "ready"
        run = subprocess.Popen(
            [SCRIPT, "sh", "-c", f"touch {ready}; sleep 60"], env=env, start_new_session=True
        )
        try:
            self.wait_for(ready)
            pgid, sid = self.watcher_ids(run.pid)
            if in_own_session:
                self.assertNotEqual(pgid, run.pid, "the watcher is in the run's process group")
                self.assertNotEqual(sid, run.pid, "the watcher is in the run's session")
            else:
                self.assertEqual(pgid, run.pid, "the test means a watcher in the run's group")
            os.killpg(run.pid, sig)
            self.assertEqual(run.wait(timeout=30), -sig)
            start, end = self.log_lines(2)  # waits up to 30 s for the watcher's end line
            self.assertEqual(start[0], "start")
            self.assertEqual(start[3], f"pid={run.pid}")
            self.assertEqual(end[0], "end")
            self.assertEqual(end[2:4], ["slot=0", f"pid={run.pid}"])
        finally:
            try:
                os.killpg(run.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                run.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass

    @unittest.skipIf(shutil.which("setsid") is None, "needs util-linux setsid")
    @unittest.skipUnless(Path("/proc/self/stat").exists(), "needs /proc")
    def test_a_run_cancelled_with_its_process_group_still_logs_its_end(self) -> None:
        self.cancel_group_and_expect_the_end(signal.SIGTERM, self.env, in_own_session=True)

    @unittest.skipIf(shutil.which("setsid") is None, "needs util-linux setsid")
    @unittest.skipUnless(Path("/proc/self/stat").exists(), "needs /proc")
    def test_the_watcher_s_own_session_keeps_it_from_a_signal_it_does_not_ignore(self) -> None:
        # USR1 is not ignored: only the session of its own keeps the watcher alive.
        self.cancel_group_and_expect_the_end(signal.SIGUSR1, self.env, in_own_session=True)

    @unittest.skipUnless(Path("/proc/self/stat").exists(), "needs /proc")
    def test_without_setsid_the_ignored_term_keeps_the_watcher(self) -> None:
        # A PATH with only the tools the run needs, setsid not among them: the watcher stays in
        # the run's process group, and only its ignoring TERM keeps it alive.
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for tool in ("bash", "sh", "flock", "mkdir", "date", "sleep", "touch", "cat"):
            found = shutil.which(tool)
            self.assertIsNotNone(found, tool)
            (bin_dir / tool).symlink_to(found)
        env = {**self.env, "PATH": str(bin_dir)}
        self.cancel_group_and_expect_the_end(signal.SIGTERM, env, in_own_session=False)

    def test_the_watcher_holds_neither_the_slot_nor_the_output(self) -> None:
        env = {**self.env, "MAITY_RUN_SLOTS": "1"}
        began = time.monotonic()
        for _ in range(3):  # with fd 7 in the watcher, the next run would wait for it
            out = subprocess.run(
                [SCRIPT, "echo", "hi"], env=env, capture_output=True, text=True, timeout=30
            )
            self.assertEqual(out.stdout, "hi\n")
            self.assertNotIn("taken", out.stderr)
        self.assertLess(time.monotonic() - began, 3, "a run waited for the last one's watcher")


if __name__ == "__main__":
    unittest.main()
