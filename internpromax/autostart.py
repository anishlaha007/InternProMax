"""Start InternProMax automatically when you log in to your computer.

macOS: a launchd LaunchAgent. Windows: a shortcut in your Startup folder (runs without a window).
Linux: a systemd user service, or an XDG autostart entry when systemd isn't available.
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import config

LABEL = "com.internpromax.server"
SERVICE = "internpromax.service"
RUN = subprocess.run  # replaced in tests


def _system() -> str:
    return platform.system()  # "Darwin", "Windows", "Linux"


def _python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":
        windowless = exe.with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return str(exe)


def log_path() -> Path:
    path = config.ensure_data_dir() / "logs" / "server.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def pid_path() -> Path:
    return config.DATA_DIR / "server.pid"


def server_args() -> list[str]:
    return [_python(), "-m", "internpromax", "serve", "--no-browser", "--log-file", str(log_path())]


def _env() -> dict[str, str]:
    # Carry over where your data lives and the port; never copy secrets into startup files.
    env = {"PYTHONUNBUFFERED": "1"}
    for key in ("IPM_DATA_DIR", "IPM_PORT"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def dashboard_url() -> str:
    return f"http://127.0.0.1:{config.PORT}"


def running(port: int | None = None, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port or config.PORT}/api/health", timeout=timeout) as res:
            return json.load(res).get("app") == "internpromax"
    except (OSError, ValueError):
        return False


def _run(cmd: list[str]) -> bool:
    try:
        return RUN(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _spawn() -> None:
    """Start the server now, detached from this terminal."""
    if running():
        return
    kwargs: dict = {"cwd": str(config.ROOT), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "env": {**os.environ, **_env()}}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(server_args(), **kwargs)


def _wait(seconds: float = 20) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if running():
            return True
        time.sleep(0.5)
    return False


def _stop_running_server() -> None:
    try:
        pid = int(pid_path().read_text().strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


# ---------------------------------------------------------------- macOS

def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _mac_install(notes: list[str]) -> None:
    path = _mac_plist()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": server_args(),
            "WorkingDirectory": str(config.ROOT),
            "EnvironmentVariables": _env(),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},  # restart after a crash, not after a clean exit
            "ProcessType": "Background",
        }, fh)
    domain = f"gui/{os.getuid()}"
    _run(["launchctl", "bootout", f"{domain}/{LABEL}"])
    if not _run(["launchctl", "bootstrap", domain, str(path)]):
        _run(["launchctl", "load", "-w", str(path)])
    protected = [Path.home() / d for d in ("Desktop", "Documents", "Downloads")] + [Path.home() / "Library" / "Mobile Documents"]
    if any(str(config.ROOT).startswith(str(p)) for p in protected):
        notes.append("Heads up: macOS can block background apps from Desktop, Documents and Downloads. If it doesn't "
                     f"start after a restart, move the InternProMax folder to {Path.home()} and run this again.")


def _mac_uninstall() -> None:
    _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
    _run(["launchctl", "unload", "-w", str(_mac_plist())])
    _mac_plist().unlink(missing_ok=True)


# ---------------------------------------------------------------- Windows

def _win_startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _win_shortcut() -> Path:
    return _win_startup_dir() / "InternProMax.lnk"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _win_arguments() -> str:
    return subprocess.list2cmdline(server_args()[1:])


def _win_install(notes: list[str]) -> None:
    lnk = _win_shortcut()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(lnk))});"
        f"$s.TargetPath={_ps_quote(_python())};$s.Arguments={_ps_quote(_win_arguments())};"
        f"$s.WorkingDirectory={_ps_quote(str(config.ROOT))};$s.WindowStyle=7;$s.Description='InternProMax';$s.Save()"
    )
    if not _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]):
        raise RuntimeError("Couldn't create the Startup shortcut (PowerShell failed).")
    _spawn()


def _win_uninstall() -> None:
    _win_shortcut().unlink(missing_ok=True)
    _stop_running_server()


# ---------------------------------------------------------------- Linux

def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _linux_unit() -> Path:
    return _config_home() / "systemd" / "user" / SERVICE


def _linux_desktop() -> Path:
    return _config_home() / "autostart" / "internpromax.desktop"


def _systemd_quote(arg: str) -> str:
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"' if any(c in arg for c in ' "\\') else arg


def _linux_install(notes: list[str]) -> None:
    unit = _linux_unit()
    unit.parent.mkdir(parents=True, exist_ok=True)
    env_lines = "".join(f'Environment="{k}={v}"\n' for k, v in _env().items())
    unit.write_text(
        "[Unit]\nDescription=InternProMax (internship finder, resume tailor and tracker)\n\n"
        f"[Service]\nWorkingDirectory={config.ROOT}\n{env_lines}"
        f"ExecStart={' '.join(_systemd_quote(a) for a in server_args())}\n"
        "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
    )
    if _run(["systemctl", "--user", "daemon-reload"]) and _run(["systemctl", "--user", "enable", "--now", SERVICE]):
        _linux_desktop().unlink(missing_ok=True)
        return
    # No systemd user session: fall back to the desktop's autostart folder.
    unit.unlink(missing_ok=True)
    desktop = _linux_desktop()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' for a in server_args())
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=InternProMax\nComment=Internship finder, resume tailor and tracker\n"
        f"Exec={exec_line}\nPath={config.ROOT}\nTerminal=false\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n"
    )
    notes.append("Using your desktop's autostart folder (no systemd user session found).")
    _spawn()


def _linux_uninstall() -> None:
    if _linux_unit().exists():
        _run(["systemctl", "--user", "disable", "--now", SERVICE])
        _linux_unit().unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
    _linux_desktop().unlink(missing_ok=True)
    _stop_running_server()


# ---------------------------------------------------------------- public

def install(wait: bool = True) -> list[str]:
    notes: list[str] = []
    system = _system()
    if system == "Darwin":
        _mac_install(notes)
    elif system == "Windows":
        _win_install(notes)
    elif system == "Linux":
        _linux_install(notes)
    else:
        raise RuntimeError(f"Automatic start isn't supported on {system}.")
    if wait:
        if _wait():
            notes.insert(0, f"InternProMax is running at {dashboard_url()} and will start every time you log in.")
        else:
            notes.insert(0, f"Set to start when you log in, but it isn't answering yet. Check {log_path()}.")
    return notes


def uninstall() -> list[str]:
    system = _system()
    if system == "Darwin":
        _mac_uninstall()
    elif system == "Windows":
        _win_uninstall()
    elif system == "Linux":
        _linux_uninstall()
    return ["InternProMax won't start automatically anymore (and the background copy was stopped)."]


def status() -> dict:
    system = _system()
    entry = {"Darwin": _mac_plist, "Windows": _win_shortcut}.get(system)
    if entry:
        files = [entry()]
    else:
        files = [_linux_unit(), _linux_desktop()]
    installed = [str(f) for f in files if f.exists()]
    return {"installed": bool(installed), "entries": installed, "running": running(), "url": dashboard_url(), "log": str(log_path())}
