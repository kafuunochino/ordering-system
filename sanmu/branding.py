"""Logo 导入：验证图片、修正方向、缩小到可保存尺寸，原文件不受影响。"""

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from .money import ValidationError

MAX_LOGO_BYTES = 10 * 1024 * 1024
MAX_LOGO_PIXELS = 25_000_000


def import_logo(path: Path | str) -> bytes:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_LOGO_BYTES:
        raise ValidationError("请选择不超过 10 MB 的 Logo 图片。")
    reader = QImageReader(str(path))
    if bytes(reader.format()).lower() not in (b"png", b"jpeg", b"jpg", b"bmp", b"webp"):
        raise ValidationError("Logo 支持 PNG、JPG、BMP、WebP 图片。")
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_LOGO_PIXELS:
        raise ValidationError("Logo 图片尺寸无效或过大，请使用 2500 万像素以内的图片。")
    reader.setAutoTransform(True)
    if max(size.width(), size.height()) > 512:
        reader.setScaledSize(size.scaled(QSize(512, 512), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValidationError("无法读取这张 Logo 图片，请换一张有效图片。")
    if max(image.width(), image.height()) > 512:
        image = image.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValidationError("Logo 图片保存失败。")
    return bytes(data)


def logo_image(data: bytes) -> QImage:
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        raise ValidationError("已保存的 Logo 图片无法读取，请重新上传。")
    return image
