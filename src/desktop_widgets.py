"""Persist and supervise optional, read-only desktop sensor windows."""
import copy
import logging
import os
import re
import secrets
import subprocess
import sys
import sysconfig
import threading
import time
import uuid
from pathlib import Path
from .voice_commands import atomic_json, read_json
from .system_metrics import SystemMetrics, system_catalog
from .widget_data import device_catalog, reading

log = logging.getLogger(__name__)
DEFAULTS = {'title': 'Мой дом', 'enabled': True, 'on_top': False, 'rounded': True, 'bars': True,
            'transparency': 10, 'background': '#25243b', 'foreground': '#ffffff', 'accent': '#a78bfa',
            'width': 340, 'font_size': 13, 'refresh_seconds': 1, 'background_image': '', 'x': None, 'y': None, 'items': []}


def normalize_widget(value, available, previous=None):
    if not isinstance(value, dict):
        raise ValueError('Некорректные настройки виджета')
    result = {**copy.deepcopy(DEFAULTS), **(previous or {})}
    for key in ('enabled', 'on_top', 'rounded', 'bars'):
        if key in value:
            if type(value[key]) is not bool:
                raise ValueError('Некорректный переключатель виджета')
            result[key] = value[key]
    for key, lo, hi in [('transparency', 0, 80), ('width', 240, 800), ('font_size', 10, 28), ('refresh_seconds', 1, 300)]:
        if key in value:
            if type(value[key]) is not int or not lo <= value[key] <= hi:
                raise ValueError(f'Параметр {key} должен быть от {lo} до {hi}')
            result[key] = value[key]
    for key in ('background', 'foreground', 'accent'):
        if key in value:
            if not isinstance(value[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value[key]):
                raise ValueError('Выберите корректный цвет')
            result[key] = value[key]
    for key in ('x', 'y'):
        if key in value:
            coordinate = value[key]
            if coordinate is not None and (type(coordinate) is not int or not -100000 <= coordinate <= 100000):
                raise ValueError('Некорректная позиция')
            result[key] = coordinate
    title = value.get('title', result['title'])
    image = value.get('background_image', result['background_image'])
    if not isinstance(image, str) or (image and not re.fullmatch(r'[a-f0-9]{64}', image)):
        raise ValueError('Выберите картинку фона из файла')
    result['background_image'] = image
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
        raise ValueError('Название должно содержать от 1 до 80 символов')
    result['title'] = title.strip()
    items = value.get('items', result['items'])
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError('Добавьте от 1 до 12 показателей')
    previous_keys = {i['key'] for i in (previous or {}).get('items', [])}
    allowed = set(available) | previous_keys
    result['items'] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str) or item['key'] not in allowed:
            raise ValueError('Показатель недоступен. Обновите список устройств')
        if item['key'] in seen:
            raise ValueError('Показатель уже добавлен')
        label = item.get('label', '')
        if not isinstance(label, str) or len(label.strip()) > 80:
            raise ValueError('Подпись показателя должна быть до 80 символов')
        seen.add(item['key'])
        result['items'].append({'key': item['key'], 'label': label.strip()})
    return result


class DesktopWidgets:
    def __init__(self, directory, devices, account):
        self.path = directory / 'desktop-widgets.json'
        self.devices, self.account = devices, account
        self.lock = threading.RLock()
        self.fetch_lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self.processes, self.sessions, self.errors = {}, {}, {}
        self.metrics = SystemMetrics()
        self.sources, self.device_error, self.updated, self.last_fetch = {}, '', '', 0
        self.source_account = ''
        self.failures = 0
        self.available = os.name == 'nt'
        stored = read_json(self.path, {'widgets': []})
        if not isinstance(stored, dict) or not isinstance(stored.get('widgets'), list):
            raise ValueError('Не удалось прочитать настройки виджетов')
        self.widgets = [{**copy.deepcopy(DEFAULTS), **w} for w in stored['widgets']]

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name='home-widget-monitor')
            self.thread.start()

    def _loop(self):
        while not self.stopping.wait(.25):
            try:
                with self.lock:
                    active = [w for w in self.widgets if w['enabled']]
                if active:
                    if any(not i['key'].startswith('system:') for w in active for i in w['items']):
                        self.refresh(False, min(w['refresh_seconds'] for w in active))
                    self.ensure()
            except Exception:
                log.exception('Desktop widget refresh failed')

    def refresh(self, force=False, interval=1):
        with self.fetch_lock:
            retry_interval = max(interval, min(30, 2 ** min(self.failures, 5))) if self.failures else interval
            if not force and time.monotonic() - self.last_fetch < retry_interval:
                return
            error = ''
            account = self.account()
            try:
                devices = self.devices()
                if not isinstance(devices, list):
                    raise RuntimeError(devices.get('error', 'Нет данных устройств'))
                sources = {s['key']: s for s in device_catalog(devices)}
                if account != self.account():
                    raise RuntimeError('Аккаунт изменился во время обновления')
            except Exception as exc:
                error = str(exc)
                sources = None
            with self.lock:
                if sources is not None:
                    self.sources = sources
                    self.source_account = account
                    self.updated = time.strftime('%H:%M:%S')
                self.device_error = error
                self.failures = self.failures + 1 if error else 0
                self.last_fetch = time.monotonic()

    def catalog(self):
        self.refresh(True)
        values = self.metrics.read()
        with self.lock:
            sources = copy.deepcopy(list(self.sources.values())) if self.source_account == self.account() else []
            sources += system_catalog()
            for source in sources:
                if source['source'] == 'system':
                    source['value'] = values.get(source['key'].split(':', 1)[1])
                    if source['key'] == 'system:gpu_percent' and values.get('gpu_name'):
                        source['label'] = values['gpu_name']
                source['reading'] = reading(source)
            return {'sources': sources, 'device_error': self.device_error, 'available': self.available,
                    'system_note': 'Показатели компьютера получаем локально. NVIDIA — при наличии драйвера; недоступные значения показываем как «Нет данных».'}

    def state(self):
        with self.lock:
            return {'widgets': [{**{k: copy.deepcopy(v) for k, v in w.items() if k != 'account'},
                                 'running': bool(self.processes.get(w['id']) and self.processes[w['id']].poll() is None),
                                 'error': self.errors.get(w['id'], '')} for w in self.widgets], 'available': self.available}

    def _save(self):
        atomic_json(self.path, {'widgets': self.widgets})

    def save(self, value, ident=''):
        if ident and not isinstance(ident, str):
            raise ValueError('Неизвестный виджет')
        with self.lock:
            previous = next((w for w in self.widgets if w['id'] == ident), None)
            if ident and previous is None:
                raise ValueError('Виджет уже удалён')
            if previous is None and len(self.widgets) >= 8:
                raise ValueError('Можно создать до 8 виджетов')
            updated = normalize_widget(value, [*self.sources, *[s['key'] for s in system_catalog()]], previous)
            if updated['background_image']:
                from .widget_images import image_path
                if not image_path(self.path.parent, updated['background_image']).is_file():
                    raise ValueError('Картинка фона не найдена. Выберите файл снова')
            if any(not i['key'].startswith('system:') for i in updated['items']) and self.source_account != self.account():
                raise ValueError('Аккаунт изменился. Обновите показатели и выберите устройства заново')
            if updated['enabled'] and not self.available:
                raise ValueError('Настольные виджеты доступны в Windows')
            updated['id'] = ident or str(uuid.uuid4())
            updated['account'] = self.account()
            before = self.widgets
            self.widgets = [updated if w['id'] == ident else w for w in self.widgets] if previous else self.widgets + [updated]
            try:
                self._save()
            except Exception:
                self.widgets = before
                raise
            self.errors.pop(updated['id'], None)
            if not updated['enabled']:
                self.stop(updated['id'])
            self.ensure()
            return self.state()

    def change(self, ident, enabled=None, delete=False, reset_position=False):
        with self.lock:
            previous = next((w for w in self.widgets if w['id'] == ident), None)
            if not previous:
                raise ValueError('Виджет уже удалён')
            if delete:
                before = self.widgets
                self.widgets = [w for w in self.widgets if w['id'] != ident]
                try:
                    self._save()
                except Exception:
                    self.widgets = before
                    raise
                self.stop(ident)
                return self.state()
            updated = dict(previous)
            if enabled is not None:
                if type(enabled) is not bool:
                    raise ValueError('Некорректный переключатель')
                updated['enabled'] = enabled
            if reset_position:
                updated.update(x=None, y=None)
                self.stop(ident)
            return self.save(updated, ident)

    def ensure(self):
        with self.lock:
            if not self.available or self.stopping.is_set():
                return
            for w in self.widgets:
                ident = w['id']
                process = self.processes.get(ident)
                if not w['enabled'] or (process and process.poll() is None) or self.errors.get(ident):
                    continue
                if process:
                    self.errors[ident] = 'Окно завершилось. Выключите и включите виджет, чтобы повторить.'
                    continue
                try:
                    # Avoid the venv redirector's extra process while using the
                    # plugin's installed image dependency with the same Python ABI.
                    pythonw = Path(getattr(sys, '_base_executable', sys.executable)).with_name('pythonw.exe')
                    if not pythonw.is_file():
                        raise RuntimeError('Не найден Python для окна виджета')
                    self.sessions[ident] = secrets.token_urlsafe(24)
                    environment = os.environ.copy()
                    environment['PYTHONPATH'] = os.pathsep.join(filter(None, [
                        sysconfig.get_path('purelib'), sysconfig.get_path('platlib'), environment.get('PYTHONPATH', '')]))
                    self.processes[ident] = subprocess.Popen([str(pythonw), '-m', 'src.desktop_window', ident, self.sessions[ident]],
                        cwd=str(Path(__file__).resolve().parent.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, env=environment)
                except Exception as exc:
                    self.errors[ident] = str(exc)

    def snapshot(self, id, session):
        with self.lock:
            if not secrets.compare_digest(self.sessions.get(id, ''), session) or not session:
                raise ValueError('Окно виджета не зарегистрировано')
            widget = next((w for w in self.widgets if w['id'] == id), None)
            if not widget:
                return {'closed': True}
            widget = copy.deepcopy(widget)
            sources, error, updated = copy.deepcopy(self.sources), self.device_error, self.updated
        values = self.metrics.read() if any(i['key'].startswith('system:') for i in widget['items']) else {}
        sources.update({s['key']: {**s, 'value': values.get(s['key'].split(':', 1)[1])} for s in system_catalog()})
        rows = []
        for item in widget['items']:
            source = sources.get(item['key'], {'key': item['key'], 'label': item['label'] or 'Недоступный показатель', 'value': None})
            if not item['key'].startswith('system:') and (widget.get('account') != self.account() or self.source_account != self.account()):
                source = {**source, 'value': None}
                error = 'Аккаунт изменён. Настройте показатели заново.'
            row = reading(source, item['label'])
            row['stale'] = bool(error and not item['key'].startswith('system:'))
            rows.append(row)
        settings = {k: v for k, v in widget.items() if k != 'account'}
        if widget.get('background_image'):
            from .widget_images import image_path
            settings['background_path'] = str(image_path(self.path.parent, widget['background_image']))
        return {'settings': settings, 'rows': rows,
                'updated': updated, 'device_error': error if any(not i['key'].startswith('system:') for i in widget['items']) else ''}

    def report(self, id, session, x=None, y=None, closed=False):
        with self.lock:
            if not session or not secrets.compare_digest(self.sessions.get(id, ''), session):
                raise ValueError('Окно виджета не зарегистрировано')
            widget = next((w for w in self.widgets if w['id'] == id), None)
            if widget:
                if closed:
                    widget['enabled'] = False
                for key, value in [('x', x), ('y', y)]:
                    if value is not None:
                        if type(value) is not int or not -100000 <= value <= 100000:
                            raise ValueError('Некорректная позиция')
                        widget[key] = value
                self._save()
        return {'success': True}

    def stop(self, ident):
        process = self.processes.pop(ident, None)
        self.sessions.pop(ident, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self.errors.pop(ident, None)

    def close(self):
        self.stopping.set()
        with self.lock:
            for ident in list(self.processes):
                self.stop(ident)
