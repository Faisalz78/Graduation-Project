"""Bounded local helpers, including Windows virtualenv launcher process trees."""

import os
import subprocess


def run_bounded(command, timeout):
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Killing only a venv launcher on Windows can leave its Python child alive.
            try:
                if os.name == "nt" and process.poll() is None:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=10,
                        check=False,
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
            raise
