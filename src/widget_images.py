"""Private local background images uploaded by the user, never remote URLs."""
import base64
import hashlib
import io
import re
import warnings
import uuid

MAX_BYTES = 2 * 1024 * 1024


def image_path(directory, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{64}', ident):
        raise ValueError('Неизвестная картинка фона')
    return directory / 'widget-backgrounds' / (ident + '.png')


def store_image(directory, data):
    from PIL import Image, ImageOps
    if not isinstance(data, str) or len(data) > 4 * MAX_BYTES // 3 + 100:
        raise ValueError('Не удалось подготовить фон. Выберите картинку снова')
    if not re.match(r'^data:image/(png|jpeg|webp);base64,', data):
        raise ValueError('Поддерживаются PNG, JPG и WebP')
    try:
        raw = base64.b64decode(data.split(',', 1)[1], validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError('Не удалось подготовить фон. Выберите картинку снова')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 16_000_000:
                    raise ValueError('Выберите PNG, JPG или WebP до 16 мегапикселей')
                image.load()
                normalized = ImageOps.exif_transpose(image).convert('RGBA')
                normalized.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        encoded = io.BytesIO()
        normalized.save(encoded, format='PNG')
        content = encoded.getvalue()
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Не удалось прочитать картинку. Выберите другой файл') from exc
    ident = hashlib.sha256(content).hexdigest()
    target = image_path(directory, ident)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return image_preview(directory, ident)


def image_preview(directory, ident):
    from PIL import Image
    with Image.open(image_path(directory, ident)) as image:
        image = image.convert('RGBA')
        image.thumbnail((480, 320), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format='PNG')
    return {'image_id': ident, 'preview': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')}
