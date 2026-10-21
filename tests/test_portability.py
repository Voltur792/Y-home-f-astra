from src import platform_support as paths
from src import voice_commands


def test_mac_command_file_and_integration_use_mac_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("YSH_COMMANDS_FILE", raising=False)
    monkeypatch.delenv("ASTRA_CONFIG_DIR", raising=False)
    monkeypatch.delenv("SPT_INTEGRATION_DIR", raising=False)
    assert voice_commands.commands_path() == tmp_path / "Library/Application Support/com.astra.astra/commands.json"
    assert paths.integration_dir() == tmp_path / "Library/Application Support/sleep-pause-timer/integrations"


def test_wayland_window_chooses_qt_before_gui_load(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    assert paths.webview_gui() == "qt"
    assert paths.os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_mac_writer_waits_for_host_exit_without_proc_filesystem(monkeypatch):
    monkeypatch.setattr(voice_commands.sys, "platform", "darwin")
    calls = []
    def probe(pid, signal):
        calls.append((pid, signal))
        if len(calls) == 3:
            raise ProcessLookupError()
    monkeypatch.setattr(voice_commands.os, "kill", probe)
    monkeypatch.setattr(voice_commands.time, "sleep", lambda _: None)
    voice_commands.wait_host(12345)
    assert calls == [(12345, 0)] * 3
