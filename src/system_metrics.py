"""Read-only local telemetry; no daemon credentials or third-party service."""
import csv
import ctypes
import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

SYSTEM_SOURCES = [
    ('cpu_percent', 'ЦП', '%', 0, 100), ('ram_percent', 'ОЗУ', '%', 0, 100),
    ('ram_used_gb', 'ОЗУ занято', 'ГБ', None, None), ('ram_total_gb', 'ОЗУ всего', 'ГБ', None, None),
    ('gpu_percent', 'Видеокарта NVIDIA', '%', 0, 100), ('gpu_temp_c', 'Температура ГП NVIDIA', '°C', 0, 100),
    ('gpu_memory_percent', 'Видеопамять NVIDIA', '%', 0, 100),
]


def system_catalog():
    return [{'key': 'system:' + key, 'source': 'system', 'label': label, 'unit': unit,
             'min': lo, 'max': hi, 'value': None} for key, label, unit, lo, hi in SYSTEM_SOURCES]


def parse_nvidia(text):
    row = next(csv.reader(text.splitlines()), [])
    if len(row) != 5:
        return {}
    name, usage, temperature, used, total = row
    result = {'gpu_name': name.strip()}
    def number(value):
        try:
            n = float(value.strip())
            return n if math.isfinite(n) and n >= 0 else None
        except ValueError:
            return None
    result['gpu_percent'] = number(usage)
    result['gpu_temp_c'] = number(temperature)
    used, total = number(used), number(total)
    result['gpu_memory_percent'] = round(100 * used / total, 1) if used is not None and total else None
    return result


class SystemMetrics:
    def __init__(self):
        self.previous = None
        self.updated = 0
        self.values = {}
        self.lock = threading.Lock()
        self.nvidia = shutil.which('nvidia-smi.exe' if os.name == 'nt' else 'nvidia-smi')
        if os.name == 'nt' and not self.nvidia:
            for path in (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/nvidia-smi.exe',
                         Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation/NVSMI/nvidia-smi.exe'):
                if path.is_file():
                    self.nvidia = str(path)
                    break

    def read(self):
        with self.lock:
            if time.monotonic() - self.updated < 1:
                return dict(self.values)
            values = {}
            if os.name == 'nt':
                from ctypes import wintypes
                class Memory(ctypes.Structure):
                    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                        (k, ctypes.c_ulonglong) for k in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Memory)]
                memory = Memory()
                memory.length = ctypes.sizeof(memory)
                if kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
                    values.update(ram_percent=memory.load, ram_used_gb=round((memory.total-memory.available)/2**30, 1), ram_total_gb=round(memory.total/2**30, 1))
                idle, system, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
                kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
                if kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user)):
                    unpack = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
                    current = (unpack(idle), unpack(system) + unpack(user))
                    if self.previous and current[1] > self.previous[1]:
                        values['cpu_percent'] = round(max(0, min(100, 100 * (1 - (current[0]-self.previous[0])/(current[1]-self.previous[1])))), 1)
                    self.previous = current
            if self.nvidia:
                try:
                    result = subprocess.run([self.nvidia, '--id=0', '--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total',
                                             '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, timeout=3)
                    if result.returncode == 0:
                        values.update(parse_nvidia(result.stdout))
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.values, self.updated = values, time.monotonic()
            return dict(values)
