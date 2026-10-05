import base64
import io
from unittest.mock import Mock
import pytest
from PIL import Image
from src.widget_images import store_image, image_path, image_preview, MAX_BYTES
from src.desktop_widgets import DesktopWidgets


def picture(format='PNG', size=(24, 16)):
    output = io.BytesIO()
    Image.new('RGB', size, '#1264aa').save(output, format=format)
    mime = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp'}[format]
    return 'data:image/' + mime + ';base64,' + base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
def test_upload_normalizes_and_persists_local_copy(tmp_path, format):
    uploaded = store_image(tmp_path, picture(format))
    assert len(uploaded['image_id']) == 64
    with Image.open(image_path(tmp_path, uploaded['image_id'])) as image:
        assert image.format == 'PNG' and image.size == (24, 16)
    assert image_preview(tmp_path, uploaded['image_id']) == uploaded
    assert uploaded['preview'].startswith('data:image/png;base64,')
    assert not list(tmp_path.rglob('*.tmp'))


@pytest.mark.parametrize('data', [None, 'https://example.org/a.png',
    'data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,bad!',
    'data:image/png;base64,' + base64.b64encode(b'not an image').decode(),
    'data:image/png;base64,' + 'a' * (4 * MAX_BYTES // 3 + 100)],
    ids=['null', 'url', 'svg', 'invalid-base64', 'invalid-content', 'too-large'])
def test_invalid_upload_does_not_write_files(tmp_path, data):
    with pytest.raises(ValueError):
        store_image(tmp_path, data)
    assert not list(tmp_path.iterdir())


def test_image_dimension_limit(tmp_path):
    with pytest.raises(ValueError):
        store_image(tmp_path, picture(size=(4001, 4000)))
    assert not list(tmp_path.iterdir())


def test_widget_keeps_image_across_restart_and_can_remove_it(tmp_path):
    uploaded = store_image(tmp_path, picture())
    manager = DesktopWidgets(tmp_path, Mock(return_value=[]), lambda: 'test')
    manager.ensure = Mock()
    manager.metrics.read = Mock(return_value={'ram_percent': 37})
    widget = manager.save({'items': [{'key': 'system:ram_percent'}],
        'background_image': uploaded['image_id'], 'refresh_seconds': 1})['widgets'][0]
    manager.sessions[widget['id']] = 'session'
    snapshot = manager.snapshot(widget['id'], 'session')
    assert snapshot['settings']['background_path'] == str(image_path(tmp_path, uploaded['image_id']))
    assert 'preview' not in snapshot['settings'] and 'account' not in snapshot['settings']
    fresh = DesktopWidgets(tmp_path, manager.devices, manager.account)
    assert fresh.state()['widgets'][0]['background_image'] == uploaded['image_id']
    assert fresh.state()['widgets'][0]['refresh_seconds'] == 1
    manager.save({'background_image': ''}, widget['id'])
    assert 'background_path' not in manager.snapshot(widget['id'], 'session')['settings']
    assert image_path(tmp_path, uploaded['image_id']).is_file()


@pytest.mark.parametrize('ident', ['../settings', 'https://example.org', 'a' * 64])
def test_only_existing_managed_images_can_be_selected(tmp_path, ident):
    manager = DesktopWidgets(tmp_path, lambda: [], lambda: 'test')
    manager.ensure = Mock()
    with pytest.raises(ValueError):
        manager.save({'items': [{'key': 'system:ram_percent'}], 'background_image': ident})
    assert manager.state()['widgets'] == []
