import requests
import logging
from urllib.parse import quote
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class YandexSmartHomeAPI:
    # Official Yandex Smart Home IoT API
    # https://yandex.ru/dev/dialogs/smart-home/doc/en/concepts/platform-protocol
    BASE_URL = "https://api.iot.yandex.net"
    
    def __init__(self, token: str, user_id: Optional[str] = None):
        # user_id kept for backward compatibility but is NOT used by the API:
        # the OAuth token is already bound to a single user account.
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
    @staticmethod
    def _extract_error(response: "requests.Response") -> str:
        """Build a readable error message from an API error response."""
        try:
            body = response.json()
            code = body.get("error_code") or body.get("message") or ""
            msg = body.get("error_message") or body.get("description") or ""
            details = " ".join(str(p) for p in [code, msg] if p).strip()
            if details:
                return f"HTTP {response.status_code}: {details}"
        except Exception:
            pass
        return f"HTTP {response.status_code}: {response.reason}"

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return self._validate_response(response.json())
        except requests.exceptions.RequestException as e:
            response = getattr(e, "response", None)
            if response is not None:
                raise RuntimeError(self._extract_error(response)) from e
            logger.error(f"Request to {url} failed: {e}")
            raise

    def _post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.post(url, json=data, timeout=10)
            response.raise_for_status()
            return self._validate_response(response.json())
        except requests.exceptions.RequestException as e:
            response = getattr(e, "response", None)
            if response is not None:
                raise RuntimeError(self._extract_error(response)) from e
            logger.error(f"Request to {url} failed: {e}")
            raise

    @staticmethod
    def _validate_response(body: Any) -> Dict[str, Any]:
        if not isinstance(body, dict):
            raise RuntimeError("Яндекс вернул некорректный ответ")
        if body.get("error_code") or str(body.get("status", "")).lower() == "error":
            raise RuntimeError(str(body.get("error_code") or body.get("status")) + ": " +
                               str(body.get("error_message") or body.get("message") or "Ошибка Яндекса"))
        return body

    def get_user_info(self) -> Dict[str, Any]:
        """Get full smart home info: devices, groups, scenarios in one request."""
        return self._get("/v1.0/user/info")

    def get_devices(self) -> List[Dict[str, Any]]:
        """Get list of all devices."""
        data = self.get_user_info()
        return data.get("devices", [])

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        """Get detailed info about a specific device."""
        return self._get(f"/v1.0/devices/{device_id}")

    def set_device_capability(self, device_id: str, capability_type: str, capability_instance: str, value: Any, relative: bool = False) -> bool:
        """Set a capability state for a device (batch endpoint, one device)."""
        data = {
            "devices": [
                {
                    "id": device_id,
                    "actions": [
                        {
                            "type": capability_type,
                            "state": {
                                "instance": capability_instance,
                                "value": value,
                                **({"relative": True} if relative else {}),
                            }
                        }
                    ]
                }
            ]
        }
        
        endpoint = "/v1.0/devices/actions"
        result = self._post(endpoint, data)
        
        self._validate_response(result)
        for dev in result.get("devices", []):
            if dev.get("id") != device_id:
                continue
            self._validate_response(dev.get("action_result") or {})
            for cap in dev.get("capabilities", []):
                state = cap.get("state") or {}
                if cap.get("type") == capability_type and state.get("instance") == capability_instance:
                    action = self._validate_response(state.get("action_result") or {})
                    if action.get("status") == "DONE":
                        return True
        raise RuntimeError("Яндекс не подтвердил выполнение команды устройством")

    def get_scenarios(self) -> List[Dict[str, Any]]:
        """Get list of all scenarios."""
        data = self.get_user_info()
        return data.get("scenarios", [])

    def run_scenario(self, scenario_id: str) -> bool:
        """Run a scenario."""
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("Не указан сценарий")
        endpoint = f"/v1.0/scenarios/{quote(scenario_id, safe='')}/actions"
        result = self._validate_response(self._post(endpoint))
        if result.get("status") != "ok":
            raise RuntimeError("Яндекс не подтвердил запуск сценария")
        return True
