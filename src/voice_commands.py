"""Exact Astra text triggers, staged until the host closes.

The current daemon forbids CommandService for plugin sessions. Never edit its
in-memory command store while it is running: a detached writer waits for the
host's exit and then merges only this feature's commands into commands.json.
"""

import ctypes
import base64
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TAG = "yandex-smart-home-direct-voice-v1"
PREFIX = "plugin__yandex_smart_home__voice_"


def commands_path():
    override = os.environ.get("YSH_COMMANDS_FILE")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ["APPDATA"]) / "astra/astra/config/commands.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "astra/commands.json"


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def normalize_phrase(phrase):
    value = " ".join(phrase.casefold().replace("ё", "е").split()).rstrip(".!?").strip()
    return re.sub(r"^астра(?:,\s*|\s+)", "", value)


def trigger_phrases(phrases):
    """Keep exact matching, allowing the spoken address and STT punctuation."""
    result = []
    for phrase in phrases:
        base = re.sub(r"^астра(?:,\s*|\s+)", "", phrase.strip(), flags=re.IGNORECASE).rstrip(".!?").strip()
        for spelling in dict.fromkeys((base, base.replace("ё", "е").replace("Ё", "Е"))):
            for prefix in ("", "Астра ", "Астра, "):
                for end in ("", ".", "!", "?"):
                    value = prefix + spelling + end
                    if value not in result:
                        result.append(value)
    return result


def is_owned(command):
    return TAG in (command.get("tags") or []) and any(
        a.get("handler_id", "").startswith(PREFIX) for a in command.get("actions", [])
    )


def validate_phrases(phrases, entries, commands, editing_id=""):
    if not isinstance(phrases, list) or not 1 <= len(phrases) <= 20:
        raise ValueError("Добавьте от 1 до 20 фраз, каждую с новой строки")
    clean, seen = [], set()
    for phrase in phrases:
        if not isinstance(phrase, str) or not 2 <= len(phrase.strip()) <= 160:
            raise ValueError("Каждая фраза должна содержать от 2 до 160 символов")
        phrase = " ".join(phrase.strip().split())
        key = normalize_phrase(phrase)
        if key in seen:
            raise ValueError("Одна и та же фраза указана несколько раз")
        seen.add(key)
        clean.append(phrase)
    for entry in entries:
        if entry["id"] != editing_id and seen.intersection(map(normalize_phrase, entry["phrases"])):
            raise ValueError("Эта фраза уже используется другой командой умного дома")
    for command in commands:
        if is_owned(command) or not command.get("enabled", True):
            continue
        for trigger in command.get("triggers", []):
            if trigger.get("type") != "text":
                continue
            for phrase in trigger.get("phrases", []):
                key = normalize_phrase(phrase)
                if any(key == wanted or (not trigger.get("exact_match", False) and key in wanted)
                       for wanted in seen):
                    raise ValueError("Фраза пересекается с командой Astra «" + command.get("name", "Без названия") + "»")
    return clean


def validate_target(target, info):
    if not isinstance(target, dict):
        raise ValueError("Выберите устройство или сценарий")
    kind, ident = target.get("kind"), target.get("target_id")
    collection = "scenarios" if kind == "scenario" else "devices"
    item = next((d for d in info.get(collection, []) if d.get("id") == ident), None)
    if kind not in ("device", "scenario") or item is None:
        raise ValueError("Устройство или сценарий больше не доступны. Обновите список")
    result = {"kind": kind, "target_id": ident, "target_name": item.get("name") or "Без названия"}
    if kind == "scenario":
        return result
    cap_type, instance, value = target.get("capability_type"), target.get("capability_instance"), target.get("value")
    relative = target.get("relative") is True
    valid = False
    for cap in item.get("capabilities", []):
        if cap.get("type") != cap_type:
            continue
        p = cap.get("parameters") or {}
        actual = p.get("instance") or (cap.get("state") or {}).get("instance")
        if cap_type == "devices.capabilities.on_off":
            valid = instance == "on" and type(value) is bool and not relative
        elif cap_type == "devices.capabilities.toggle":
            valid = instance == actual and type(value) is bool and not relative
        elif cap_type == "devices.capabilities.mode":
            valid = instance == actual and value in [m.get("value") for m in p.get("modes", [])] and not relative
        elif cap_type == "devices.capabilities.range" or (
            cap_type == "devices.capabilities.color_setting" and instance == "temperature_k" and p.get("temperature_k")
        ):
            bounds = p.get("temperature_k") if instance == "temperature_k" else p.get("range", {})
            bounds = bounds or {}
            valid = (instance == ("temperature_k" if cap_type.endswith("color_setting") else actual)
                     and type(value) in (int, float) and math.isfinite(value)
                     and relative == (p.get("random_access") is False))
            if valid:
                lo, hi = bounds.get("min", 0), bounds.get("max", 100)
                step = bounds.get("precision", 1) or 1
                valid = (0 < abs(value) <= hi - lo if relative else lo <= value <= hi)
                valid = valid and math.isclose((value - (0 if relative else lo)) / step,
                                              round((value - (0 if relative else lo)) / step), abs_tol=1e-7)
        elif cap_type == "devices.capabilities.color_setting":
            if instance == "scene":
                valid = value in [s.get("id") for s in (p.get("color_scene") or {}).get("scenes", [])]
            elif instance == "rgb" and p.get("color_model") == "rgb":
                valid = type(value) is int and 0 <= value <= 0xffffff
            elif instance == "hsv" and p.get("color_model") == "hsv" and isinstance(value, dict):
                valid = all(type(value.get(k)) in (int, float) and math.isfinite(value[k]) and 0 <= value[k] <= limit
                            for k, limit in (("h", 360), ("s", 100), ("v", 100)))
            valid = valid and not relative
        if valid:
            break
    if not valid:
        raise ValueError("Выбранное действие или значение не поддерживается устройством")
    result.update(capability_type=cap_type, capability_instance=instance, value=value, relative=relative)
    return result


def as_command(entry):
    ident = entry["id"].replace("-", "")
    handler = PREFIX + ident
    trigger_id, action_id = "ysh_" + ident + "_trigger", "ysh_" + ident + "_action"
    edge_id = "ysh_" + ident + "_edge"
    now = datetime.now(timezone.utc).isoformat()
    config = {"exact_match": True, "case_sensitive": False, "phrases": trigger_phrases(entry["phrases"])}
    return {
        "id": entry["id"], "name": "Умный дом — " + entry["name"], "description": "Прямое действие умного дома без ИИ.",
        "enabled": entry["enabled"], "tags": [TAG], "created_at": entry.get("created_at", now), "updated_at": now,
        "slash_enabled": False, "slash_description": "", "execution": {}, "editor_mode": "graph",
        "triggers": [{"type": "text", **config}],
        "actions": [{"type": "dynamic", "handler_id": handler, "params": {}}],
        "workflow": {"nodes": {
            trigger_id: {"id": trigger_id, "label": "", "node_type": "trigger", "position_x": 355.0, "position_y": 134.0,
                         "data": {"trigger_type": "text", "config": config}},
            action_id: {"id": action_id, "label": "", "node_type": "action", "position_x": 355.0, "position_y": 224.0,
                        "data": {"action_type": handler, "action": {"type": handler}, "config": {}}},
        }, "edges": {edge_id: {"id": edge_id, "source_node": trigger_id, "target_node": action_id,
                                "source_port": "default", "target_port": "default"}}},
    }


def apply_pending(store_path, astra_path):
    state = read_json(store_path, {"entries": []})
    commands = read_json(astra_path, [])
    if not isinstance(commands, list):
        raise ValueError("Неизвестный формат файла команд Astra")
    entries = state.get("entries", [])
    for entry in entries:
        validate_phrases(entry["phrases"], entries, commands, entry["id"])
    merged = [c for c in commands if not is_owned(c)]
    foreign_ids = {c.get("id") for c in merged}
    if any(e["id"] in foreign_ids for e in entries):
        raise ValueError("Идентификатор команды уже занят другой командой Astra")
    merged.extend(as_command(e) for e in entries)
    if astra_path.exists():
        backup = astra_path.with_name("commands.json.bak.yandex-home-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        backup.write_bytes(astra_path.read_bytes())
    atomic_json(astra_path, merged)
    state["applied_revision"] = state.get("revision", 0)
    state["applied_entries"] = entries
    state["trigger_version"] = 2
    state.pop("apply_error", None)
    atomic_json(store_path, state)


def windows_parent_pid(pid):
    from ctypes import wintypes
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise RuntimeError("Не удалось определить родительский процесс")
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    raise RuntimeError("Родительский процесс уже завершён")


def open_host_handle(starting_pid=None):
    """Use only our verified parent, never an arbitrary process or credential."""
    if os.name != "nt":
        # Linux: plugin is spawned by the daemon; verify its executable.
        pid = os.getppid()
        name = Path(os.readlink(f"/proc/{pid}/exe")).name.casefold()
        if name not in ("astra", "astra-daemon"):
            raise RuntimeError("Сохранение доступно при запуске плагина из Astra")
        return pid
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = starting_pid or os.getppid()
    python_paths = {Path(sys.executable).resolve(), Path(getattr(sys, "_base_executable", sys.executable)).resolve()}
    # Windows venv's python.exe is a redirector: the real interpreter has an
    # extra parent. Follow only our own interpreter paths to the actual host.
    for _ in range(4):
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        size, buffer = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not handle:
            raise RuntimeError("Не удалось определить процесс Astra")
        try:
            if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise RuntimeError("Не удалось определить процесс Astra")
            image = Path(buffer.value)
            if image.name.casefold() in ("astra.exe", "astra-daemon.exe"):
                return pid
            if image.resolve() not in python_paths:
                break
            pid = windows_parent_pid(pid)
        finally:
            kernel.CloseHandle(handle)
    raise RuntimeError("Сохранение доступно при запуске плагина из Astra")


class WindowsWriterProcess:
    """Small process handle for the worker created by the Windows service."""

    def __init__(self, pid):
        from ctypes import wintypes
        self.pid = pid
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
        if not self.handle and ctypes.get_last_error() != 87:
            raise OSError(ctypes.get_last_error(), "Не удалось проверить фоновое сохранение")

    def poll(self):
        from ctypes import wintypes
        if not self.handle:
            return 0
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), "Не удалось проверить фоновое сохранение")
        return None if code.value == 259 else code.value

    def wait(self, timeout=None):
        if self.handle:
            result = self.kernel.WaitForSingleObject(self.handle, 0xffffffff if timeout is None else int(timeout * 1000))
            if result == 258:
                raise subprocess.TimeoutExpired("voice command writer", timeout)
            if result != 0:
                raise OSError(ctypes.get_last_error(), "Не удалось дождаться фонового сохранения")
        return self.poll()

    def terminate(self):
        if self.handle and self.poll() is None:
            self.kernel.TerminateProcess(self.handle, 1)

    def __del__(self):
        if getattr(self, "handle", None):
            self.kernel.CloseHandle(self.handle)


def spawn_writer_process(args):
    if os.name != "nt":
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    # Astra supervises plugin trees in a Windows Job Object. A normal child
    # dies when that job is closed, before it can save commands after exit.
    # Win32_Process.Create is the supported Windows launch path outside the
    # caller's job. Use the base pythonw directly: the worker needs only the
    # standard library, and a venv redirector creates another supervised job.
    candidates = [Path(getattr(sys, "_base_executable", args[0])).with_name("pythonw.exe"),
                  Path(args[0]).with_name("pythonw.exe")]
    windowless = next((p for p in candidates if p.exists()), None)
    if windowless is None:
        raise RuntimeError("Не найден pythonw.exe для сохранения команд без консоли")
    command_line = subprocess.list2cmdline([str(windowless), *args[1:]])
    literal = "'" + command_line.replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference='Stop'; "
        "$startup=New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
        "-Property @{ShowWindow=[uint16]0}; "
        "$worker=Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine=" + literal + ";ProcessStartupInformation=$startup}; "
        "if($worker.ReturnValue -ne 0){throw ('Ошибка запуска: '+$worker.ReturnValue)}; "
        "[Console]::Write($worker.ProcessId)"
    )
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                             "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup, timeout=12)
    if result.returncode or not result.stdout.strip().isdigit():
        raise RuntimeError("Windows не удалось подготовить фоновое сохранение команд")
    return WindowsWriterProcess(int(result.stdout.strip()))


def start_writer(store_path, astra_path):
    pid = open_host_handle()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    ready = store_path.with_name("voice-writer-" + uuid.uuid4().hex + ".ready")
    args = [sys.executable, str(Path(__file__).resolve()), "--wait-host", str(pid), str(store_path), str(astra_path), str(ready)]
    process = spawn_writer_process(args)
    try:
        deadline = time.monotonic() + 3
        while not ready.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                process.terminate() if process.poll() is None else None
                raise RuntimeError("Не удалось подготовить сохранение команд. Повторите попытку")
            time.sleep(.02)
        return process
    finally:
        ready.unlink(missing_ok=True)


def wait_host(pid, ready=None):
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle and ctypes.get_last_error() != 87:
            raise RuntimeError("Не удалось дождаться закрытия Astra; команды не изменены")
        if ready:
            ready.write_text("ready", encoding="utf-8")
        if handle:
            try:
                if kernel.WaitForSingleObject(handle, 0xffffffff) != 0:
                    raise RuntimeError("Не удалось дождаться закрытия Astra; команды не изменены")
            finally:
                kernel.CloseHandle(handle)
    else:
        if ready:
            ready.write_text("ready", encoding="utf-8")
        while Path(f"/proc/{pid}").exists():
            time.sleep(.2)


def writer_lock(store):
    """A process lock survives plugin reloads but is released if a writer dies."""
    handle = store.with_suffix(".worker.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--wait-host":
        store, commands = Path(sys.argv[3]), Path(sys.argv[4])
        ready = Path(sys.argv[5])
        lock = writer_lock(store)
        if lock is None:
            ready.write_text("already-running", encoding="utf-8")
            sys.exit(0)
        try:
            wait_host(int(sys.argv[2]), ready)
            apply_pending(store, commands)
        except Exception as error:
            state = read_json(store, {})
            state["apply_error"] = str(error)
            atomic_json(store, state)
        finally:
            lock.close()
