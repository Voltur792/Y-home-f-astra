import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from astra_plugin_sdk.testing import Harness
from src.plugin import YandexSmartHome
from src.voice_commands import atomic_json, apply_pending, PREFIX
from src import voice_commands


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr('src.plugin.DATA_DIR', tmp_path)
    monkeypatch.setattr('src.plugin.SETTINGS_FILE', tmp_path / 'settings.json')
    monkeypatch.setenv('YSH_COMMANDS_FILE', str(tmp_path / 'commands.json'))
    monkeypatch.setattr('src.voice_commands.start_writer', lambda *a: Mock(poll=lambda: None))
    plugin = YandexSmartHome()
    plugin.api = Mock()
    plugin.api.get_user_info.return_value = {
        'devices': [{'id': 'lamp', 'name': 'Лампа', 'capabilities': [
            {'type': 'devices.capabilities.on_off'},
            {'type': 'devices.capabilities.range', 'parameters': {'instance': 'brightness', 'range': {'min': 1, 'max': 100, 'precision': 1}}},
            {'type': 'devices.capabilities.mode', 'parameters': {'instance': 'program', 'modes': [{'value': 'eco'}]}},
        ]}], 'scenarios': [{'id': 'night', 'name': 'Ночь'}]}
    return plugin, tmp_path


def save(plugin, **extra):
    return plugin.ui_save_voice_command(phrases=['зажги гостиную'], target={
        'kind': 'device', 'target_id': 'lamp', 'capability_type': 'devices.capabilities.on_off',
        'capability_instance': 'on', 'value': True}, **extra)


def restart(plugin, directory):
    apply_pending(directory / 'voice-commands.json', directory / 'commands.json')
    fresh = YandexSmartHome()
    fresh.api = plugin.api
    return fresh


def test_save_is_staged_and_does_not_execute_or_change_running_astra(home):
    plugin, directory = home
    atomic_json(directory / 'commands.json', [{'id': 'other', 'name': 'Другая'}])
    before = (directory / 'commands.json').read_bytes()
    assert save(plugin)['success']
    assert plugin.ui_get_voice_commands()['restart_required']
    assert (directory / 'commands.json').read_bytes() == before
    plugin.api.set_device_capability.assert_not_called()
    plugin.api.run_scenario.assert_not_called()


def test_real_sdk_action_executes_saved_device_directly_without_resolution(home):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    plugin.api.get_user_info.reset_mock()
    plugin._smart_action = Mock(side_effect=AssertionError('AI resolver must not run'))
    with Harness(plugin) as h:
        response = h.execute_action('voice_' + result['id'].replace('-', ''))
        assert response.success
        assert 'выполнена' in response.result
    plugin.api.get_user_info.assert_not_called()
    plugin.api.set_device_capability.assert_called_once_with('lamp', 'devices.capabilities.on_off', 'on', True)


def test_scenario_uses_stable_id_without_ai(home):
    plugin, directory = home
    result = plugin.ui_save_voice_command(phrases=['ночной режим'], target={'kind': 'scenario', 'target_id': 'night'})
    plugin = restart(plugin, directory)
    assert asyncio.run(plugin.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    plugin.api.run_scenario.assert_called_once_with('night')
    plugin.api.set_device_capability.assert_not_called()


def test_range_command_is_configurable(home):
    plugin, directory = home
    result = plugin.ui_save_voice_command(phrases=['яркость пять'], target={'kind': 'device', 'target_id': 'lamp',
        'capability_type': 'devices.capabilities.range', 'capability_instance': 'brightness', 'value': 5})
    plugin = restart(plugin, directory)
    assert asyncio.run(plugin.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    plugin.api.set_device_capability.assert_called_once_with('lamp', 'devices.capabilities.range', 'brightness', 5)


def test_address_and_stt_punctuation_keep_exact_matching(home):
    from src.voice_commands import trigger_phrases, as_command
    plugin, directory = home
    save(plugin)
    entry = plugin._voice_state()['entries'][0]
    command = as_command(entry)
    phrases = command['triggers'][0]['phrases']
    assert 'Астра зажги гостиную' in phrases
    assert 'Астра, зажги гостиную.' in phrases
    assert command['triggers'][0]['exact_match']
    assert 'не зажги гостиную' not in phrases
    assert 'зажги гостиную' in trigger_phrases(['Астра, зажги гостиную!'])
    assert 'error' in plugin.ui_save_voice_command(phrases=['Астра зажги гостиную'], target={'kind': 'scenario', 'target_id': 'night'})


def test_registered_phrase_can_change_target_without_restart(home):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    updated = plugin.ui_save_voice_command(id=result['id'], phrases=['зажги гостиную'],
        target={'kind':'scenario', 'target_id':'night'})
    assert updated['success'] and updated['restart_required'] is False
    assert not plugin.ui_get_voice_commands()['restart_required']
    assert asyncio.run(plugin.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    plugin.api.run_scenario.assert_called_once_with('night')
    plugin.api.set_device_capability.assert_not_called()


@pytest.mark.parametrize('operation', [{'enabled': False}, {'delete': True}])
def test_disabled_and_deleted_actions_stop_immediately(home, operation):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    assert plugin.ui_change_voice_command(id=result['id'], **operation)['success']
    assert not asyncio.run(plugin.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    plugin.api.set_device_capability.assert_not_called()
    apply_pending(directory / 'voice-commands.json', directory / 'commands.json')
    commands = json.loads((directory / 'commands.json').read_text(encoding='utf-8'))
    assert commands == [] if operation.get('delete') else commands[0]['enabled'] is False


def test_edited_target_does_not_execute_with_old_phrase(home):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    assert plugin.ui_save_voice_command(id=result['id'], phrases=['новая фраза'], target={'kind': 'scenario', 'target_id': 'night'})['success']
    assert not asyncio.run(plugin.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    plugin.api.run_scenario.assert_not_called()


def test_changed_account_and_api_errors_are_not_success(home, monkeypatch):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    action = 'voice_' + result['id'].replace('-', '')
    plugin.api.set_device_capability.side_effect = RuntimeError('DEVICE_UNREACHABLE')
    response = asyncio.run(plugin.execute_action(action, '{}'))
    assert response['success'] is False and 'DEVICE_UNREACHABLE' in response['error']
    plugin.api.set_device_capability.reset_mock()
    monkeypatch.setattr('src.plugin._load_saved_token', lambda: 'another-test-account')
    assert not asyncio.run(plugin.execute_action(action, '{}'))['success']
    plugin.api.set_device_capability.assert_not_called()


def test_merge_preserves_other_commands_and_creates_exact_graph(home):
    plugin, directory = home
    foreign = {'id': 'music', 'tags': ['music'], 'enabled': True, 'actions': [{'type': 'speak', 'text': 'test'}]}
    atomic_json(directory / 'commands.json', [foreign])
    result = save(plugin)
    apply_pending(directory / 'voice-commands.json', directory / 'commands.json')
    commands = json.loads((directory / 'commands.json').read_text(encoding='utf-8'))
    assert commands[0] == foreign
    c = commands[1]
    assert c['triggers'][0]['exact_match'] is True
    assert c['actions'][0]['handler_id'] == PREFIX + result['id'].replace('-', '')
    assert c['actions'][0]['params'] == {}
    assert len(c['workflow']['nodes']) == 2
    assert len(c['workflow']['edges']) == 1
    assert list(directory.glob('commands.json.bak.*'))
    assert not plugin.ui_get_voice_commands()['restart_required']
    apply_pending(directory / 'voice-commands.json', directory / 'commands.json')
    assert len(json.loads((directory / 'commands.json').read_text(encoding='utf-8'))) == 2


def test_duplicate_and_foreign_phrase_conflicts(home):
    plugin, directory = home
    assert save(plugin)['success']
    assert 'error' in save(plugin)
    atomic_json(directory / 'commands.json', [{'name': 'Музыка', 'enabled': True,
        'triggers': [{'type': 'text', 'exact_match': True, 'phrases': ['НОЧНОЙ РЕЖИМ']}]}])
    result = plugin.ui_save_voice_command(phrases=['ночной режим'], target={'kind': 'scenario', 'target_id': 'night'})
    assert 'Музыка' in result['error']


def test_conflict_added_after_staging_never_overwrites_astra(home):
    plugin, directory = home
    save(plugin)
    foreign = [{'name': 'Другая', 'triggers': [{'type': 'text', 'phrases': ['зажги гостиную']}]}]
    atomic_json(directory / 'commands.json', foreign)
    with pytest.raises(ValueError):
        apply_pending(directory / 'voice-commands.json', directory / 'commands.json')
    assert json.loads((directory / 'commands.json').read_text(encoding='utf-8')) == foreign


def test_failed_application_after_edit_keeps_old_action_blocked_on_restart(home):
    plugin, directory = home
    result = save(plugin)
    plugin = restart(plugin, directory)
    plugin.ui_save_voice_command(id=result['id'], phrases=['ночной режим'], target={'kind': 'scenario', 'target_id': 'night'})
    commands_path = directory / 'commands.json'
    commands = json.loads(commands_path.read_text(encoding='utf-8'))
    commands.append({'id': 'foreign', 'name': 'Новая чужая команда', 'triggers': [{'type': 'text', 'phrases': ['ночной режим']}]})
    atomic_json(commands_path, commands)
    with pytest.raises(ValueError):
        apply_pending(directory / 'voice-commands.json', commands_path)
    fresh = YandexSmartHome()
    fresh.api = plugin.api
    assert not asyncio.run(fresh.execute_action('voice_' + result['id'].replace('-', ''), '{}'))['success']
    fresh.api.run_scenario.assert_not_called()
    fresh.api.set_device_capability.assert_not_called()


@pytest.mark.parametrize('value', [True, '5', 0, 101, 5.5, float('nan'), float('inf')])
def test_invalid_range_never_saves_or_executes(home, value):
    plugin, directory = home
    result = plugin.ui_save_voice_command(phrases=['яркость пять'], target={'kind': 'device', 'target_id': 'lamp',
        'capability_type': 'devices.capabilities.range', 'capability_instance': 'brightness', 'value': value})
    assert 'error' in result
    assert not (directory / 'voice-commands.json').exists()
    plugin.api.set_device_capability.assert_not_called()


def test_unsupported_device_and_wrong_target_do_not_save(home):
    plugin, _ = home
    for target in [{'kind': 'scenario', 'target_id': 'gone'}, {'kind': 'device', 'target_id': 'lamp',
                   'capability_type': 'devices.capabilities.ir_remote', 'capability_instance': 'button', 'value': 'anything'}]:
        assert 'error' in plugin.ui_save_voice_command(phrases=['тестовая фраза'], target=target)


def test_no_astra_host_means_no_partial_save(home, monkeypatch):
    plugin, directory = home
    monkeypatch.setattr(plugin, '_ensure_voice_writer', Mock(side_effect=RuntimeError('Astra is not running')))
    assert 'error' in save(plugin)
    assert not (directory / 'voice-commands.json').exists()


def test_detached_writer_waits_for_exit_and_only_one_writer_applies(home):
    plugin, directory = home
    save(plugin)
    store, commands, ready = directory / 'voice-commands.json', directory / 'commands.json', directory / 'writer.ready'
    atomic_json(commands, [{'id': 'foreign', 'name': 'Музыка'}])
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    host = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], creationflags=flags)
    writers = []
    try:
        for i in range(2):
            signal = ready.with_name(str(i) + '.ready')
            writer = voice_commands.spawn_writer_process([sys.executable, str(Path(voice_commands.__file__)),
                '--wait-host', str(host.pid), str(store), str(commands), str(signal)])
            writers.append(writer)
            deadline = time.monotonic() + 5
            while not signal.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert signal.exists()
            assert signal.read_text() == ('ready' if i == 0 else 'already-running')
        assert json.loads(commands.read_text(encoding='utf-8')) == [{'id': 'foreign', 'name': 'Музыка'}]
        host.terminate()
        host.wait(timeout=5)
        for writer in writers:
            assert writer.wait(timeout=5) == 0
        assert len(json.loads(commands.read_text(encoding='utf-8'))) == 2
        assert len(list(directory.glob('commands.json.bak.*'))) == 1
        assert not plugin.ui_get_voice_commands()['restart_required']
    finally:
        if host.poll() is None:
            host.terminate()
        host.wait(timeout=5)
        for writer in writers:
            if writer.poll() is None:
                writer.terminate()
            writer.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object regression')
def test_writer_survives_termination_of_host_job(home):
    import ctypes
    from ctypes import wintypes
    plugin, directory = home
    save(plugin)
    store, commands = directory / 'voice-commands.json', directory / 'commands.json'
    signal, go, worker_pid = directory / 'worker.ready', directory / 'go', directory / 'worker.pid'
    atomic_json(commands, [{'id': 'music', 'name': 'Музыка'}])
    host_script = directory / 'host.py'
    host_script.write_text(
        'import sys, time\nfrom pathlib import Path\n'
        f'sys.path.insert(0, {str(Path(voice_commands.__file__).parent)!r})\n'
        'from voice_commands import spawn_writer_process\n'
        f'while not Path({str(go)!r}).exists(): time.sleep(.02)\n'
        f'worker = spawn_writer_process([sys.executable, {str(Path(voice_commands.__file__))!r}, '
        f'"--wait-host", str(__import__("os").getpid()), {str(store)!r}, {str(commands)!r}, {str(signal)!r}])\n'
        f'Path({str(worker_pid)!r}).write_text(str(worker.pid))\n'
        'time.sleep(30)\n', encoding='utf-8')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    assert job
    host = subprocess.Popen([sys.executable, str(host_script)], creationflags=subprocess.CREATE_NO_WINDOW)
    worker = None
    try:
        assert kernel.AssignProcessToJobObject(job, int(host._handle))
        go.touch()
        deadline = time.monotonic() + 20
        while not (signal.exists() and worker_pid.exists()) and time.monotonic() < deadline:
            assert host.poll() is None
            time.sleep(.02)
        assert signal.exists() and worker_pid.exists()
        worker = voice_commands.WindowsWriterProcess(int(worker_pid.read_text()))
        in_job = wintypes.BOOL()
        assert kernel.IsProcessInJob(worker.handle, None, ctypes.byref(in_job))
        assert not in_job.value
        assert json.loads(commands.read_text(encoding='utf-8')) == [{'id': 'music', 'name': 'Музыка'}]
        assert kernel.TerminateJobObject(job, 1)
        host.wait(timeout=5)
        assert worker.wait(timeout=5) == 0
        assert len(json.loads(commands.read_text(encoding='utf-8'))) == 2
        assert not plugin.ui_get_voice_commands()['restart_required']
    finally:
        if host.poll() is None:
            host.terminate()
        host.wait(timeout=5)
        kernel.CloseHandle(job)
        if worker and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows windowless Python regression')
def test_writer_has_no_console_with_venv_redirector(tmp_path):
    venv_python = Path(__file__).resolve().parents[1] / '.venv/Scripts/python.exe'
    if not venv_python.exists():
        pytest.skip('No local venv')
    result = tmp_path / 'windowless.json'
    code = ('import ctypes,json;from ctypes import wintypes;from pathlib import Path;'
            'k=ctypes.WinDLL("kernel32");k.GetCurrentProcess.restype=wintypes.HANDLE;'
            'k.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)];'
            'b=wintypes.BOOL();k.IsProcessInJob(k.GetCurrentProcess(),None,ctypes.byref(b));'
            f'Path({str(result)!r}).write_text(json.dumps({{"console":bool(k.GetConsoleWindow()),"job":bool(b.value)}}))')
    worker = voice_commands.spawn_writer_process([str(venv_python), '-c', code])
    assert worker.wait(timeout=10) == 0
    assert json.loads(result.read_text()) == {'console': False, 'job': False}
