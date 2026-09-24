import asyncio
import base64
import io
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from src.plugin import YandexSmartHome
from src.api import YandexSmartHomeAPI

@pytest.fixture
def plugin(monkeypatch):
    monkeypatch.setattr('src.plugin._load_saved_token', lambda: None)
    p = YandexSmartHome()
    p.api = Mock()
    p.api.get_user_info.return_value = {
        'scenarios': [{'id':'fifteen','name':'Запусти двигатель на 15 минут'},
                      {'id':'five','name':'5 минут'}, {'id':'one','name':'1 минута'}],
        'devices': [{'id':'lamp','name':'Умная лампочка','capabilities':[{'type':'devices.capabilities.on_off'}]}]}
    return p

@pytest.mark.parametrize('phrase', ['5 минут', 'Запусти сценарий 5 минут.', 'Запусти сценарий 5 минут в умном дону', 'запусти сценарий пять минут'])
def test_five_minutes(plugin, phrase):
    assert plugin.tool_run_scenario(phrase)['scenario']['id'] == 'five'
    plugin.api.run_scenario.assert_called_once_with('five')

@pytest.mark.parametrize('phrase', ['15 минут', '5 часов', 'запустить любой сценарий', 'сценарий', 'умная лампочка'])
def test_no_wrong_scenario(plugin, phrase):
    if phrase == '15 минут':
        plugin.api.get_user_info.return_value['scenarios'] = [{'id':'five','name':'5 минут'}]
    assert 'error' in plugin.tool_run_scenario(phrase)
    plugin.api.run_scenario.assert_not_called()
    plugin.api.set_device_capability.assert_not_called()

def test_duplicate_names_require_id(plugin):
    plugin.api.get_user_info.return_value['scenarios'].append({'id':'other','name':'5 минут'})
    assert 'несколько' in plugin.tool_run_scenario('5 минут')['error']
    plugin.api.run_scenario.assert_not_called()

def test_off_in_legacy_args(plugin):
    result = plugin.tool_smart_home(kwargs='{"query":"Умная лампочка","value":"off"}')
    assert result['action'] == 'device_off'
    plugin.api.run_scenario.assert_not_called()

def test_false_never_runs_scenario(plugin):
    assert 'error' in plugin.tool_smart_home('5 минут', value='off')
    plugin.api.run_scenario.assert_not_called()

def test_transport_preserves_russian(plugin):
    result = asyncio.run(plugin.call_tool('tool_get_scenarios', '{}'))
    assert '5 минут' in result['result']
    assert '\\u043c' not in result['result']
    assert json.loads(result['result'])['count'] == 3

def test_transport_marks_errors(plugin):
    result = asyncio.run(plugin.call_tool('tool_run_scenario', '{"scenario_id":"нет"}'))
    assert result['success'] is False

@pytest.mark.parametrize('code', ['INVALID_ACTION', 'DEVICE_UNREACHABLE'])
def test_nested_action_errors(code):
    api = YandexSmartHomeAPI('test')
    api._post = Mock(return_value={'status':'ok','devices':[{'id':'lamp','capabilities':[{
        'type':'devices.capabilities.on_off','state':{'instance':'on','action_result':{'status':'ERROR','error_code':code}}}]}]})
    with pytest.raises(RuntimeError, match=code):
        api.set_device_capability('lamp','devices.capabilities.on_off','on',True)

def test_missing_ack_is_not_success():
    api = YandexSmartHomeAPI('test')
    api._post = Mock(return_value={'status':'ok','devices':[]})
    with pytest.raises(RuntimeError):
        api.set_device_capability('lamp','devices.capabilities.on_off','on',True)

def test_done_ack():
    api = YandexSmartHomeAPI('test')
    api._post = Mock(return_value={'status':'ok','devices':[{'id':'lamp','capabilities':[{
        'type':'devices.capabilities.on_off','state':{'instance':'on','action_result':{'status':'DONE'}}}]}]})
    assert api.set_device_capability('lamp','devices.capabilities.on_off','on',False)

def test_scenario_error():
    api = YandexSmartHomeAPI('test')
    api._post = Mock(return_value={'status':'error','message':'not found'})
    with pytest.raises(RuntimeError, match='not found'):
        api.run_scenario('missing')

def test_legacy_capability_is_not_ignored(plugin):
    assert 'error' in plugin.tool_control_device(kwargs='{"device_id":"lamp","capability_type":"devices.capabilities.range","capability_instance":"brightness","value":true}')
    plugin.api.set_device_capability.assert_not_called()

def test_device_ambiguity(plugin):
    plugin.api.get_user_info.return_value['devices'] += [
        {'id':'lamp2','name':'Умная лампочка спальня','capabilities':[{'type':'devices.capabilities.on_off'}]},
        {'id':'lamp3','name':'Умная лампочка кухня','capabilities':[{'type':'devices.capabilities.on_off'}]}]
    assert 'error' in plugin.tool_control_device('лампочку')
    plugin.api.set_device_capability.assert_not_called()

def test_http_200_error_payload():
    api = YandexSmartHomeAPI('test')
    response = Mock()
    response.json.return_value = {'status':'error','message':'access denied'}
    api.session.get = Mock(return_value=response)
    with pytest.raises(RuntimeError, match='access denied'):
        api.get_user_info()

def test_scenario_success():
    api = YandexSmartHomeAPI('test')
    api._post = Mock(return_value={'status':'ok'})
    assert api.run_scenario('five')
    api._post.assert_called_once_with('/v1.0/scenarios/five/actions')

def test_plugin_page_contribution_is_transparent():
    contributions = asyncio.run(YandexSmartHome().get_ui_contributions())
    assert len(contributions) == 1
    page = contributions[0]
    assert page.id == 'yandex-smart-home'
    assert page.slot == 'page.custom'
    assert page.transparent is True
    assert page.icon_svg, 'the tab must carry the embedded icon'

def test_tab_icon_svg_is_self_contained():
    # Astra's store drops icons carrying scripts or off-machine references.
    svg = YandexSmartHome._astra_ui_contributions[0].icon_svg
    assert 'data:image/png;base64,' in svg
    low = svg.lower()
    for forbidden in ('<script', 'onload=', 'onerror=', 'foreignobject'):
        assert forbidden not in low
    without_ns = low.replace('xmlns="http://www.w3.org/2000/svg"', '')
    assert 'http://' not in without_ns and 'https://' not in without_ns and 'file://' not in without_ns
    payload = svg.split('base64,', 1)[1].split('"', 1)[0]
    assert base64.b64decode(payload)[:8] == b'\x89PNG\r\n\x1a\n'

def test_tab_icon_matches_main_icon():
    # The tab icon is generated from icon.png: replacing the icon without
    # regenerating src/tab_icon.py must fail here, not silently disagree.
    PILImage = pytest.importorskip('PIL.Image')
    import re
    from src.tab_icon import TAB_ICON_SVG
    icon = Path(__file__).resolve().parent.parent / 'icon.png'
    side = int(re.search(r'viewBox="0 0 (\d+) (\d+)"', TAB_ICON_SVG).group(1))
    expected = io.BytesIO()
    PILImage.open(icon).convert('RGBA').resize((side, side), PILImage.Resampling.LANCZOS).save(expected, 'PNG', optimize=True)
    embedded = base64.b64decode(TAB_ICON_SVG.split('base64,', 1)[1].split('"', 1)[0])
    assert embedded == expected.getvalue(), 'src/tab_icon.py is stale, regenerate it from icon.png'
