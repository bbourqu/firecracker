import os
from pathlib import Path

import subprocess

import launcher


class DummyProc:
    def __init__(self, pid=12345):
        self.pid = pid
        self._poll = None

    def poll(self):
        return self._poll

    def terminate(self):
        self._poll = 0

    def wait(self, timeout=None):
        self._poll = 0

    def kill(self):
        self._poll = -9


def test_start_launcher_writes_pid_and_logs(tmp_path, monkeypatch):
    results_root = str(tmp_path / "results")

    def fake_popen(cmd, stdout, stderr, text=True):
        # simulate writing to stdout/stderr files
        stdout.write("out\n")
        stderr.write("err\n")
        return DummyProc(pid=9999)

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)

    proc, results_dir = launcher.start_launcher("vid1", "cfg", results_root, use_jailer=False)

    assert (results_dir / "launcher.out").exists()
    assert (results_dir / "launcher.err").exists()
    assert (results_dir / "launcher.pid").read_text() == "9999"

    # stop_launcher should not raise
    launcher.stop_launcher(proc, results_dir)
