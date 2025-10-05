from pathlib import Path
from tools.guest_tools import create_guest_tar, create_init_overlay


def test_create_guest_tar(tmp_path):
    p1 = tmp_path / "a.txt"
    p1.write_text("hello")
    out = tmp_path / "guest.tar.gz"
    t = create_guest_tar("vmx", [p1], out)
    assert t.exists()


def test_create_init_overlay_dry_run(tmp_path):
    out = tmp_path / "init.img"
    res = create_init_overlay("vmx", out, dry_run=True)
    assert res.exists()
    assert res.read_bytes() == b"DUMMY-INIT-IMG"
