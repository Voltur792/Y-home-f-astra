/* Shared, schema-driven device controls and sensor presentation. No API calls here. */
(() => {
    'use strict';
    const labels = {
        on: 'Питание', backlight: 'Подсветка', controls_locked: 'Блокировка управления', ionization: 'Ионизация', keep_warm: 'Поддержание тепла', mute: 'Без звука', oscillation: 'Вращение', pause: 'Пауза', work_speed: 'Скорость', thermostat: 'Режим климата', program: 'Программа', input_source: 'Источник', fan_speed: 'Скорость вентилятора', swing: 'Направление воздуха', cleanup_mode: 'Режим уборки', tea_mode: 'Вид чая', coffee_mode: 'Вид кофе', dishwashing: 'Мойка', brightness: 'Яркость', channel: 'Канал', humidity: 'Влажность', temperature: 'Температура', volume: 'Громкость', open: 'Открытие', temperature_k: 'Температура света', rgb: 'Цвет', hsv: 'Цвет', scene: 'Световой эффект', battery_level: 'Заряд', illumination: 'Освещённость', pressure: 'Давление', motion: 'Движение', water_leak: 'Протечка', button: 'Кнопка', vibration: 'Вибрация', smoke: 'Дым', gas: 'Газ', co2_level: 'CO₂', tvoc: 'Летучие вещества', electricity_meter: 'Энергопотребление', power: 'Мощность', voltage: 'Напряжение', amperage: 'Ток', water_level: 'Уровень воды', water_meter: 'Расход воды', heat_meter: 'Тепло', food_level: 'Уровень корма', pm1_density: 'Частицы PM1', 'pm2.5_density': 'Частицы PM2.5', pm10_density: 'Частицы PM10', filter_life: 'Ресурс фильтра'
    };
    const values = { auto: 'Авто', eco: 'Экономичный', quiet: 'Тихий', turbo: 'Турбо', cool: 'Охлаждение', heat: 'Обогрев', dry: 'Осушение', fan_only: 'Вентиляция', preheat: 'Преднагрев', low: 'Низкая', medium: 'Средняя', high: 'Высокая', min: 'Минимум', max: 'Максимум', normal: 'Обычный', fast: 'Быстрый', slow: 'Медленный', one: 'Первый', two: 'Второй', three: 'Третий', four: 'Четвёртый', five: 'Пятый', horizontal: 'Горизонтально', vertical: 'Вертикально', stationary: 'Неподвижно', click: 'Одно нажатие', double_click: 'Двойное нажатие', long_press: 'Долгое нажатие', tilt: 'Наклон', fall: 'Падение', vibration: 'Вибрация', detected: 'Обнаружено', not_detected: 'Не обнаружено', opened: 'Открыто', closed: 'Закрыто', leak: 'Протечка', dry_water: 'Сухо', high_water: 'Высокий уровень', low_water: 'Низкий уровень', empty: 'Пусто', full: 'Полный', very_low: 'Очень низкий', very_high: 'Очень высокий', red: 'Красный', green: 'Зелёный', blue: 'Синий', white: 'Белый', sunrise: 'Рассвет', sunset: 'Закат', night: 'Ночь', reading: 'Чтение', party: 'Вечеринка', romance: 'Романтика', alarm: 'Тревога', siren: 'Сирена', candle: 'Свеча', fire: 'Огонь', ocean: 'Океан', forest: 'Лес', jungle: 'Джунгли', movie: 'Кино', relax: 'Отдых', rest: 'Отдых', fantasy: 'Фантазия' };
    const units = { 'unit.temperature.celsius': '°C', 'unit.temperature.kelvin': 'K', 'unit.percent': '%', 'unit.illumination.lux': 'лк', 'unit.pressure.mmhg': 'мм рт. ст.', 'unit.pressure.pascal': 'Па', 'unit.pressure.bar': 'бар', 'unit.density.mcg_m3': 'мкг/м³', 'unit.ppm': 'ppm', 'unit.power.watt': 'Вт', 'unit.voltage.volt': 'В', 'unit.amperage.ampere': 'А', 'unit.electricity.kilowatt_hour': 'кВт·ч', 'unit.volume.cubic_meter': 'м³', 'unit.gas_density.ppm': 'ppm', 'unit.heat.gigacalorie': 'Гкал' };
    let sequence = 0;
    const text = (tag, className, value) => { const node = document.createElement(tag); node.className = className; if (value != null) node.textContent = String(value); return node; };
    const human = value => labels[value] || values[value] || String(value || '').replace(/_/g, ' ');
    const number = value => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(value);
    function unitFor(instance, parameters = {}) {
        if (parameters.unit) return units[parameters.unit] || parameters.unit.replace(/^unit\./, '');
        return ({ temperature: '°C', temperature_k: 'K', brightness: '%', humidity: '%', battery_level: '%', volume: '%', open: '%' })[instance] || '';
    }
    function propertyText(property) {
        const instance = property.parameters?.instance || property.state?.instance || '';
        const raw = property.state?.value;
        let value = 'Нет данных';
        if (raw != null) {
            if (typeof raw === 'number') value = number(raw) + (unitFor(instance, property.parameters) ? ' ' + unitFor(instance, property.parameters) : '');
            else if (typeof raw === 'boolean') value = raw ? 'Да' : 'Нет';
            else if (instance === 'water_leak' && raw === 'dry') value = 'Сухо';
            else value = values[raw] || String(raw).replace(/_/g, ' ');
        }
        return { key: property.type + ':' + instance, label: human(instance) || 'Показатель', value, instance };
    }
    function renderSensors(container, device) {
        const properties = (device.properties || []).map(propertyText);
        container.replaceChildren();
        properties.forEach(property => {
            const row = text('div', 'sensor-reading');
            row.append(text('dt', 'sensor-label', property.label), text('dd', 'sensor-value', property.value));
            row.dataset.propertyKey = property.key;
            container.append(row);
        });
        container.hidden = !properties.length;
    }
    function descriptors(device) {
        const result = [];
        for (const cap of device.capabilities || []) {
            const kind = (cap.type || '').replace('devices.capabilities.', '');
            const params = cap.parameters || {};
            const push = (instance, control, options = {}) => result.push({ key: cap.type + ':' + instance, type: cap.type, instance, control, params, retrievable: cap.retrievable !== false, ...options });
            if (kind === 'on_off') push('on', 'boolean', { split: params.split === true });
            else if (kind === 'toggle') push(params.instance || cap.state?.instance, 'boolean');
            else if (kind === 'range') push(params.instance || cap.state?.instance, 'range', { relative: params.random_access === false });
            else if (kind === 'mode' && Array.isArray(params.modes) && params.modes.length) push(params.instance || cap.state?.instance, 'mode', { options: params.modes });
            else if (kind === 'color_setting') {
                if (params.color_model) push(params.color_model, 'color');
                if (params.temperature_k) push('temperature_k', 'range', { params: { range: params.temperature_k, unit: 'unit.temperature.kelvin' } });
                if (params.color_scene?.scenes?.length) push('scene', 'mode', { options: params.color_scene.scenes });
            } else if (kind === 'ir_remote') {
                // OAuth IoT metadata exposes the remote capability, but not its
                // custom button list. Do not invent actions from an empty schema.
                continue;
            }
        }
        return result.filter(item => item.instance);
    }
    function stateFor(device, descriptor) {
        const cap = (device.capabilities || []).find(item => item.type === descriptor.type && item.state?.instance === descriptor.instance);
        return descriptor.retrievable ? cap?.state?.value : undefined;
    }
    function rgbToHex(value) {
        const rgb = Math.max(0, Math.min(0xffffff, Number(value) || 0));
        return '#' + rgb.toString(16).padStart(6, '0');
    }
    function hsvToRgb(hsv) {
        if (!hsv || typeof hsv !== 'object') return '#ffffff';
        const h = hsv.h / 60, s = hsv.s / 100, v = hsv.v / 100;
        const c = v * s, x = c * (1 - Math.abs(h % 2 - 1)), m = v - c;
        const sectors = [[c,x,0],[x,c,0],[0,c,x],[0,x,c],[x,0,c],[c,0,x]];
        return '#' + (sectors[Math.floor(h) % 6] || sectors[0]).map(n => Math.round((n+m)*255).toString(16).padStart(2,'0')).join('');
    }
    function hexToHsv(hex) {
        const parts = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255), [r,g,b] = parts;
        const max = Math.max(...parts), min = Math.min(...parts), d = max - min;
        let h = d === 0 ? 0 : max === r ? ((g-b)/d)%6 : max === g ? (b-r)/d+2 : (r-g)/d+4;
        return { h: Math.round((h*60+360)%360), s: Math.round(max === 0 ? 0 : d/max*100), v: Math.round(max*100) };
    }
    function makeControl(card, descriptor, command) {
        const row = text('div', 'capability capability-' + descriptor.control);
        row.dataset.capabilityKey = descriptor.key;
        const id = 'home-control-' + (++sequence);
        const label = text('label', 'capability-label', human(descriptor.instance));
        label.htmlFor = id;
        row.append(label);
        const feedback = text('span', 'capability-state');
        const interactive = [];
        let dirty = false, current;
        const add = element => { interactive.push(element); return element; };
        const submit = async (value, relative = false) => {
            if (card._busy || card._locked) return;
            setDeviceBusy(card, true);
            card.querySelector('.device-message').textContent = 'Отправляем команду…';
            try {
                await command({ device_id: card.dataset.deviceId, capability_type: descriptor.type, capability_instance: descriptor.instance, value, relative });
                dirty = false;
                // API acknowledgement is not telemetry, especially for split/non-retrievable actions.
                if (descriptor.retrievable && !relative && !descriptor.split) current = value;
                sync(current, true);
                card.querySelector('.device-message').textContent = descriptor.retrievable && !descriptor.split ? 'Команда выполнена' : 'Команда отправлена';
            } catch (error) {
                dirty = false;
                sync(current, true);
                card.querySelector('.device-message').textContent = error.message || 'Не удалось выполнить команду. Повторите попытку.';
            } finally { setDeviceBusy(card, false); }
        };
        let sync = value => { current = value; };
        if (descriptor.control === 'boolean') {
            const box = text('div', 'boolean-control');
            const input = add(document.createElement('input')); input.type = 'checkbox'; input.id = id; input.className = 'device-toggle';
            const toggle = text('label', 'switch'); toggle.htmlFor = id; toggle.append(input, text('span', 'slider'));
            const explicit = text('div', 'explicit-buttons');
            for (const [name, value] of [['Включить',true],['Выключить',false]]) {
                const button = add(text('button', 'btn compact', name)); button.type = 'button'; button.setAttribute('aria-label', name + ': ' + human(descriptor.instance)); button.addEventListener('click', () => submit(value)); explicit.append(button);
            }
            input.addEventListener('change', () => submit(input.checked));
            box.append(feedback,toggle,explicit); row.append(box);
            sync = (value, force = false) => {
                if (dirty && !force) return; current = value;
                const known = typeof value === 'boolean' && !descriptor.split;
                toggle.hidden = !known; explicit.hidden = known;
                input.checked = value === true;
                feedback.textContent = known ? (value ? 'Включено' : 'Выключено') : 'Состояние не сообщается';
                if (descriptor.instance === 'on') card.classList.toggle('is-on', value === true);
            };
        } else if (descriptor.control === 'mode') {
            const select = add(document.createElement('select')); select.id = id;
            const empty = text('option', '', 'Выберите значение'); empty.value = ''; empty.disabled = true; select.append(empty);
            descriptor.options.forEach(option => { const value = option.value ?? option.id; const item = text('option','',option.name || values[value] || String(value).replace(/_/g,' ')); item.value = value; select.append(item); });
            select.addEventListener('change', () => { if (select.value) submit(select.value); });
            row.append(select);
            sync = value => { current = value; select.value = value == null ? '' : String(value); if (select.selectedIndex < 0) select.value = ''; };
        } else if (descriptor.control === 'range') {
            const range = descriptor.params.range || {};
            const precision = Number(range.precision) > 0 ? Number(range.precision) : 1;
            const unitsText = unitFor(descriptor.instance, descriptor.params);
            if (descriptor.relative) {
                const group = text('div', 'relative-control');
                for (const [symbol, delta] of [['−',-precision],['+',precision]]) {
                    const button = add(text('button','btn step-button',symbol)); button.type='button'; button.setAttribute('aria-label',(delta<0?'Уменьшить: ':'Увеличить: ')+human(descriptor.instance)); button.addEventListener('click',()=>submit(delta,true)); group.append(button);
                }
                group.insertBefore(feedback,group.lastChild); row.append(group);
                sync = value => { current=value; feedback.textContent = value == null ? 'Относительное управление' : number(value)+(unitsText?' '+unitsText:''); };
            } else {
                const min = Number.isFinite(range.min) ? range.min : null, max = Number.isFinite(range.max) ? range.max : null;
                const input = add(document.createElement('input')); input.id=id; input.type = min !== null && max !== null ? 'range' : 'number';
                if(min!==null)input.min=String(min); if(max!==null)input.max=String(max); input.step=String(precision);
                const group = text('div','range-control'); const apply = add(text('button','btn compact','Применить')); apply.type='button'; apply.dataset.requiresDraft='true'; apply.disabled=true;
                const output = text('output','range-value'); output.htmlFor=id;
                input.addEventListener('input',()=>{dirty=true;output.textContent=input.value+(unitsText?' '+unitsText:'');apply.disabled=false;});
                apply.addEventListener('click',()=>{
                    const value=Number(input.value);
                    if (!input.value || !Number.isFinite(value) || (min!==null&&value<min) || (max!==null&&value>max)) { card.querySelector('.device-message').textContent='Укажите значение в допустимом диапазоне.'; input.focus(); return; }
                    submit(value);
                });
                group.append(input,output,apply); row.append(group,feedback);
                sync=(value,force=false)=>{if(dirty&&!force)return;current=value;input.value=value==null?(min===null?'':String(min)):String(value);output.textContent=value==null?'—':number(value)+(unitsText?' '+unitsText:'');feedback.textContent=value==null?'Состояние не сообщается':'';apply.disabled=!dirty;};
            }
        } else if (descriptor.control === 'color') {
            const group=text('div','color-control'); const input=add(document.createElement('input')); input.type='color';input.id=id;
            const apply=add(text('button','btn compact','Применить цвет')); apply.type='button';apply.dataset.requiresDraft='true';apply.disabled=true;
            input.addEventListener('input',()=>{dirty=true;apply.disabled=false;});
            apply.addEventListener('click',()=>submit(descriptor.instance==='hsv'?hexToHsv(input.value):parseInt(input.value.slice(1),16)));
            group.append(input,apply);row.append(group,feedback);
            sync=(value,force=false)=>{if(dirty&&!force)return;current=value;input.value=descriptor.instance==='hsv'?hsvToRgb(value):rgbToHex(value??0xffffff);feedback.textContent=value==null?'Текущий цвет не сообщается':'';apply.disabled=!dirty;};
        } else { row.append(text('p','capability-state','Управление этим параметром пока недоступно')); }
        return { row, sync, interactive, hasDraft: () => dirty };
    }
    function createDeviceCard(device, command) {
        const card=text('article','device-card');card.dataset.deviceId=device.id;card._command=command;card._controls=[];
        card.append(text('div','device-meta'),text('h3','device-name'),text('div','capabilities'),text('dl','sensor-readings'),text('p','device-message'));
        card.querySelector('.device-message').setAttribute('role','status');
        updateDeviceCard(card,device);return card;
    }
    function updateDeviceCard(card,device) {
        card.querySelector('.device-name').textContent=device.name||'Без имени';
        card.querySelector('.device-meta').textContent=device.room_name||'Без комнаты';
        renderSensors(card.querySelector('.sensor-readings'),device);
        if(card._busy)return;
        const controls=descriptors(device), signature=JSON.stringify(controls);
        if(card._signature!==signature && !card._controls.some(control=>control.hasDraft())) {
            card._signature=signature;
            card._controls=controls.map(descriptor=>({...makeControl(card,descriptor,card._command),descriptor}));
            card.querySelector('.capabilities').replaceChildren(...card._controls.map(control=>control.row));
        }
        card._controls.forEach(control=>control.sync(stateFor(device,control.descriptor)));
        if (!controls.length && !device.properties?.length) {
            const hasRemote = (device.capabilities || []).some(cap => cap.type === 'devices.capabilities.ir_remote');
            card.querySelector('.device-message').textContent = hasRemote
                ? 'ИК-пульт найден. Список его кнопок не передаётся через API-подключение Яндекса.'
                : 'Нет доступных параметров';
        } else if ((device.capabilities || []).some(cap => cap.type === 'devices.capabilities.ir_remote')) {
            card.querySelector('.device-message').textContent = 'ИК-пульт обнаружен, но его пользовательские кнопки недоступны через API-подключение Яндекса.';
        }
    }
    function setDeviceBusy(card,busy) {
        card._busy=busy;card.setAttribute('aria-busy',String(busy));
        card._controls.forEach(control=>control.interactive.forEach(input=>{input.disabled=busy||!!card._locked||(input.dataset.requiresDraft==='true'&&!control.hasDraft());}));
    }
    function lockDevice(card,locked) {card._locked=locked;setDeviceBusy(card,!!card._busy);}
    window.SmartHomeUI={createDeviceCard,updateDeviceCard,setDeviceBusy,lockDevice,propertyText,renderSensors,human,descriptors};
})();

