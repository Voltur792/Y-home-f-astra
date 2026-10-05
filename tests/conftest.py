"""Never publish test integration endpoints over a running user's plugin."""
import pytest


@pytest.fixture(autouse=True)
def isolated_integration_registry(monkeypatch, tmp_path):
    monkeypatch.setenv('SPT_INTEGRATION_DIR', str(tmp_path / 'integrations'))
    monkeypatch.setenv('YSH_COMMANDS_FILE', str(tmp_path / 'commands.json'))
