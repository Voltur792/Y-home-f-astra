(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    let entries = [], devices = [], scenarios = [], descriptors = [], editing = '', pending = false, loaded = false, generation = 0;
    const PAGE_SIZE = 3;
    let pageIndex = 0, lastState = {entries: []};
    const node = (tag, text, className = '') => { const n = document.createElement(tag); n.textContent = text; n.className = className; return n; };
    async function call(method, params = {}) {
        if (!window.astra?.callBackend) throw new Error('Откройте вкладку внутри Astra.');
        const result = await window.astra.callBackend('yandex_home_' + method, params);
        if (!result) throw new Error('Нет ответа от плагина. Повторите попытку.');
        if (result.error) throw new Error(result.error === 'not_configured' ? 'Подключите аккаунт во вкладке «Настройки».' : result.error);
        return result;
    }
    function message(text, bad = false) { $('voice-message').textContent = text; $('voice-message').className = 'message' + (bad ? ' error' : ''); }
    function lock(busy) {
        pending = busy;
        $('voice-form').querySelectorAll('input,select,textarea,button').forEach(n => { n.disabled = busy; });
        $('voice-list').querySelectorAll('button').forEach(n => { n.disabled = busy; });
        $('voice-refresh').disabled = busy; $('voice-form').setAttribute('aria-busy', String(busy));
    }
    function populateTargets(saved) {
        const select = $('voice-target'); select.replaceChildren(); VoiceFields.option(select, '', 'Выберите из списка');
        const rows = $('voice-kind').value === 'device' ? devices.filter(d => SmartHomeUI.descriptors(d).length) : scenarios;
        rows.forEach(item => VoiceFields.option(select, item.id, (item.name || 'Без названия') + (item.room_name ? ' · ' + item.room_name : '')));
        if (saved) select.value = saved.target_id;
        populateActions(saved);
    }
    function populateActions(saved) {
        const scenario = $('voice-kind').value === 'scenario';
        $('voice-action-group').hidden = scenario; $('voice-value-group').hidden = scenario;
        $('voice-action').required = !scenario; $('voice-action').replaceChildren();
        const device = devices.find(d => d.id === $('voice-target').value);
        descriptors = device ? SmartHomeUI.descriptors(device) : [];
        descriptors.forEach((d,i) => VoiceFields.option($('voice-action'), i, SmartHomeUI.human(d.instance)));
        if (saved) { const index = descriptors.findIndex(d => d.type === saved.capability_type && d.instance === saved.capability_instance); if (index >= 0) $('voice-action').value = String(index); }
        VoiceFields.fields(scenario ? null : descriptors[Number($('voice-action').value)], saved?.value);
    }
    function clearForm() {
        editing = ''; $('voice-form').reset(); $('voice-form-title').textContent = 'Новая команда';
        $('voice-save').textContent = 'Сохранить команду'; $('voice-cancel').hidden = true; populateTargets(); message('');
    }
    function edit(entry) {
        editing = entry.id; $('voice-name').value = entry.name; $('voice-phrases').value = entry.phrases.join('\n');
        $('voice-enabled').checked = entry.enabled; $('voice-kind').value = entry.target.kind;
        populateTargets(entry.target); $('voice-form-title').textContent = 'Изменить команду';
        $('voice-save').textContent = 'Сохранить изменения'; $('voice-cancel').hidden = false;
        message($('voice-target').value ? '' : 'Цель команды недоступна. Выберите её заново.', !$('voice-target').value); $('voice-phrases').focus();
    }
    function render(state) {
        lastState = state;
        entries = state.entries;
        const banner = $('voice-restart'); banner.hidden = !state.restart_required && !state.apply_error;
        banner.textContent = state.apply_error ? 'Не удалось применить команды: ' + state.apply_error + '. Исправьте настройки и сохраните снова.'
            : 'Изменения сохранены. Полностью закройте Astra, подождите несколько секунд и запустите снова, чтобы команды заработали.';
        banner.classList.toggle('error', !!state.apply_error);
        const list = $('voice-list'); list.replaceChildren();
        pageIndex = Math.min(pageIndex, Math.max(0, Math.ceil(entries.length / PAGE_SIZE) - 1));
        $('voice-page-label').textContent = entries.length ? (pageIndex + 1) + ' / ' + Math.ceil(entries.length / PAGE_SIZE) + ' · ' + entries.length + ' команд' : '0 команд';
        $('voice-prev').disabled = pageIndex === 0; $('voice-next').disabled = (pageIndex + 1) * PAGE_SIZE >= entries.length;
        if (!entries.length) { const empty = node('div', '', 'placeholder'); empty.append(node('strong', 'Команд пока нет'), node('p', 'Выберите действие и добавьте фразы в форме рядом.')); list.append(empty); }
        entries.slice(pageIndex * PAGE_SIZE, (pageIndex + 1) * PAGE_SIZE).forEach(entry => {
            const card = node('article', '', 'voice-card'), info = node('div', '', 'scenario-info');
            info.append(node('h4', entry.name, 'scenario-name'), node('p', entry.phrases.map(p => '«' + p + '»').join(' / '), 'voice-phrases'));
            const t = entry.target, val = typeof t.value === 'boolean' ? (t.value ? 'включить' : 'выключить') : typeof t.value === 'object' ? 'цвет' : SmartHomeUI.human(t.value);
            info.append(node('p', t.target_name + (t.kind === 'scenario' ? ' · запуск сценария' : ' · ' + SmartHomeUI.human(t.capability_instance) + ': ' + val), 'input-help'));
            info.append(node('span', entry.enabled ? 'Включена' : 'Отключена', 'voice-state'));
            const buttons = node('div', '', 'voice-buttons');
            const addButton = (label, handler) => { const b = node('button', label, 'btn'); b.type = 'button'; b.onclick = handler; buttons.append(b); };
            addButton('Изменить', () => { if (!pending) edit(entry); });
            addButton(entry.enabled ? 'Отключить' : 'Включить', () => change(entry, { enabled: !entry.enabled }));
            addButton('Удалить', () => {
                if (card.querySelector('.voice-delete-confirm')) return;
                const confirm = node('div', '', 'voice-delete-confirm'); confirm.append(node('span', 'Удалить эту команду? '));
                const yes = node('button', 'Удалить', 'btn'), no = node('button', 'Отмена', 'btn');
                yes.type = no.type = 'button'; yes.onclick = () => change(entry, { delete: true }); no.onclick = () => confirm.remove();
                confirm.append(yes, no); card.append(confirm); yes.focus();
            });
            card.append(info, buttons); list.append(card);
        });
    }
    async function change(entry, params) {
        if (pending) return; lock(true); message('Сохраняем…');
        try { await call('change_voice_command', { id: entry.id, ...params }); const state = await call('get_voice_commands'); render(state); if (editing === entry.id) clearForm(); message(state.restart_required ? 'Сохранено. Для изменения фраз нужен полный перезапуск Astra.' : 'Сохранено. Изменения уже действуют.'); }
        catch (error) { message(error.message, true); } finally { lock(false); }
    }
    async function show(force = false) {
        if (pending || (loaded && !force)) return;
        const current = ++generation; lock(true); message('Загружаем…');
        try {
            render(await call('get_voice_commands'));
            const results = await Promise.all([call('get_devices'), call('get_scenarios')]);
            if (current !== generation) return;
            if (!results.every(Array.isArray)) throw new Error('Не удалось получить список устройств и сценариев.');
            [devices, scenarios] = results; loaded = true;
            populateTargets(entries.find(e => e.id === editing)?.target); message('');
        } catch (error) { if (current === generation) message(error.message, true); }
        finally { if (current === generation) lock(false); }
    }
    document.addEventListener('DOMContentLoaded', () => {
        $('voice-prev').onclick = () => { if (!pending && pageIndex > 0) { pageIndex--; render(lastState); } };
        $('voice-next').onclick = () => { if (!pending && (pageIndex + 1) * PAGE_SIZE < entries.length) { pageIndex++; render(lastState); } };
        $('voice-kind').onchange = () => populateTargets(); $('voice-target').onchange = () => populateActions();
        $('voice-action').onchange = () => VoiceFields.fields(descriptors[Number($('voice-action').value)]);
        $('voice-cancel').onclick = clearForm; $('voice-refresh').onclick = () => show(true);
        $('voice-form').addEventListener('submit', async event => {
            event.preventDefault(); if (pending) return;
            const target = { kind: $('voice-kind').value, target_id: $('voice-target').value };
            if (target.kind === 'device') {
                const d = descriptors[Number($('voice-action').value)];
                if (!d) { message('Выберите доступное действие устройства.', true); return; }
                Object.assign(target, { capability_type: d.type, capability_instance: d.instance, value: VoiceFields.value(d), relative: !!d.relative });
            }
            const params = { id: editing, name: $('voice-name').value.trim(), phrases: $('voice-phrases').value.split('\n').map(p => p.trim()).filter(Boolean), target, enabled: $('voice-enabled').checked };
            lock(true); message('Сохраняем…');
            try { await call('save_voice_command', params); const state = await call('get_voice_commands'); render(state); clearForm(); message(state.restart_required ? 'Сохранено. Для новых фраз нужен полный перезапуск Astra.' : 'Сохранено. Изменения уже действуют.'); }
            catch (error) { message(error.message, true); } finally { lock(false); }
        });
    });
    window.VoiceCommands = { show, isBusy: () => pending, reset: () => { generation++; loaded = false; devices = []; scenarios = []; lock(false); clearForm(); } };
})();
