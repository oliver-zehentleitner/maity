"""tools/run_slot.sh: at most MAITY_RUN_SLOTS commands at a time; a further one waits, says so
and starts once a slot is free; a command inside a slot keeps it."""

from __future__ import annotations

import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
