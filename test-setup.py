#!/usr/bin/env python3
"""Offline regression check: setup never resets existing policy or credentials."""
from pathlib import Path
import runpy
import tempfile

ROOT = Path(__file__).resolve().parent
setup = runpy.run_path(str(ROOT / "setup"))
policy = runpy.run_path(str(ROOT / "dns-policy"))

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    runtime = root / "runtime"
    template = ROOT / "config/dnsdist.conf"
    setup["initialize"](runtime, template)
    original_key = (runtime / "console.key").read_bytes()
    entries = {"192.0.2.1": None}
    state, generation = policy["serialize"](entries)
    (runtime / "policy.state").write_bytes(state)
    (runtime / "dnsdist.conf").write_text("-- existing custom configuration\n")
    setup["initialize"](runtime, template)
    assert (runtime / "console.key").read_bytes() == original_key
    assert (runtime / "policy.state").read_bytes() == state
    assert policy["parse_state"](state) == (entries, generation, False)
    assert (runtime / "dnsdist.conf").read_text() == "-- existing custom configuration\n"
    assert runtime.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in runtime.iterdir())
    bin_dir = root / "bin"
    setup["install_link"](bin_dir)
    setup["install_link"](bin_dir)
    link = bin_dir / "dns-policy"
    assert link.resolve() == ROOT / "dns-policy"
    link.unlink()
    link.write_text("user-owned script\n")
    try:
        setup["install_link"](bin_dir)
    except RuntimeError:
        pass
    else:
        raise AssertionError("setup overwrote an existing executable")
    assert link.read_text() == "user-owned script\n"
    link.unlink()
    # Adoption uses a directory symlink; initialization must preserve its contents too.
    adopted = root / "adopted"
    adopted.symlink_to(runtime, target_is_directory=True)
    setup["initialize"](adopted, template)
    assert (adopted / "policy.state").read_bytes() == state
    assert (adopted / "console.key").read_bytes() == original_key

print("setup regression checks passed")
