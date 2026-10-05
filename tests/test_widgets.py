import json
from unittest.mock import Mock
import pytest
from src.desktop_widgets import DesktopWidgets, normalize_widget
from src.widget_data import device_catalog, reading
from src.system_metrics import parse_nvidia

def sensor(value=21.5):
    return {'id':'sensor', 'name':'Климат в комнате', 'properties':[
        {'type':'devices.properties.float', 'parameters':{'instance':'temperature','unit':'unit.temperature.celsius'}, 'state':{'instance':'temperature','value':value}},
        {'type':'devices.properties.float', 'parameters':{'instance':'humidity'}, 'state':{'instance':'humidity','value':42}},
        {'type':'devices.properties.event', 'parameters':{'instance':'water_leak'}, 'state':{'instance':'water_leak','value':'dry'}},
    ], 'capabilities':[{'type':'devices.capabilities.on_off','retrievable':False}]}

@pytest.fixture
def manager(tmp_path):
    devices=Mock(return_value=[sensor()])
    account=Mock(return_value='account-a')
    manager=DesktopWidgets(tmp_path, devices, account)
    manager.ensure=Mock()
    manager.metrics.read=Mock(return_value={'ram_percent':37})
    manager.refresh(True)
    return manager

def test_any_read_only_property_and_units():
    rows=device_catalog([sensor()])
    assert len(rows)==3
    assert reading(rows[0])['text']=='21,5 °C'
    assert reading(rows[1])['text']=='42 %'
    assert reading(rows[1])['progress']==42
    assert reading(rows[2])['text']=='Сухо'
    assert reading(device_catalog([sensor(None)])[0])['text']=='Нет данных'

def test_settings_persist_all_items_and_customization(manager):
    key=next(iter(manager.sources))
    value={'title':'Спальня','items':[{'key':key,'label':'В комнате'},{'key':'system:ram_percent'}],
           'background':'#112233','foreground':'#abcdef','accent':'#dd0055','transparency':55,
           'width':420,'font_size':16,'refresh_seconds':30,'rounded':False,'on_top':True}
    state=manager.save(value)
    widget=state['widgets'][0]
    assert widget['background']=='#112233' and widget['transparency']==55
    assert 'account' not in widget
    manager.sessions[widget['id']]='window-session'
    snapshot=manager.snapshot(widget['id'],'window-session')
    assert snapshot['rows'][0]['label']=='В комнате'
    assert snapshot['rows'][1]['text']=='37 %'
    fresh=DesktopWidgets(manager.path.parent, manager.devices, manager.account)
    assert fresh.state()['widgets'][0]['items']==widget['items']

def test_device_failure_retains_timestamp_and_marks_stale(manager):
    key=next(iter(manager.sources))
    w=manager.save({'items':[{'key':key}]})['widgets'][0]
    manager.sessions[w['id']]='session'
    manager.devices.return_value={'error':'offline'}
    manager.refresh(True)
    state=manager.snapshot(w['id'],'session')
    assert state['device_error']=='offline' and state['rows'][0]['stale']
    assert state['rows'][0]['text']=='21,5 °C' and state['updated']
    manager.devices.return_value=[sensor(None)]
    manager.refresh(True)
    assert manager.snapshot(w['id'],'session')['rows'][0]['text']=='Нет данных'

def test_missing_device_and_changed_account_do_not_show_old_telemetry(manager):
    key=next(iter(manager.sources))
    w=manager.save({'items':[{'key':key}]})['widgets'][0]
    manager.sessions[w['id']]='session'
    manager.account.return_value='account-b'
    assert manager.snapshot(w['id'],'session')['rows'][0]['text']=='Нет данных'
    with pytest.raises(ValueError):
        manager.save({'items':[{'key':key}]},w['id'])
    manager.devices.return_value=[]
    manager.refresh(True)
    assert manager.snapshot(w['id'],'session')['rows'][0]['text']=='Нет данных'

@pytest.mark.parametrize('change',[
    {'transparency':81},{'width':True},{'background':'url(bad)'},{'font_size':9},
    {'items':[{'key':'not-allowed'}]}, {'items':[]}, {'items':[{'key':'system:ram_percent'}]*2},
    {'refresh_seconds':0},{'x':float('inf')},
])
def test_invalid_customization_is_rejected(manager,change):
    before=manager.state()
    with pytest.raises(ValueError):
        manager.save({'items':[{'key':'system:ram_percent'}],**change})
    assert manager.state()==before

def test_window_session_position_close_and_deletion(manager):
    w=manager.save({'items':[{'key':'system:ram_percent'}]})['widgets'][0]
    with pytest.raises(ValueError):manager.snapshot(w['id'],'wrong')
    manager.sessions[w['id']]='session'
    manager.report(w['id'],'session',x=-320,y=120)
    assert manager.state()['widgets'][0]['x']==-320
    manager.change(w['id'],reset_position=True)
    assert manager.state()['widgets'][0]['x'] is None
    manager.sessions[w['id']]='session'
    manager.report(w['id'],'session',closed=True)
    assert not manager.state()['widgets'][0]['enabled']
    manager.change(w['id'],delete=True)
    assert manager.state()['widgets']==[]

def test_nvidia_unavailable_is_not_zero_and_vram_is_percent():
    values=parse_nvidia('NVIDIA RTX 4070, 24, 40, 1024, 4096')
    assert values['gpu_percent']==24 and values['gpu_temp_c']==40
    assert values['gpu_memory_percent']==25
    values=parse_nvidia('GPU, N/A, [Not Supported], 0, 0')
    assert values['gpu_percent'] is None and values['gpu_memory_percent'] is None
    assert parse_nvidia('bad')=={}


def test_one_second_polling_shared_across_widgets_and_error_backoff(manager, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('src.desktop_widgets.time.monotonic', lambda: clock[0])
    manager.last_fetch = 99
    manager.devices.reset_mock()
    manager.refresh(interval=1)
    clock[0] = 100.9
    manager.refresh(interval=1)
    assert manager.devices.call_count == 1
    clock[0] = 101
    manager.refresh(interval=1)
    assert manager.devices.call_count == 2
    manager.devices.return_value = {'error': 'offline'}
    clock[0] = 102
    manager.refresh(interval=1)
    clock[0] = 103
    manager.refresh(interval=1)
    assert manager.devices.call_count == 3
    clock[0] = 104
    manager.refresh(interval=1)
    assert manager.devices.call_count == 4
    manager.devices.return_value = [sensor(23)]
    clock[0] = 108
    manager.refresh(interval=1)
    clock[0] = 109
    manager.refresh(interval=1)
    assert manager.devices.call_count == 6 and manager.failures == 0


def test_legacy_widget_gets_image_default_without_losing_settings(tmp_path):
    (tmp_path / 'desktop-widgets.json').write_text(json.dumps({'widgets': [{
        'id': 'old', 'items': [{'key': 'system:ram_percent', 'label': 'Memory'}],
        'width': 460, 'refresh_seconds': 15, 'x': -320, 'y': 120}]}))
    manager = DesktopWidgets(tmp_path, lambda: [], lambda: 'test')
    widget = manager.state()['widgets'][0]
    assert widget['background_image'] == '' and widget['refresh_seconds'] == 15
    assert widget['width'] == 460 and widget['x'] == -320
