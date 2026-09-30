"""Start-on-login setup for macOS, Windows and Linux (OS commands are recorded, not run)."""

import plistlib
import subprocess

import pytest

from internpromax import autostart, config


@pytest.fixture
def fake_os(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    calls = []
    results = {}

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, results.get(cmd[0], 0), "", "")

    monkeypatch.setattr(autostart, "RUN", run)
    spawned = []
    monkeypatch.setattr(autostart, "_spawn", lambda: spawned.append(True))
    monkeypatch.setattr(autostart, "running", lambda *a, **k: True)
    monkeypatch.setattr(autostart.os, "getuid", lambda: 501, raising=False)
    return {"home": home, "calls": calls, "results": results, "spawned": spawned, "set": lambda s: monkeypatch.setattr(autostart, "_system", lambda: s)}


def test_macos_launch_agent(fake_os):
    fake_os["set"]("Darwin")
    notes = autostart.install()
    plist_path = fake_os["home"] / "Library" / "LaunchAgents" / "com.internpromax.server.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["ProgramArguments"][1:5] == ["-m", "internpromax", "serve", "--no-browser"]
    assert "--log-file" in plist["ProgramArguments"]
    assert plist["WorkingDirectory"] == str(config.ROOT) and plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert ["launchctl", "bootstrap", "gui/501", str(plist_path)] in fake_os["calls"]
    assert "running at http://127.0.0.1" in notes[0]
    assert autostart.status()["installed"]
    autostart.uninstall()
    assert not plist_path.exists() and ["launchctl", "bootout", "gui/501/com.internpromax.server"] in fake_os["calls"]


def test_windows_startup_shortcut(fake_os):
    fake_os["set"]("Windows")
    autostart.install()
    ps = next(c for c in fake_os["calls"] if c[0] == "powershell")
    script = ps[-1]
    assert "Startup\\InternProMax.lnk" in script.replace("/", "\\") and "CreateShortcut" in script
    assert "-m internpromax serve --no-browser --log-file" in script and "WindowStyle=7" in script
    assert fake_os["spawned"]  # started right away, not just at next login


def test_windows_reports_powershell_failure(fake_os):
    fake_os["set"]("Windows")
    fake_os["results"]["powershell"] = 1
    with pytest.raises(RuntimeError):
        autostart.install()


def test_linux_systemd_user_service(fake_os):
    fake_os["set"]("Linux")
    autostart.install()
    unit = (fake_os["home"] / ".config" / "systemd" / "user" / "internpromax.service").read_text()
    assert "ExecStart=" in unit and "-m internpromax serve --no-browser" in unit and "Restart=on-failure" in unit
    assert f"WorkingDirectory={config.ROOT}" in unit and "WantedBy=default.target" in unit
    assert ["systemctl", "--user", "enable", "--now", "internpromax.service"] in fake_os["calls"]
    autostart.uninstall()
    assert ["systemctl", "--user", "disable", "--now", "internpromax.service"] in fake_os["calls"]
    assert not (fake_os["home"] / ".config" / "systemd" / "user" / "internpromax.service").exists()


def test_linux_falls_back_to_desktop_autostart(fake_os):
    fake_os["set"]("Linux")
    fake_os["results"]["systemctl"] = 1  # no systemd user session
    notes = autostart.install()
    desktop = (fake_os["home"] / ".config" / "autostart" / "internpromax.desktop").read_text()
    assert "Exec=" in desktop and '"-m" "internpromax" "serve"' in desktop and f"Path={config.ROOT}" in desktop
    assert not (fake_os["home"] / ".config" / "systemd" / "user" / "internpromax.service").exists()
    assert fake_os["spawned"] and any("autostart folder" in n for n in notes)
