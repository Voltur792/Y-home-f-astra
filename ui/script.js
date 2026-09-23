document.addEventListener('DOMContentLoaded', () => {
    const $ = id => document.getElementById(id);
    const tabs = [...document.querySelectorAll('.tab-btn')];
    const statusEl = $('status');
    const refreshBtn = $('refresh-btn');
    const notice = $('notice');
    const resources = {
        devices: { element: $('device-list'), method: 'yandex_home_get_devices', loaded: false, pending: null, generation: 0 },
        scenarios: { element: $('scenario-list'), method: 'yandex_home_get_scenarios', loaded: false, pending: null, generation: 0 }
    };
    const busyDevices = new Set();
    const busyScenarios = new Set();
    let activeTab = 'devices';
    let saving = false;
    let actionRevision = 0;
    const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const errorMessage = error => error && error.message ? error.message : String(error || 'Неизвестная ошибка');

    function announce(text, isError = false) {
        notice.textContent = text;
        notice.className = 'notice' + (isError ? ' error' : '');
        notice.hidden = !text;
    }
    function status(text, connected = false) {
        statusEl.textContent = text;
        statusEl.className = 'status ' + (connected ? 'connected' : 'disconnected');
    }
    function placeholder(element, title, detail = '', error = false) {
        element.innerHTML = '<div class="placeholder' + (error ? ' error' : '') + '"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(detail) + '</p></div>';
    }
    function refreshState() {
        const resource = resources[activeTab];
        const pending = saving || !!(resource && resource.pending);
        refreshBtn.hidden = !resource;
        refreshBtn.disabled = pending;
        refreshBtn.classList.toggle('spinning', pending);
        refreshBtn.setAttribute('aria-label', pending ? 'Обновление данных' : 'Обновить данные');
    }
    function selectTab(name) {
        activeTab = name;
        tabs.forEach(tab => {
            const selected = tab.dataset.tab === name;
            tab.classList.toggle('active', selected);
            tab.setAttribute('aria-selected', String(selected));
            tab.tabIndex = selected ? 0 : -1;
            $(tab.dataset.tab).classList.toggle('active', selected);
        });
        refreshState();
        if (resources[name]) load(name);
    }
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => selectTab(tab.dataset.tab));
        tab.addEventListener('keydown', event => {
            let next;
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
            if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
            if (event.key === 'Home') next = 0;
            if (event.key === 'End') next = tabs.length - 1;
            if (next !== undefined) {
                event.preventDefault();
                tabs[next].focus();
                selectTab(tabs[next].dataset.tab);
            }
        });
    });
    refreshBtn.addEventListener('click', () => load(activeTab));

    async function callBackend(method, params = {}) {
        if (!window.astra || typeof window.astra.callBackend !== 'function') throw new Error('Откройте вкладку внутри Astra. Подключение к приложению недоступно.');
        const response = await window.astra.callBackend(method, params);
        if (response == null) throw new Error('Нет ответа от плагина. Повторите попытку.');
        if (response.error) {
            const error = new Error(response.error === 'not_configured' ? 'Добавьте OAuth-токен во вкладке «Настройки».' : response.error);
            error.notConfigured = response.error === 'not_configured';
            throw error;
        }
        return response;
    }
    function load(name) {
        const resource = resources[name];
        if (!resource || saving) return Promise.resolve();
        // Each resource has its own request. Switching tabs cannot discard the other response.
        if (resource.pending) return resource.pending;
        const generation = resource.generation;
        const revision = actionRevision;
        if (!resource.loaded) resource.element.innerHTML = '<div class="placeholder"><span class="spinner" aria-hidden="true"></span><p>Загрузка…</p></div>';
        resource.element.setAttribute('aria-busy', 'true');
        resource.pending = (async () => {
            try {
                const items = await callBackend(resource.method);
                if (generation !== resource.generation) return;
                if (!Array.isArray(items)) throw new Error('Плагин вернул некорректный список.');
                // A read begun before a device action must never undo the action's UI state.
                if (name === 'devices' && revision !== actionRevision) return;
                if (name === 'devices') renderDevices(items);
                else renderScenarios(items);
                resource.loaded = true;
                resource.element.removeAttribute('data-stale');
                if (resource.lastError && notice.textContent === resource.lastError) announce('');
                resource.lastError = '';
                $(name + '-count').textContent = String(items.length);
                $(name + '-updated').textContent = 'Обновлено в ' + new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
                status('Подключено к Яндексу', true);
            } catch (error) {
                if (generation !== resource.generation) return;
                status(error.notConfigured ? 'Нужно подключение' : 'Нет связи с Яндексом');
                if (!resource.loaded || error.notConfigured) {
                    placeholder(resource.element, error.notConfigured ? 'Подключите свой дом' : 'Не удалось обновить данные', errorMessage(error), !error.notConfigured);
                    $(name + '-count').textContent = '—';
                } else {
                    resource.element.dataset.stale = 'true';
                }
                $(name + '-updated').textContent = 'Данные не обновлены';
                resource.lastError = errorMessage(error);
                announce(resource.lastError, true);
            } finally {
                if (generation === resource.generation) {
                    resource.pending = null;
                    resource.element.setAttribute('aria-busy', 'false');
                    refreshState();
                }
            }
        })();
        refreshState();
        return resource.pending;
    }

    function onOff(device) {
        const cap = (device.capabilities || []).find(c => c.type === 'devices.capabilities.on_off');
        return cap && cap.state && typeof cap.state.value === 'boolean' ? cap.state.value : null;
    }
    function sensorValue(device) {
        const labels = { temperature: 'Температура', humidity: 'Влажность', battery_level: 'Заряд', illumination: 'Освещённость', pressure: 'Давление', motion: 'Движение', open: 'Открытие', water_leak: 'Протечка' };
        const property = (device.properties || []).find(p => p.state && p.state.value != null);
        if (!property) return 'Только просмотр';
        const value = typeof property.state.value === 'boolean' ? (property.state.value ? 'Да' : 'Нет') : property.state.value;
        const units = { 'unit.temperature.celsius': '°C', 'unit.temperature.kelvin': 'K', 'unit.percent': '%', 'unit.illumination.lux': 'лк', 'unit.pressure.mmhg': 'мм рт. ст.', 'unit.pressure.pascal': 'Па', 'unit.pressure.bar': 'бар' };
        const unitId = property.parameters && property.parameters.unit;
        const defaults = { temperature: '°C', humidity: '%', battery_level: '%' };
        const unit = unitId ? (units[unitId] || unitId.replace(/^unit\./, '')) : (defaults[property.state.instance] || '');
        return (labels[property.state.instance] || property.state.instance) + ': ' + value + (unit && typeof property.state.value === 'number' ? ' ' + unit : '');
    }
    function updateDevice(card, device) {
        card.querySelector('.device-name').textContent = device.name || 'Без имени';
        card.querySelector('.device-meta').textContent = device.room_name || 'Без комнаты';
        if (busyDevices.has(device.id)) return;
        const state = onOff(device);
        const controls = card.querySelector('.device-controls');
        const previous = controls.querySelector('input');
        if ((state !== null) !== !!previous) {
            controls.innerHTML = state === null ? '<span class="device-status"></span>' : '<span class="device-status"></span><label class="switch"><input type="checkbox" class="device-toggle"><span class="slider"></span></label>';
            const input = controls.querySelector('input');
            if (input) input.addEventListener('change', () => toggleDevice(device.id, input.checked, card));
        }
        const input = controls.querySelector('input');
        if (input) {
            input.checked = state === true;
            input.setAttribute('aria-label', 'Питание: ' + (device.name || 'Без имени'));
        }
        card.classList.toggle('is-on', state === true);
        const label = controls.querySelector('.device-status');
        label.textContent = state === null ? sensorValue(device) : state ? 'Включено' : 'Выключено';
        label.className = 'device-status' + (state ? ' on' : '');
    }
    function renderDevices(devices) {
        const container = resources.devices.element;
        if (!devices.length) { placeholder(container, 'Устройств пока нет', 'Добавьте устройства в приложении «Дом с Алисой», затем обновите список.'); return; }
        container.querySelectorAll('.placeholder').forEach(el => el.remove());
        const existing = new Map([...container.querySelectorAll('.device-card')].map(card => [card.dataset.deviceId, card]));
        devices.forEach(device => {
            let card = existing.get(device.id);
            if (!card) {
                card = document.createElement('article');
                card.className = 'device-card';
                card.dataset.deviceId = device.id;
                card.innerHTML = '<div class="device-meta"></div><h3 class="device-name"></h3><div class="device-controls"><span class="device-status"></span></div>';
                container.appendChild(card);
            }
            existing.delete(device.id);
            updateDevice(card, device);
        });
        existing.forEach(card => { if (!busyDevices.has(card.dataset.deviceId)) card.remove(); });
    }
    async function toggleDevice(id, value, card) {
        if (saving) {
            card.querySelector('input').checked = !value;
            announce('Дождитесь завершения подключения аккаунта.');
            return;
        }
        if (busyDevices.has(id)) return;
        busyDevices.add(id);
        actionRevision++;
        const input = card.querySelector('input');
        const label = card.querySelector('.device-status');
        input.disabled = true;
        label.textContent = 'Переключение…';
        let state = !value;
        try {
            await callBackend('yandex_home_control_device', { device_id: id, capability_type: 'devices.capabilities.on_off', capability_instance: 'on', value });
            state = value;
            announce(card.querySelector('.device-name').textContent + ': ' + (value ? 'включено' : 'выключено'));
        } catch (error) { announce(errorMessage(error), true); }
        finally {
            actionRevision++;
            busyDevices.delete(id);
            input.checked = state;
            input.disabled = false;
            card.classList.toggle('is-on', state);
            label.textContent = state ? 'Включено' : 'Выключено';
            label.className = 'device-status' + (state ? ' on' : '');
        }
    }
    function renderScenarios(scenarios) {
        const container = resources.scenarios.element;
        if (!scenarios.length) { placeholder(container, 'Сценариев пока нет', 'Создайте сценарий в приложении «Дом с Алисой», затем обновите список.'); return; }
        container.querySelectorAll('.placeholder').forEach(el => el.remove());
        const existing = new Map([...container.querySelectorAll('.scenario-card')].map(card => [card.dataset.scenarioId, card]));
        scenarios.forEach(scenario => {
            let card = existing.get(scenario.id);
            if (!card) {
                card = document.createElement('article');
                card.className = 'scenario-card';
                card.dataset.scenarioId = scenario.id;
                card.innerHTML = '<div class="scenario-icon" aria-hidden="true">▷</div><div class="scenario-info"><h3 class="scenario-name"></h3><span class="scenario-result">Готов к запуску</span></div><button class="btn run-scenario-btn">Запустить</button>';
                card.querySelector('button').addEventListener('click', () => runScenario(scenario.id, card));
                container.appendChild(card);
            }
            existing.delete(scenario.id);
            card.querySelector('.scenario-name').textContent = scenario.name || 'Без названия';
            card.querySelector('button').setAttribute('aria-label', 'Запустить сценарий «' + (scenario.name || 'Без названия') + '»');
        });
        existing.forEach(card => { if (!busyScenarios.has(card.dataset.scenarioId)) card.remove(); });
    }
    async function runScenario(id, card) {
        if (saving) { announce('Дождитесь завершения подключения аккаунта.'); return; }
        if (busyScenarios.has(id)) return;
        busyScenarios.add(id);
        const button = card.querySelector('button');
        const result = card.querySelector('.scenario-result');
        button.disabled = true;
        button.textContent = 'Запуск…';
        result.textContent = 'Отправляем команду';
        try {
            await callBackend('yandex_home_run_scenario', { scenario_id: id });
            result.textContent = 'Запущен в ' + new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
            announce('Сценарий «' + card.querySelector('.scenario-name').textContent + '» запущен');
        } catch (error) {
            result.textContent = 'Не удалось запустить';
            announce(errorMessage(error), true);
        } finally {
            busyScenarios.delete(id);
            button.disabled = false;
            button.textContent = 'Запустить';
        }
    }

    $('save-settings').addEventListener('click', async () => {
        if (saving) return;
        const token = $('token').value.trim();
        const message = $('settings-message');
        if (busyDevices.size || busyScenarios.size) {
            message.textContent = 'Дождитесь завершения команды умного дома, затем повторите подключение.';
            message.className = 'message error';
            return;
        }
        if (!token) { message.textContent = 'Введите OAuth-токен'; message.className = 'message error'; $('token').focus(); return; }
        saving = true;
        $('save-settings').disabled = true;
        document.querySelectorAll('.device-toggle, .run-scenario-btn').forEach(control => { control.disabled = true; });
        message.textContent = 'Проверяем подключение…';
        message.className = 'message';
        // Old-account responses must not enter the refreshed UI after saving another token.
        Object.values(resources).forEach(resource => {
            resource.generation++;
            resource.pending = null;
            resource.element.setAttribute('aria-busy', 'false');
        });
        refreshState();
        let saved = false;
        try {
            await callBackend('yandex_home_save_settings', { token });
            saved = true;
            message.textContent = 'Подключение сохранено. Можно управлять домом.';
            message.className = 'message success';
            $('token').value = '';
            announce('');
            Object.entries(resources).forEach(([name, resource]) => {
                resource.loaded = false;
                resource.element.replaceChildren();
                $(name + '-count').textContent = '—';
                $(name + '-updated').textContent = '';
            });
            status('Подключено к Яндексу', true);
        } catch (error) { message.textContent = errorMessage(error); message.className = 'message error'; }
        finally {
            saving = false;
            $('save-settings').disabled = false;
            document.querySelectorAll('.device-toggle, .run-scenario-btn').forEach(control => { control.disabled = false; });
            refreshState();
        }
        if (saved) await Promise.all([load('devices'), load('scenarios')]);
    });
    load('devices');
    const timer = setInterval(() => { if (!document.hidden && !saving && !busyDevices.size && !busyScenarios.size) load(activeTab); }, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) load(activeTab); });
    window.addEventListener('pagehide', () => clearInterval(timer), { once: true });
});
