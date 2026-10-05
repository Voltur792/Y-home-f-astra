/* Device values reuse the same advertised schema as manual controls. */
(() => {
    const $ = id => document.getElementById(id);
    const option = (select, value, label) => {
        const node = document.createElement('option'); node.value = value; node.textContent = label; select.append(node);
    };
    function fields(d, saved) {
        const host = $('voice-value-host'); host.replaceChildren(); $('voice-value-help').textContent = '';
        if (!d) return;
        let input;
        if (d.control === 'boolean' || d.control === 'mode') {
            input = document.createElement('select');
            if (d.control === 'boolean') {
                option(input, 'true', d.instance === 'pause' ? 'Поставить на паузу' : 'Включить');
                option(input, 'false', d.instance === 'pause' ? 'Продолжить' : 'Выключить');
            } else d.options.forEach(mode => { const value = mode.value ?? mode.id; option(input, value, SmartHomeUI.human(value)); });
            if (saved != null) input.value = String(saved);
        } else if (d.control === 'range') {
            input = document.createElement('input'); input.type = 'number';
            const range = d.params.range || {}, min = range.min ?? 0, max = range.max ?? 100, step = range.precision || 1;
            input.step = step; input.min = d.relative ? -(max - min) : min; input.max = d.relative ? max - min : max;
            input.value = saved ?? (d.relative ? step : min);
            $('voice-value-help').textContent = d.relative ? 'Изменить на указанное число: плюс — увеличить, минус — уменьшить.' : 'От ' + min + ' до ' + max + ', шаг ' + step + '.';
        } else if (d.control === 'color') {
            input = document.createElement('input'); input.type = 'color'; input.value = '#ffffff';
            if (d.instance === 'rgb' && saved != null) input.value = '#' + Number(saved).toString(16).padStart(6, '0');
            if (d.instance === 'hsv' && saved) {
                const c = saved.v / 100 * saved.s / 100, h = saved.h / 60, x = c * (1 - Math.abs(h % 2 - 1)), m = saved.v / 100 - c;
                const parts = [[c,x,0],[x,c,0],[0,c,x],[0,x,c],[x,0,c],[c,0,x]][Math.floor(h) % 6];
                input.value = '#' + parts.map(v => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('');
            }
        }
        if (input) { input.id = 'voice-value'; input.required = true; host.append(input); }
    }
    function value(d) {
        const raw = $('voice-value')?.value;
        if (d.control === 'boolean') return raw === 'true';
        if (d.control === 'range') return Number(raw);
        if (d.control === 'color') {
            const rgb = parseInt(raw.slice(1), 16);
            if (d.instance === 'rgb') return rgb;
            const r = (rgb >> 16) / 255, g = ((rgb >> 8) & 255) / 255, b = (rgb & 255) / 255;
            const max = Math.max(r,g,b), min = Math.min(r,g,b), delta = max - min;
            const h = delta === 0 ? 0 : max === r ? 60 * (((g-b)/delta + 6) % 6) : max === g ? 60 * ((b-r)/delta + 2) : 60 * ((r-g)/delta + 4);
            return { h: Math.round(h), s: Math.round(max ? delta/max*100 : 0), v: Math.round(max*100) };
        }
        return raw;
    }
    window.VoiceFields = { fields, value, option };
})();
