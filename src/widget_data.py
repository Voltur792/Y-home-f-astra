"""Catalog and presentation of any retrievable Yandex device property."""
import json
import math

LABELS = {'temperature': 'Температура', 'humidity': 'Влажность', 'battery_level': 'Заряд',
          'illumination': 'Освещённость', 'pressure': 'Давление', 'co2_level': 'CO₂',
          'water_leak': 'Протечка', 'motion': 'Движение', 'voltage': 'Напряжение',
          'amperage': 'Ток', 'power': 'Мощность', 'electricity_meter': 'Энергопотребление',
          'water_level': 'Уровень воды', 'water_meter': 'Расход воды', 'smoke': 'Дым', 'gas': 'Газ',
          'brightness': 'Яркость', 'temperature_k': 'Температура света', 'on': 'Питание',
          'open': 'Открытие', 'volume': 'Громкость', 'pm2.5_density': 'Частицы PM2.5', 'tvoc': 'Летучие вещества'}
UNITS = {'unit.temperature.celsius': '°C', 'unit.temperature.kelvin': 'K', 'unit.percent': '%',
         'unit.illumination.lux': 'лк', 'unit.pressure.mmhg': 'мм рт. ст.', 'unit.pressure.pascal': 'Па',
         'unit.ppm': 'ppm', 'unit.power.watt': 'Вт', 'unit.voltage.volt': 'В', 'unit.amperage.ampere': 'А',
         'unit.electricity.kilowatt_hour': 'кВт·ч', 'unit.volume.cubic_meter': 'м³', 'unit.density.mcg_m3': 'мкг/м³'}
VALUES = {'detected': 'Обнаружено', 'not_detected': 'Не обнаружено', 'opened': 'Открыто',
          'closed': 'Закрыто', 'leak': 'Протечка', 'dry': 'Сухо', 'low': 'Низкая', 'high': 'Высокая', 'auto': 'Авто'}


def device_catalog(devices):
    result = []
    for device in devices:
        for collection in ('properties', 'capabilities'):
            for prop in device.get(collection) or []:
                if prop.get('retrievable') is False:
                    continue
                params, state = prop.get('parameters') or {}, prop.get('state') or {}
                instance = params.get('instance') or state.get('instance')
                if not instance:
                    continue
                key = json.dumps([device['id'], collection, prop.get('type'), instance], separators=(',', ':'))
                unit = params.get('unit') or ''
                bounds = params.get('range') or {}
                if instance in ('humidity', 'battery_level', 'brightness', 'volume', 'open'):
                    bounds = bounds or {'min': 0, 'max': 100}
                    unit = unit or 'unit.percent'
                if instance == 'temperature':
                    unit = unit or 'unit.temperature.celsius'
                if instance == 'temperature_k':
                    unit = unit or 'unit.temperature.kelvin'
                result.append({'key': key, 'source': 'device', 'device_id': device['id'],
                               'label': (device.get('name') or 'Устройство') + ' · ' + LABELS.get(instance, instance.replace('_', ' ')),
                               'room': device.get('room_name', ''), 'unit': UNITS.get(unit, unit.removeprefix('unit.')),
                               'min': bounds.get('min'), 'max': bounds.get('max'), 'value': state.get('value')})
    return result


def reading(source, label=''):
    value = source.get('value')
    if value is None:
        text = 'Нет данных'
    elif isinstance(value, bool):
        text = 'Да' if value else 'Нет'
    elif isinstance(value, (int, float)):
        text = f'{value:,.2f}'.rstrip('0').rstrip('.').replace(',', ' ').replace('.', ',') if math.isfinite(value) else 'Нет данных'
        if text != 'Нет данных' and source.get('unit'):
            text += ' ' + source['unit']
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)[:120]
    else:
        text = VALUES.get(str(value), str(value))[:120]
    progress = None
    lo, hi = source.get('min'), source.get('max')
    if type(value) in (int, float) and math.isfinite(value) and type(lo) in (int, float) and type(hi) in (int, float) and hi > lo:
        progress = max(0, min(100, 100 * (value-lo)/(hi-lo)))
    return {'key': source['key'], 'label': label or source['label'], 'text': text, 'progress': progress,
            'available': value is not None and text != 'Нет данных'}
