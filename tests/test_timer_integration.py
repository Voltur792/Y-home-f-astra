import asyncio
from src.plugin import YandexSmartHome
from src.timer_integration import integration_call


def test_timer_bridge_uses_home_client_and_propagates_action_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("SPT_INTEGRATION_DIR", str(tmp_path / "bridge"))
    monkeypatch.setattr("src.plugin.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.plugin.SETTINGS_FILE", tmp_path / "settings.json")
    calls = []
    class API:
        def get_user_info(self):
            return {"devices": [{"id": "lamp", "name": "Лампа"}], "scenarios": [{"id": "evening", "name": "Вечер"}]}
        def run_scenario(self, id):
            calls.append(("scenario", id))
        def set_device_capability(self, id, type, instance, value):
            calls.append(("device", id, type, instance, value))
            raise RuntimeError("INVALID_ACTION")
    async def run():
        plugin = YandexSmartHome()
        plugin.api = API()
        await plugin.on_config_changed({})
        try:
            devices = await asyncio.to_thread(integration_call, "home", "devices")
            assert devices[0]["name"] == "Лампа"
            scenarios = await asyncio.to_thread(integration_call, "home", "scenarios")
            assert scenarios[0]["id"] == "evening"
            assert (await asyncio.to_thread(integration_call, "home", "scenario", scenario_id="evening"))["success"]
            try:
                await asyncio.to_thread(integration_call, "home", "device", device_id="lamp", value=False)
                assert False, "Device failure must reach the scheduler"
            except RuntimeError as exc:
                assert "INVALID_ACTION" in str(exc)
            assert calls[-1][-1] is False
        finally:
            await plugin.on_shutdown()
    asyncio.run(run())
    assert not (tmp_path / "bridge" / "home.json").exists()
