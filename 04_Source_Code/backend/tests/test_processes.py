import ctypes
import os
import subprocess
import sys

import pytest

from app.services.processes import run_bounded


@pytest.mark.skipif(os.name != "nt", reason="Windows venv launchers have a child process")
def test_timeout_terminates_nested_python_child(tmp_path):
    pidfile = tmp_path / "child.pid"
    code = (
        "import sys,subprocess,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
        "creationflags=subprocess.CREATE_NO_WINDOW); "
        "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", code, str(pidfile)], timeout=2)
    assert pidfile.is_file()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, int(pidfile.read_text()))
    if handle:
        try:
            code = ctypes.c_ulong()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            assert code.value != 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
