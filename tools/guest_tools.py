"""Helpers to prepare guest artifacts: guest.tar.gz and init overlay image.

create_guest_tar collects specified files/dirs into a tar.gz for the guest.
create_init_overlay wraps the existing shell script; supports dry_run for tests.
"""
from pathlib import Path
import tarfile
import subprocess
from typing import Iterable


def create_guest_tar(vm_id: str, src_paths: Iterable[Path], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, 'w:gz') as tar:
        for p in src_paths:
            if p.exists():
                tar.add(p, arcname=p.name)
    return out_path


def create_init_overlay(vm_id: str, out_img: Path, script_path: Path = Path('.specify/scripts/create_init_overlay.sh'), dry_run: bool = False) -> Path:
    out_img.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        # create a small placeholder file to simulate an image
        out_img.write_bytes(b"DUMMY-INIT-IMG")
        return out_img

    if not script_path.exists():
        raise FileNotFoundError(f"init overlay script not found: {script_path}")

    subprocess.run([str(script_path), vm_id, str(out_img)], check=True)
    return out_img
