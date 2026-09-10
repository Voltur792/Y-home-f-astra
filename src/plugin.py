"""YandexSmartHome - Astra plugin for controlling Yandex Smart Home devices."""

import ast
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from astra_plugin_sdk import Plugin, tool, ui_page, ui_call, UiContribution

logger = logging.getLogger(__name__)

# The token is stored next to the plugin, not in Astra config: the plugin's
# own settings tab explains how to obtain it, so there is nothing to fill in
# Astra.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"


def _load_settings() -> Dict[str, Any]:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read settings file: {e}")
    return {}


def _save_settings(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_saved_token() -> Optional[str]:
    return _load_settings().get("token") or None


@ui_page("yandex-smart-home", "Умный дом", "widget.html", icon_svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="currentColor" d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>')
class YandexSmartHome(Plugin):
    """Astra plugin: yandex-smart-home."""

    def __init__(self):
        super().__init__()
        self.api = None

    async def on_config_changed(self, config: Dict[str, Any]):
        """Called on start with initial config and on any config change."""
        self._ensure_api()

    def _ensure_api(self):
        """Lazily create the API client from the saved token."""
        if self.api is not None:
            return
        token = _load_saved_token()
        if not token:
            # Migration: the token used to live in the Astra plugin config
            # before settings moved into the widget. Pick it up once.
            legacy = (self.config or {}).get("token")
            if legacy:
                token = legacy
                try:
                    self._save_token(token)
                    logger.info("Migrated token from Astra config to settings file")
                except Exception as e:
                    logger.error(f"Failed to migrate token: {e}")
        if token:
            from .api import YandexSmartHomeAPI
            self.api = YandexSmartHomeAPI(token=token)
            logger.info("Yandex Smart Home API initialized")
        else:
            logger.info("No token saved yet — open the Умный дом tab to connect")

    def _save_token(self, token: str) -> None:
        data = _load_settings()
        data["token"] = token
        _save_settings(data)

    # --- UI Handlers (called from iframe via astra.callBackend) ---

    @ui_call("yandex_home_get_status")
    def ui_get_status(self, **params: Any) -> Dict[str, Any]:
        """Whether a token is configured (used by the widget on load)."""
        self._ensure_api()
        return {"configured": self.api is not None}

    @ui_call("yandex_home_get_devices")
    def ui_get_devices(self, **params: Any) -> Dict[str, Any]:
        """Get all devices (called from UI). Returns a plain list for the widget,
        enriched with room_name resolved from the rooms mapping."""
        self._ensure_api()
        if not self.api:
            return {"error": "not_configured"}
        try:
            info = self.api.get_user_info()
            devices = info.get("devices", [])
            rooms = {r.get("id"): (r.get("name") or "") for r in (info.get("rooms") or [])}
            for d in devices:
                d["room_name"] = rooms.get(d.get("room"), "")
            return devices
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return {"error": str(e)}

    @ui_call("yandex_home_control_device")
    def ui_control_device(self, **params: Any) -> Dict[str, Any]:
        """Control a device (called from UI)."""
        self._ensure_api()
        if not self.api:
            return {"error": "not_configured"}
        try:
            device_id = params.get("device_id")
            capability_type = params.get("capability_type") or "devices.capabilities.on_off"
            capability_instance = params.get("capability_instance") or "on"
            value = params.get("value")

            self.api.set_device_capability(device_id, capability_type, capability_instance, value)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to control device: {e}")
            return {"error": str(e)}

    @ui_call("yandex_home_get_scenarios")
    def ui_get_scenarios(self, **params: Any) -> Dict[str, Any]:
        """Get all scenarios (called from UI). Returns a plain list."""
        self._ensure_api()
        if not self.api:
            return {"error": "not_configured"}
        try:
            info = self.api.get_user_info()
            return info.get("scenarios", [])
        except Exception as e:
            logger.error(f"Failed to get scenarios: {e}")
            return {"error": str(e)}

    @ui_call("yandex_home_run_scenario")
    def ui_run_scenario(self, **params: Any) -> Dict[str, Any]:
        """Run a scenario (called from UI)."""
        self._ensure_api()
        if not self.api:
            return {"error": "not_configured"}
        try:
            scenario_id = params.get("scenario_id")
            self.api.run_scenario(scenario_id)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to run scenario: {e}")
            return {"error": str(e)}

    @ui_call("yandex_home_save_settings")
    def ui_save_settings(self, **params: Any) -> Dict[str, Any]:
        """Save the token to the settings file and reconnect (called from UI)."""
        try:
            token = (params.get("token") or "").strip()
            if not token:
                return {"error": "Токен обязателен"}

            # Verify the token against the API before saving
            from .api import YandexSmartHomeAPI
            probe = YandexSmartHomeAPI(token=token)
            probe.get_user_info()

            self._save_token(token)
            self.api = probe
            logger.info("Settings saved, API re-initialized")
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            return {"error": str(e)}

    # --- Home tab ---

    async def get_ui_contributions(self) -> list[UiContribution]:
        # super() returns the @ui_page tab; WITHOUT this call the tab vanishes
        # from navigation (SDK >= 0.6 keeps decorated pages ONLY in the base
        # implementation — see AGENTS.md).
        contributions = await super().get_ui_contributions()
        for c in contributions:
            if c.slot == "page.custom":
                # Without transparent=True Astra paints the iframe opaque and
                # the glass theme (transparent body CSS) has nothing to show
                # through.
                c.transparent = True
        return contributions

    # --- Tools (called from Astra chat) ---
    # NOTE 1: tool parameters must be explicit typed arguments, NOT **kwargs —
    # the SDK builds the JSON schema from the signature, and **kwargs becomes
    # a nonsense {"kwargs": "string"} required property the AI cannot fill.
    # NOTE 2: every tool keeps an optional `kwargs: str` parameter holding a
    # JSON object. Astra pins tool schemas to a chat, so an old conversation
    # keeps calling with the legacy {"kwargs": "<json>"} shape; parsing it
    # here keeps those chats working after the schema change.

    @staticmethod
    def _merge_args(kwargs: str, named: Dict[str, Any]) -> Dict[str, Any]:
        """Merge a legacy `kwargs` string argument with named args.

        Astra's model tends to pass EVERYTHING through `kwargs` as a bare
        string — a JSON object, a quoted JSON string, or the raw value itself
        (e.g. the scenario UUID with no JSON around it). Named arguments win
        over the parsed JSON; empty values in `named` are dropped so the
        string can supply them. A bare (non-JSON) string lands in `_raw`.
        """
        merged = {k: v for k, v in named.items() if v not in (None, "")}
        raw = ""
        if kwargs:
            try:
                parsed = json.loads(kwargs)
            except (json.JSONDecodeError, TypeError):
                # The AI often sends a PYTHON dict literal with single quotes
                # ("{'action':'off', ...}") — parse it too (safe: literals only).
                try:
                    parsed = ast.literal_eval(kwargs)
                except (ValueError, SyntaxError, TypeError, MemoryError):
                    parsed = None
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    merged.setdefault(k, v)
            elif isinstance(parsed, str):
                raw = parsed          # kwargs was a quoted JSON string
            elif parsed is None:
                raw = kwargs          # kwargs was not JSON at all — bare value
            else:
                raw = str(parsed)     # number/bool/… passed as JSON
        if raw:
            merged.setdefault("_raw", raw)
        return merged

    @tool("Get all devices from Yandex Smart Home. Returns {'devices': [{'id', 'name', "
          "'room_name', 'on': bool}, ...]}. Use the 'id' for control_device.")
    def tool_get_devices(self, kwargs: str = "") -> Dict[str, Any]:
        """Get all devices."""
        self._ensure_api()
        if not self.api:
            return {"error": "API not initialized. Open the Умный дом tab to connect."}
        try:
            info = self.api.get_user_info()
            devices = info.get("devices", [])
            rooms = {r.get("id"): (r.get("name") or "") for r in (info.get("rooms") or [])}
            out = []
            for d in devices:
                on = None
                for cap in d.get("capabilities", []) or []:
                    if cap.get("type") == "devices.capabilities.on_off":
                        on = (cap.get("state") or {}).get("value")
                out.append({
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "room_name": rooms.get(d.get("room"), ""),
                    "on": on,
                })
            return {"devices": out}
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return {"error": str(e)}

    # --- Smart action engine: one resolver for devices AND scenarios, so a
    # confused AI calling any tool still triggers the right action ---

    def _smart_action(self, query: str, on: bool = True,
                      prefer: str = "scenario") -> Dict[str, Any]:
        """Resolve the user's phrase to a scenario or a device and act.

        prefer='scenario' (run_scenario): try scenarios first, fall back to
        devices. prefer='device' (control_device/smart_home without
        'сценарий'): devices first, then scenarios. 'выключи…' skips
        scenarios (a scenario would turn things ON) and forces off.
        """
        q = (query or "").strip()
        if not q:
            return {"error": ("query is required — the user's request phrase, "
                              "e.g. 'включи умную лампочку', 'запусти сценарий 1 минута'")}
        q_cf = q.casefold()
        wants_scenario = "сценар" in q_cf
        # on/off may be spelled as tokens anywhere in the phrase: the AI
        # invents shapes like {"action": "turn_on"}.
        tokens = set(q_cf.replace("_", " ").replace("-", " ").split())
        wants_off = bool(tokens & {"выключи", "выключить", "выключай", "отключи",
                                   "отключить", "off", "turn off", "выкл"}) or \
            any(w in q_cf for w in ("выключи", "выключить", "отключи"))
        if wants_off:
            on = False

        order = ("scenario", "device") if prefer == "scenario" else ("device", "scenario")
        for kind in order:
            if kind == "scenario":
                if wants_off:
                    continue  # a scenario would switch things ON, not off
                sc = self._resolve_scenario(q)
                if sc is not None:
                    self.api.run_scenario(sc["id"])
                    logger.info(f"smart_action: ran scenario {sc.get('name')!r} ({sc['id']})")
                    return {"success": True, "action": "scenario_run",
                            "scenario": {"id": sc.get("id"), "name": sc.get("name")}}
            else:
                if wants_scenario:
                    continue  # the user explicitly said 'сценарий'
                dv = self._resolve_device(q)
                if dv is not None:
                    self.api.set_device_capability(dv["id"], "devices.capabilities.on_off",
                                                   "on", on)
                    logger.info(f"smart_action: device {dv.get('name')!r} -> "
                                f"{'on' if on else 'off'}")
                    return {"success": True,
                            "action": "device_on" if on else "device_off",
                            "device": {"id": dv.get("id"), "name": dv.get("name")}}
        return {"error": (f"Nothing found for {q!r} in Yandex Smart Home. "
                          "Call get_devices / get_scenarios to list what exists.")}

    @staticmethod
    def _extract_ref(args: Dict[str, Any], keys: tuple) -> str:
        """Pull the reference value the AI passed: a string, a number, an
        object like {'id': ...}, under any of `keys` (or the bare `kwargs`).
        Last resort: the AI invents argument shapes ("deviceType": "light",
        "location": "коридор", "action": "turn_on") — join every string
        value into one query and let the resolver make sense of it."""
        def _as_ref(val: Any) -> str:
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                for k in ("id", "name", "scenario_id", "device_id", "query"):
                    v = val.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            if isinstance(val, (int, float)):
                return str(val)
            return ""

        for key in keys:
            ref = _as_ref(args.get(key))
            if ref:
                return ref

        junk = ("devices.capabilities", "devices.properties")
        values: list[str] = []
        for v in args.values():
            if isinstance(v, dict):
                v = " ".join(str(x) for x in v.values())
            if not isinstance(v, str):
                continue
            v = v.strip()
            v_cf = v.casefold()
            if not v or v_cf in ("on", "off", "true", "false", "0", "1",
                                 "вкл", "выкл") or any(j in v_cf for j in junk):
                continue
            values.append(v)
        return " ".join(values)

    @staticmethod
    def _parse_on(args: Dict[str, Any], default: bool = True) -> bool:
        """Read the on/off intent from whatever key the AI used
        (value / action / state / power / on / command), tolerating
        'off', 'false', 'turn_off', 'выкл', 0, False…"""
        for key in ("value", "action", "state", "power", "on", "command"):
            v = args.get(key)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                v = v.strip().casefold().replace("_", " ").replace("-", " ")
                if v in ("off", "false", "0", "выкл", "выключить", "выключи",
                         "выключай", "отключи", "отключить", "turn off"):
                    return False
                if v in ("on", "true", "1", "вкл", "включить", "включи",
                         "включай", "turn on"):
                    return True
        return default

    @tool("MAIN tool for ANY user request about Yandex Smart Home — handles devices "
          "AND scenarios automatically. Pass the user's phrase as query, e.g. 'включи "
          "умную лампочку в коридоре', 'запусти сценарий 1 минута', 'выключи люстру'. "
          "value: 'on' or 'off' (default on). Returns what was done. Prefer this over "
          "the low-level control_device / run_scenario.")
    def tool_smart_home(self, query: str = "", value: str = "on",
                        kwargs: str = "") -> Dict[str, Any]:
        """Turn devices on/off or run a scenario, from the user's phrase."""
        self._ensure_api()
        logger.info(f"tool_smart_home called: query={query!r}, value={value!r}, "
                    f"kwargs={kwargs!r}")
        if not self.api:
            return {"error": "API not initialized. Open the Умный дом tab to connect."}
        try:
            args = self._merge_args(kwargs, {"query": query, "value": value})
            ref = self._extract_ref(args, ("query", "q", "text", "phrase", "name",
                                           "device", "scenario_id", "device_id", "_raw"))
            return self._smart_action(ref, on=self._parse_on(args, default=True),
                                      prefer="scenario")
        except Exception as e:
            logger.error(f"tool_smart_home failed: {e}")
            return {"error": str(e)}

    @tool("Low-level: turn a DEVICE on/off. Prefer smart_home for user requests. "
          "device_id from get_devices (or the exact device name), value: true=on, "
          "false=off. If the device is not found, falls back to running a SCENARIO "
          "with the same phrase.")
    def tool_control_device(self, device_id: str = "", value: Optional[bool] = None,
                            capability_type: str = "devices.capabilities.on_off",
                            capability_instance: str = "on",
                            kwargs: str = "") -> Dict[str, Any]:
        """Control a device (falls back to a scenario)."""
        self._ensure_api()
        logger.info(f"tool_control_device called: device_id={device_id!r}, "
                    f"value={value!r}, kwargs={kwargs!r}")
        if not self.api:
            return {"error": "API not initialized. Open the Умный дом tab to connect."}
        try:
            args = self._merge_args(kwargs, {
                "device_id": device_id, "value": value,
                "capability_type": capability_type,
                "capability_instance": capability_instance,
            })
            ref = self._extract_ref(args, ("device_id", "device", "name", "id",
                                           "query", "_raw"))
            if not ref:
                return {"error": ("device_id is required — the device id from "
                                  "get_devices, or the device name")}
            return self._smart_action(ref, on=self._parse_on(args, default=True),
                                      prefer="device")
        except Exception as e:
            logger.error(f"Failed to control device: {e}")
            return {"error": str(e)}

    @tool("List all Yandex Smart Home scenarios. Returns {'scenarios': [{'id', 'name'}, ...]}. "
          "Use this to find a scenario by the user's wording, then run it with run_scenario.")
    def tool_get_scenarios(self, kwargs: str = "") -> Dict[str, Any]:
        """Get all scenarios."""
        self._ensure_api()
        if not self.api:
            return {"error": "API not initialized. Open the Умный дом tab to connect."}
        try:
            info = self.api.get_user_info()
            scenarios = [
                {"id": s.get("id"), "name": s.get("name")}
                for s in (info.get("scenarios") or [])
            ]
            return {"scenarios": scenarios}
        except Exception as e:
            logger.error(f"Failed to get scenarios: {e}")
            return {"error": str(e)}

    @tool("Low-level: run a named SCENARIO. Prefer smart_home for user requests. "
          "scenario_id from get_scenarios, or the scenario name as the user said it. "
          "If no scenario matches, falls back to turning a DEVICE on/off with the "
          "same phrase.")
    def tool_run_scenario(self, scenario_id: str = "", kwargs: str = "") -> Dict[str, Any]:
        """Run a scenario (falls back to a device)."""
        self._ensure_api()
        logger.info(f"tool_run_scenario called: scenario_id={scenario_id!r}, kwargs={kwargs!r}")
        if not self.api:
            return {"error": "API not initialized. Open the Умный дом tab to connect."}
        try:
            args = self._merge_args(kwargs, {"scenario_id": scenario_id})
            ref = self._extract_ref(args, ("scenario_id", "scenario", "name", "id",
                                           "query", "_raw"))
            if not ref:
                return {"error": ("scenario_id is required — the scenario id from "
                                  "get_scenarios, or the scenario name")}
            return self._smart_action(ref, on=True, prefer="scenario")
        except Exception as e:
            logger.error(f"tool_run_scenario failed: {e}")
            return {"error": str(e)}

    # Russian filler words the user's phrasing adds around the actual name;
    # stripped before matching ("запусти двигатель" -> "двигатель").
    _FILLER_WORDS = frozenset((
        "запусти", "запустить", "запускай", "запуск", "включи", "включить",
        "включай", "выключи", "выключить", "выключай", "открой", "открыть",
        "закрой", "закрыть", "пожалуйста", "сценарий", "сценария", "сценарии",
        "устройство", "устройства", "умный", "умном", "доме", "дом", "в",
        "на", "и",
    ))

    @classmethod
    def _strip_filler(cls, ref: str) -> str:
        """Drop filler/verb words: 'запусти двигатель' -> 'двигатель'."""
        words = [w for w in ref.split()
                 if w.casefold().strip(",.!?") not in cls._FILLER_WORDS]
        return " ".join(words).strip()

    @classmethod
    def _variants(cls, ref: str) -> list[str]:
        """Match variants for a user phrase, from strict to loose:
        'выключи люстру' -> ['выключи люстру', 'люстру', 'люст'].
        The stemmed variant (last 2 chars cut from long words) absorbs
        Russian case endings: 'люстру'/'люстра', 'двигателю'/'двигатель'."""
        base = ref.strip()
        stripped = cls._strip_filler(ref)
        stemmed = (" ".join(w[:-2] if len(w) > 5 else w for w in stripped.split())
                   if stripped else "")
        out: list[str] = []
        for v in (base, stripped, stemmed):
            if v and v not in out:
                out.append(v)
        return out

    def _resolve_device(self, ref: str) -> Optional[Dict[str, Any]]:
        """Find a device by id, exact name, name substring, word stems, or room."""
        info = self.api.get_user_info()
        devices = info.get("devices", []) or []
        rooms = {r.get("id"): (r.get("name") or "") for r in (info.get("rooms") or [])}
        variants = self._variants(ref)
        for variant in variants:  # exact id
            for d in devices:
                if d.get("id") == variant:
                    return d
        for variant in variants:  # exact name, case-insensitive
            v_cf = variant.casefold()
            for d in devices:
                if (d.get("name") or "").strip().casefold() == v_cf:
                    return d
        for variant in variants:  # name contains the variant (stem absorbs cases)
            v_cf = variant.casefold()
            for d in devices:
                if v_cf in (d.get("name") or "").casefold():
                    return d
        found = self._match_by_words(devices, variants)
        if found:
            return found
        # Last resort: a word names a ROOM ('включи свет в коридоре') —
        # return the first switchable device in that room.
        for variant in reversed(variants):
            for word in variant.split():
                w = word.casefold().strip(",.!?")
                if len(w) < 5:
                    continue
                for d in devices:
                    room_cf = (rooms.get(d.get("room")) or "").casefold()
                    if len(room_cf) >= 5 and (w in room_cf or room_cf in w):
                        if any(c.get("type") == "devices.capabilities.on_off"
                               for c in d.get("capabilities") or []):
                            return d
        return None

    def _resolve_scenario(self, ref: str) -> Optional[Dict[str, Any]]:
        """Find a scenario by id, exact name, or name substring (case-insensitive)."""
        info = self.api.get_user_info()
        scenarios = info.get("scenarios", []) or []
        variants = self._variants(ref)
        for variant in variants:  # exact id
            for s in scenarios:
                if s.get("id") == variant:
                    return s
        for variant in variants:  # exact name, case-insensitive
            v_cf = variant.casefold()
            for s in scenarios:
                if (s.get("name") or "").strip().casefold() == v_cf:
                    return s
        for variant in variants:  # name contains the variant (stem absorbs cases)
            v_cf = variant.casefold()
            for s in scenarios:
                if v_cf in (s.get("name") or "").casefold():
                    return s
        return self._match_by_words(scenarios, variants)

    @staticmethod
    def _match_by_words(items: list, variants: list[str]) -> Optional[Dict[str, Any]]:
        """Last-chance match: any significant word of the phrase (stemmed)
        contained in the item name. Absorbs inflection in any word:
        'умную лампочку' -> 'лампочк' -> 'Умная лампочка'."""
        for variant in reversed(variants):  # loosest variant first
            for word in variant.split():
                if len(word) < 6:
                    continue  # too short/generic to match on
                stem = word[:-2].casefold()
                if len(stem) < 5:
                    continue
                for it in items:
                    if stem in (it.get("name") or "").casefold():
                        return it
        return None


if __name__ == "__main__":
    try:
        print("Starting YandexSmartHome plugin...", file=sys.stdout, flush=True)
        plugin = YandexSmartHome()
        print("Plugin instance created", file=sys.stdout, flush=True)
        plugin.run()
        print("Plugin run() completed", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"Failed to start plugin: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.stdout.flush()
