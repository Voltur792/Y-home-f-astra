document.addEventListener('DOMContentLoaded', () => {
    const $ = id => document.getElementById(id);
    const tabs = [...document.querySelectorAll('.tab-btn')];
    const statusEl = $('status');
    const refreshBtn = $('refresh-btn');
    const notice = $('notice');
    const resources = {
        devices: { element: $('device-list'), method: 'yandex_home_get_devices', loaded: false, pending: null, generation: 0 },
        'read-only': { element: $('read-only-list'), method: 'yandex_home_get_devices', loaded: false, pending: null, generation: 0 },
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
                if (name === 'devices') renderDevices(items, true);
                else if (name === 'read-only') renderDevices(items, false);
                else renderScenarios(items);
                resource.loaded = true;
                resource.element.removeAttribute('data-stale');
                if (resource.lastError && notice.textContent === resource.lastError) announce('');
                resource.lastError = '';
                const count = name === 'devices' ? items.filter(isInteractiveDevice).length
                    : name === 'read-only' ? items.filter(device => !isInteractiveDevice(device)).length : items.length;
                $(name + '-count').textContent = String(count);
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

    function isInteractiveDevice(device) { return SmartHomeUI.descriptors(device).length > 0; }
    function renderDevices(devices, interactive) {
        const name = interactive ? 'devices' : 'read-only';
        const container = resources[name].element;
        devices = devices.filter(device => isInteractiveDevice(device) === interactive);
        if (!devices.length) {
            placeholder(container, interactive ? 'Устройств с командами пока нет' : 'Устройств только для просмотра нет', interactive
                ? 'Доступные для управления устройства появятся здесь.'
                : 'Датчики и устройства без доступных команд появятся здесь.');
            return;
        }
        container.querySelectorAll('.placeholder').forEach(el => el.remove());
        const existing = new Map([...container.querySelectorAll('.device-card')].map(card => [card.dataset.deviceId, card]));
        devices.forEach(device => {
            let card = existing.get(device.id);
            if (!card) { card = SmartHomeUI.createDeviceCard(device, controlDevice); container.appendChild(card); }
            else SmartHomeUI.updateDeviceCard(card, device);
            existing.delete(device.id);
        });
        existing.forEach(card => { if (!busyDevices.has(card.dataset.deviceId)) card.remove(); });
    }
    async function controlDevice(command) {
        if (saving) throw new Error('Дождитесь завершения подключения аккаунта.');
        if (busyDevices.has(command.device_id)) throw new Error('Дождитесь завершения предыдущей команды.');
        busyDevices.add(command.device_id);
        actionRevision++;
        try {
            await callBackend('yandex_home_control_device', command);
        } finally {
            actionRevision++;
            busyDevices.delete(command.device_id);
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
        document.querySelectorAll('.device-card').forEach(card => SmartHomeUI.lockDevice(card, true));
        document.querySelectorAll('.run-scenario-btn').forEach(control => { control.disabled = true; });
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
            document.querySelectorAll('.device-card').forEach(card => SmartHomeUI.lockDevice(card, false));
            document.querySelectorAll('.run-scenario-btn').forEach(control => { control.disabled = false; });
            refreshState();
        }
        if (saved) await Promise.all([load('devices'), load('scenarios')]);
    });
    $('toggle-token').addEventListener('click', () => {
        const input = $('token'), reveal = input.type === 'password';
        input.type = reveal ? 'text' : 'password';
        $('toggle-token').textContent = reveal ? 'Скрыть' : 'Показать';
        $('toggle-token').setAttribute('aria-label', reveal ? 'Скрыть токен' : 'Показать токен');
        $('toggle-token').setAttribute('aria-pressed', String(reveal));
    });
    load('devices');
    const timer = setInterval(() => { if (!document.hidden && !saving && !busyDevices.size && !busyScenarios.size) load(activeTab); }, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) load(activeTab); });
    window.addEventListener('pagehide', () => clearInterval(timer), { once: true });
});
