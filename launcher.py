"""Minimal launcher wrapper used by tests.

This module provides a tiny abstraction over the existing shell-based
launchers. The real project uses shell scripts under .specify/scripts/; for
testing we keep a small Python-level API that can be mocked.
"""
from pathlib import Path
import shutil
import subprocess
from typing import Optional, Tuple
import os


def _find_jailer() -> Optional[Path]:
    p = shutil.which("jailer")
    if p:
        return Path(p)
    return None


def start_launcher(vm_id: str, config_path: str, results_root: str, use_jailer: bool = True, extra_args: list | None = None) -> Tuple[subprocess.Popen, Path]:
    """Start the launcher process and capture logs into results directory.

    Returns (process, results_dir).
    """
    jailer_path = _find_jailer() if use_jailer else None
    if jailer_path:
        cmd = [str(jailer_path), "--vm-id", vm_id, "--config", config_path]
    else:
        dev_launcher = Path(".specify/scripts/launch_firecracker_without_jailer.sh")
        if dev_launcher.exists():
            cmd = [str(dev_launcher), vm_id, config_path]
            if extra_args:
                cmd += extra_args
        else:
            cmd = ["/bin/sleep", "60"]

    results_dir = Path(results_root) / vm_id
    results_dir.mkdir(parents=True, exist_ok=True)

    out_path = results_dir / "launcher.out"
    err_path = results_dir / "launcher.err"

    out_f = open(out_path, 'w')
    err_f = open(err_path, 'w')

    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, text=True)

    # write pid file
    pid_path = results_dir / "launcher.pid"
    pid_path.write_text(str(proc.pid))

    return proc, results_dir


def stop_launcher(proc: subprocess.Popen, results_dir: str) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    # best-effort cleanup of pid file
    try:
        p = Path(results_dir) / "launcher.pid"
        if p.exists():
            p.unlink()
    except Exception:
        pass

