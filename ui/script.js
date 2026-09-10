document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const statusEl = document.getElementById('status');
    const refreshBtn = document.getElementById('refresh-btn');
    const deviceListEl = document.getElementById('device-list');
    const scenarioListEl = document.getElementById('scenario-list');
    const tokenInput = document.getElementById('token');
    const saveSettingsBtn = document.getElementById('save-settings');
    const settingsMessage = document.getElementById('settings-message');

    let activeTab = 'devices';
    let refreshTimer = null;
    let loadSeq = 0; // guards against out-of-order responses overwriting fresh data

    const REFRESH_MS = 10000;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
            activeTab = tab.dataset.tab;
            if (activeTab === 'devices') { loadDevices(); }
            else if (activeTab === 'scenarios') { loadScenarios(); }
        });
    });

    refreshBtn.addEventListener('click', () => {
        refreshBtn.classList.add('spinning');
        setTimeout(() => refreshBtn.classList.remove('spinning'), 500);
        if (activeTab === 'devices') { loadDevices(); }
        else if (activeTab === 'scenarios') { loadScenarios(); }
    });

    function setError(el, title, detail) {
        el.innerHTML = '<div class="placeholder error"><div class="big">⚠️</div>' + escapeHtml(title) +
            (detail ? '<div style="margin-top:6px;font-size:0.85em">' + escapeHtml(detail) + '</div>' : '') + '</div>';
    }
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    // ---------- Devices ----------
    let devicesLoadedOnce = false;

    async function loadDevices() {
        const seq = ++loadSeq;
        // Spinner only on the very first load; background refreshes are silent
        if (!devicesLoadedOnce) {
            deviceListEl.innerHTML = '<div class="placeholder"><div class="spinner"></div><div>Загрузка устройств…</div></div>';
        }
        try {
            const devices = await callBackend('yandex_home_get_devices');
            if (seq !== loadSeq) { return; } // a newer request already finished
            if (devices && devices.error === 'not_configured') {
                updateStatus(false);
                deviceListEl.innerHTML = '<div class="placeholder"><div class="big">🔌</div>Токен не настроен.<br>Откройте вкладку «Настройки».</div>';
                return;
            }
            if (devices && devices.error) { setError(deviceListEl, 'Не удалось получить устройства', devices.error); updateStatus(false); return; }
            renderDevices(devices || []);
            updateStatus(true);
            devicesLoadedOnce = true;
        } catch (e) {
            if (seq !== loadSeq) { return; }
            if (!devicesLoadedOnce) { setError(deviceListEl, 'Ошибка загрузки', e.message); }
            updateStatus(false);
        }
    }

    function iconFor(deviceType) {
        const t = deviceType || '';
        if (t.includes('socket') || t.includes('switch')) return '🔌';
        if (t.includes('sensor')) return '📊';
        if (t.includes('camera')) return '📹';
        if (t.includes('thermostat') || t.includes('humidifier')) return '🌡️';
        if (t.includes('light')) return '💡';
        if (t.includes('media_device')) return '📺';
        if (t.includes('vacuum_cleaner')) return '🤖';
        if (t.includes('kettle')) return '🫖';
        if (t.includes('coffee_maker')) return '☕';
        if (t.includes('air_conditioner')) return '❄️';
        if (t.includes('openable')) return '🚪';
        if (t.includes('curtain')) return '🪟';
        return '🏠';
    }

    function renderDevices(devices) {
        if (!devices.length) {
            deviceListEl.innerHTML = '<div class="placeholder"><div class="big">🫙</div>Устройства не найдены</div>';
            return;
        }
        const byId = {};
        devices.forEach(d => { byId[d.id] = d; });

        // Fast path: same device set — update existing cards in place, no DOM rebuild
        const existing = deviceListEl.querySelectorAll('.device-card');
        const sameSet = existing.length === devices.length &&
            Array.from(existing).every(card => byId[card.dataset.deviceId]);
        if (sameSet) {
            existing.forEach(card => updateDeviceCard(card, byId[card.dataset.deviceId]));
            return;
        }

        // Slow path: first render or the device list changed — full rebuild
        deviceListEl.innerHTML = '';
        devices.forEach(device => {
            const card = buildDeviceCard(device);
            deviceListEl.appendChild(card);
        });

        deviceListEl.querySelectorAll('.device-toggle').forEach(input => {
            input.addEventListener('change', (e) => {
                const cardEl = e.target.closest('.device-card');
                toggleDevice(cardEl.dataset.deviceId, e.target.checked, cardEl);
            });
        });
    }

    function buildDeviceCard(device) {
        const isOn = getOnOffState(device) === true;
        const hasOnOff = getOnOffState(device) !== null;
        const card = document.createElement('div');
        card.className = 'device-card' + (isOn ? ' is-on' : '');
        card.dataset.deviceId = device.id;

        const meta = [device.room_name, (device.type || '').replace('devices.types.', '')].filter(Boolean).join(' · ');
        let inner = '<div class="device-name">' + iconFor(device.type) + ' ' + escapeHtml(device.name || 'Без имени') + '</div>';
        if (meta) { inner += '<div class="device-meta">' + escapeHtml(meta) + '</div>'; }

        if (hasOnOff) {
            inner += '<div class="device-status ' + (isOn ? 'on' : 'off') + '">' + (isOn ? 'Включено' : 'Выключено') + '</div>';
            inner += '<div class="toggle-row">' +
                '<label class="switch"><input type="checkbox" class="device-toggle" ' + (isOn ? 'checked' : '') + '>' +
                '<span class="slider"></span></label>' +
                '<span class="toggle-label">' + (isOn ? 'Вкл' : 'Выкл') + '</span></div>';
        } else {
            const sensorText = sensorValue(device);
            inner += '<div class="device-status">' + (sensorText ? escapeHtml(sensorText) : 'Только просмотр') + '</div>';
        }
        card.innerHTML = inner;
        return card;
    }

    // Update one card's state in place (called on silent background refresh)
    function updateDeviceCard(card, device) {
        const state = getOnOffState(device);
        const input = card.querySelector('.device-toggle');
        if (state === null) {
            // Sensor-like device: refresh its value text
            const statusEl2 = card.querySelector('.device-status');
            const sensorText = sensorValue(device);
            if (statusEl2 && sensorText && statusEl2.textContent !== sensorText) {
                statusEl2.textContent = sensorText;
            }
            return;
        }
        const isOn = state === true;
        // Skip devices the user is currently toggling
        if (input && input.disabled) { return; }
        card.classList.toggle('is-on', isOn);
        if (input && input.checked !== isOn) { input.checked = isOn; }
        const label = card.querySelector('.toggle-label');
        if (label) { label.textContent = isOn ? 'Вкл' : 'Выкл'; }
        const statusEl2 = card.querySelector('.device-status');
        if (statusEl2) {
            const text = isOn ? 'Включено' : 'Выключено';
            if (statusEl2.textContent !== text) {
                statusEl2.textContent = text;
                statusEl2.className = 'device-status ' + (isOn ? 'on' : 'off');
            }
        }
    }

    // Yandex IoT API: on/off lives in a capability
    // { type: "devices.capabilities.on_off", state: { instance: "on", value } }
    // Returns true/false, or null when the device has no on_off capability.
    function getOnOffState(device) {
        if (!device.capabilities) { return null; }
        const cap = device.capabilities.find(c => c.type === 'devices.capabilities.on_off' && c.state && c.state.instance === 'on');
        if (!cap || !cap.state || cap.state.value === null || cap.state.value === undefined) { return null; }
        return cap.state.value === true;
    }

    function sensorValue(device) {
        if (!device.properties || !device.properties.length) { return ''; }
        const p = device.properties.find(pr => pr.state && pr.state.value !== null && pr.state.value !== undefined);
        if (!p) { return ''; }
        return p.state.instance + ': ' + p.state.value;
    }

    async function toggleDevice(deviceId, turnOn, cardEl) {
        const input = cardEl.querySelector('.device-toggle');
        const label = cardEl.querySelector('.toggle-label');
        const statusEl2 = cardEl.querySelector('.device-status');
        // Optimistic update: reflect the new state immediately
        input.disabled = true;
        label.textContent = '…';
        try {
            const result = await callBackend('yandex_home_control_device', {
                device_id: deviceId,
                capability_type: 'devices.capabilities.on_off',
                capability_instance: 'on',
                value: turnOn
            });
            if (result && result.error) {
                // Revert on failure
                input.checked = !turnOn;
                label.textContent = turnOn ? 'Выкл' : 'Вкл';
                alert('Ошибка: ' + result.error);
            } else {
                input.checked = turnOn;
                label.textContent = turnOn ? 'Вкл' : 'Выкл';
                cardEl.classList.toggle('is-on', turnOn);
                if (statusEl2) {
                    statusEl2.textContent = turnOn ? 'Включено' : 'Выключено';
                    statusEl2.className = 'device-status ' + (turnOn ? 'on' : 'off');
                }
            }
        } catch (e) {
            input.checked = !turnOn;
            label.textContent = turnOn ? 'Выкл' : 'Вкл';
            alert('Ошибка: ' + e.message);
        } finally {
            input.disabled = false;
        }
    }

    // ---------- Scenarios ----------
    let scenariosLoadedOnce = false;

    async function loadScenarios() {
        const seq = ++loadSeq;
        if (!scenariosLoadedOnce) {
            scenarioListEl.innerHTML = '<div class="placeholder"><div class="spinner"></div><div>Загрузка сценариев…</div></div>';
        }
        try {
            const scenarios = await callBackend('yandex_home_get_scenarios');
            if (seq !== loadSeq) { return; }
            if (scenarios && scenarios.error === 'not_configured') {
                updateStatus(false);
                scenarioListEl.innerHTML = '<div class="placeholder"><div class="big">🔌</div>Токен не настроен.<br>Откройте вкладку «Настройки».</div>';
                return;
            }
            if (scenarios && scenarios.error) { setError(scenarioListEl, 'Не удалось получить сценарии', scenarios.error); updateStatus(false); return; }
            renderScenarios(scenarios || []);
            updateStatus(true);
            scenariosLoadedOnce = true;
        } catch (e) {
            if (seq !== loadSeq) { return; }
            if (!scenariosLoadedOnce) { setError(scenarioListEl, 'Ошибка загрузки', e.message); }
            updateStatus(false);
        }
    }

    function renderScenarios(scenarios) {
        if (!scenarios.length) {
            scenarioListEl.innerHTML = '<div class="placeholder"><div class="big">⚡</div>Сценарии не найдены.<br>Создайте их в приложении «Дом с Алисой».</div>';
            return;
        }
        const existing = scenarioListEl.querySelectorAll('.scenario-card');
        const sameSet = existing.length === scenarios.length &&
            Array.from(existing).every((card, i) => scenarios[i] && card.dataset.scenarioId === scenarios[i].id);
        if (sameSet) { return; } // nothing changed — keep DOM as is

        scenarioListEl.innerHTML = '';
        scenarios.forEach((sc, i) => {
            const card = document.createElement('div');
            card.className = 'scenario-card';
            card.dataset.scenarioId = sc.id;
            card.innerHTML =
                '<div class="scenario-icon">' + ['⚡', '🌅', '🌙', '🎬', '🏠', '🎵', '🔒', '☕'][i % 8] + '</div>' +
                '<div class="scenario-info"><div class="scenario-name">' + escapeHtml(sc.name || 'Без названия') + '</div></div>' +
                '<button class="btn run-scenario-btn">Запустить</button>';
            card.querySelector('.run-scenario-btn').addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'Запуск…';
                try {
                    const result = await callBackend('yandex_home_run_scenario', { scenario_id: sc.id });
                    if (result && result.error) { alert('Ошибка: ' + result.error); }
                } catch (err) {
                    alert('Ошибка: ' + err.message);
                } finally {
                    btn.disabled = false;
                    btn.textContent = 'Запустить';
                }
            });
            scenarioListEl.appendChild(card);
        });
    }

    // ---------- Settings ----------
    saveSettingsBtn.addEventListener('click', async () => {
        const token = tokenInput.value.trim();
        if (!token) { settingsMessage.textContent = 'Пожалуйста, введите OAuth-токен'; settingsMessage.className = 'message error'; return; }
        saveSettingsBtn.disabled = true;
        settingsMessage.textContent = 'Проверяем токен…';
        settingsMessage.className = 'message';
        try {
            const result = await callBackend('yandex_home_save_settings', { token: token });
            if (result && result.error) {
                settingsMessage.textContent = 'Ошибка: ' + result.error;
                settingsMessage.className = 'message error';
                updateStatus(false);
            } else {
                settingsMessage.textContent = 'Подключено! Токен сохранён.';
                settingsMessage.className = 'message success';
                updateStatus(true);
                tokenInput.value = '';
                loadDevices();
            }
        } catch (e) {
            settingsMessage.textContent = 'Ошибка: ' + e.message;
            settingsMessage.className = 'message error';
            updateStatus(false);
        } finally {
            saveSettingsBtn.disabled = false;
        }
    });

    // ---------- Status & polling ----------
    function updateStatus(connected) {
        if (connected) { statusEl.textContent = 'Подключено'; statusEl.className = 'status connected'; }
        else { statusEl.textContent = 'Нет подключения'; statusEl.className = 'status disconnected'; }
    }

    async function callBackend(method, params = {}) {
        if (window.astra && window.astra.callBackend) { return await window.astra.callBackend(method, params); }
        throw new Error('Astra bridge недоступен');
    }

    function startPolling() {
        if (refreshTimer) { clearInterval(refreshTimer); }
        refreshTimer = setInterval(() => {
            if (activeTab === 'devices') { loadDevices(); }
            else if (activeTab === 'scenarios') { loadScenarios(); }
        }, REFRESH_MS);
    }

    // ---------- Init ----------
    (async () => {
        if (!window.astra) {
            setError(deviceListEl, 'Astra bridge недоступен', 'Виджет открыт вне Astra');
            return;
        }
        try {
            const st = await callBackend('yandex_home_get_status');
            updateStatus(!!(st && st.configured));
        } catch (e) { updateStatus(false); }
        loadDevices();
        startPolling();
    })();
});
