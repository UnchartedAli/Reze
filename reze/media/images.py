"""
Image processing for REZE Studio.

All operations use Pillow and are real conversions: they open the source,
validate it, transform it, and write a new file. Pillow is an optional
integration, so every entry point raises :class:`MissingDependencyError` with an
install hint instead of silently returning the original file.

Telegram static stickers require a 512x512 WebP asset with transparency
preserved; :func:`make_sticker` enforces exactly that.
"""

from typing import Iterable, Optional, Tuple

from reze.config import settings
from reze.exceptions import MediaError, MissingDependencyError

try:  # pragma: no cover - exercised through the dependency checks below
    from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Image = None  # type: ignore[assignment]
    ImageDraw = ImageFont = ImageOps = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment]
    PILLOW_AVAILABLE = False

STICKER_SIZE = 512
STICKER_MAX_BYTES = 512 * 1024
MAX_PIXELS = 40_000_000


def available() -> bool:
    return PILLOW_AVAILABLE


def require_pillow() -> None:
    if not PILLOW_AVAILABLE:
        raise MissingDependencyError(
            "Pillow is required for image operations. Install it with `pip install Pillow`."
        )


def open_image(path: str):
    """Open and validate an image, rejecting decompression bombs."""
    require_pillow()
    try:
        image = Image.open(path)
        image.load()
    except UnidentifiedImageError as exc:
        raise MediaError("The file is not a supported image format.") from exc
    except OSError as exc:
        raise MediaError(f"The image could not be read: {exc}") from exc

    width, height = image.size
    if width <= 0 or height <= 0:
        raise MediaError("The image has invalid dimensions.")
    if width * height > MAX_PIXELS:
        raise MediaError(f"The image is too large ({width}x{height}); the limit is {MAX_PIXELS} pixels.")
    return image


def probe(path: str) -> dict:
    image = open_image(path)
    try:
        return {
            "width": image.size[0],
            "height": image.size[1],
            "format": image.format or "unknown",
            "mode": image.mode,
            "frames": getattr(image, "n_frames", 1),
        }
    finally:
        image.close()


# --------------------------------------------------------------------- helpers
def _flatten(image, background: Tuple[int, int, int] = (255, 255, 255)):
    """Composite transparency over a solid background (needed for JPEG)."""
    if image.mode in {"RGBA", "LA", "P"}:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, background)
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image.convert("RGB")


def _save(image, path: str, quality: Optional[int] = None, fmt: Optional[str] = None) -> str:
    extension = (fmt or path.rsplit(".", 1)[-1]).lower()
    quality = int(quality if quality is not None else settings.media_quality)
    quality = max(20, min(100, quality))
    if extension in {"jpg", "jpeg"}:
        image = _flatten(image)
        image.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    elif extension == "png":
        image.save(path, "PNG", optimize=True)
    elif extension == "webp":
        image.save(path, "WEBP", quality=quality, method=6)
    elif extension == "gif":
        image.convert("P", palette=Image.ADAPTIVE).save(path, "GIF")
    else:
        raise MediaError(f"Unsupported output format: .{extension}")
    return path


def load_font(size: int):
    require_pillow()
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _fit_font(draw, text: str, max_width: int, start_size: int = 72):
    size = max(10, start_size)
    while size > 10:
        font = load_font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 4
    return load_font(10)


def _wrap_text(draw, text: str, font, max_width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_caption_block(draw, text: str, box: Tuple[int, int, int, int], align: str = "center") -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    font = _fit_font(draw, text, width, start_size=max(18, width // 10))
    lines = _wrap_text(draw, text, font, width)
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    total_height = line_height * len(lines)
    if align == "top":
        y = y0
    elif align == "bottom":
        y = y1 - total_height
    else:
        y = y0 + (y1 - y0 - total_height) // 2
    for line in lines:
        line_box = draw.textbbox((0, 0), line, font=font)
        line_width = line_box[2] - line_box[0]
        if align == "left":
            x = x0
        elif align == "right":
            x = x1 - line_width
        else:
            x = x0 + (width - line_width) // 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=max(2, font.size // 12),
            stroke_fill=(0, 0, 0, 255),
        )
        y += line_height


# ------------------------------------------------------------------- operations
def make_sticker(source: str, destination: str) -> str:
    """Convert any supported image into a Telegram static sticker asset."""
    require_pillow()
    image = open_image(source)
    try:
        image = ImageOps.exif_transpose(image).convert("RGBA")
        image.thumbnail((STICKER_SIZE, STICKER_SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (0, 0, 0, 0))
        offset = ((STICKER_SIZE - image.width) // 2, (STICKER_SIZE - image.height) // 2)
        canvas.paste(image, offset, image)
        quality = 92
        while quality >= 40:
            canvas.save(destination, "WEBP", quality=quality, method=6, lossless=False)
            import os

            if os.path.getsize(destination) <= STICKER_MAX_BYTES:
                break
            quality -= 8
    finally:
        image.close()

    if not _is_square_sticker(destination):
        raise MediaError("The generated sticker is not a valid 512x512 WebP asset.")
    return destination


def _is_square_sticker(path: str) -> bool:
    import os

    try:
        if os.path.getsize(path) > STICKER_MAX_BYTES:
            return False
        with Image.open(path) as check:
            return check.format == "WEBP" and check.size == (STICKER_SIZE, STICKER_SIZE)
    except Exception:
        return False


def resize(
    source: str,
    destination: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    keep_aspect: bool = True,
) -> str:
    require_pillow()
    if not width and not height:
        raise MediaError("Provide a width, a height, or both.")
    if width and not 16 <= width <= 8000:
        raise MediaError("Width must be between 16 and 8000 pixels.")
    if height and not 16 <= height <= 8000:
        raise MediaError("Height must be between 16 and 8000 pixels.")

    image = open_image(source)
    try:
        image = ImageOps.exif_transpose(image)
        if keep_aspect:
            if width and height:
                image = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
            elif width:
                ratio = width / image.width
                image = image.resize((width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
            else:
                ratio = height / image.height
                image = image.resize((max(1, round(image.width * ratio)), height), Image.Resampling.LANCZOS)
        else:
            image = image.resize(
                (width or image.width, height or image.height), Image.Resampling.LANCZOS
            )
        return _save(image, destination)
    finally:
        image.close()


def compress(
    source: str,
    destination: str,
    quality: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> str:
    """Compress an image, lowering quality until it fits *max_bytes* if given."""
    require_pillow()
    image = open_image(source)
    quality = int(quality if quality is not None else settings.media_quality)
    quality = max(20, min(100, quality))
    limit = max_bytes or int(settings.media_max_output_mb) * 1024 * 1024
    try:
        image = ImageOps.exif_transpose(image)
        attempt = quality
        best = None
        while attempt >= 20:
            _save(image, destination, quality=attempt)
            best = destination
            import os

            if os.path.getsize(destination) <= limit:
                return destination
            attempt -= 10
        if best is None:
            raise MediaError("Compression failed.")
        import os

        if os.path.getsize(best) > limit:
            raise MediaError(
                f"Could not reach the requested size ({limit // 1024} KB) without heavy quality loss."
            )
        return best
    finally:
        image.close()


def add_caption(
    source: str,
    destination: str,
    text: str,
    position: str = "bottom",
    align: str = "center",
) -> str:
    require_pillow()
    text = (text or "").strip()
    if not text:
        raise MediaError("Caption text is empty.")
    if len(text) > 400:
        raise MediaError("Caption text is too long (max 400 characters).")

    image = open_image(source).convert("RGBA")
    try:
        draw = ImageDraw.Draw(image)
        width, height = image.size
        margin = max(8, width // 40)
        if position == "top":
            box = (margin, margin, width - margin, max(margin + 40, height // 3))
        elif position == "center":
            box = (margin, height // 4, width - margin, height - height // 4)
        else:
            box = (margin, max(margin + 40, height - height // 3), width - margin, height - margin)
        _draw_caption_block(draw, text, box, align=align)
        return _save(image, destination)
    finally:
        image.close()


def make_meme(source: str, destination: str, top: str = "", bottom: str = "") -> str:
    require_pillow()
    if not top and not bottom:
        raise MediaError("Provide top text, bottom text, or both.")
    image = open_image(source).convert("RGBA")
    try:
        draw = ImageDraw.Draw(image)
        width, height = image.size
        margin = max(6, width // 60)
        if top:
            _draw_caption_block(draw, top, (margin, margin, width - margin, max(margin + 40, height // 3)))
        if bottom:
            _draw_caption_block(
                draw,
                bottom,
                (margin, max(margin + 40, height - height // 3), width - margin, height - margin),
            )
        return _save(image, destination)
    finally:
        image.close()


def thumbnail(source: str, destination: str, size: int = 320) -> str:
    """Square center-cropped thumbnail."""
    require_pillow()
    size = max(64, min(int(size), 1280))
    image = open_image(source)
    try:
        image = ImageOps.exif_transpose(image)
        cropped = ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)
        return _save(cropped, destination)
    finally:
        image.close()


def to_image(source: str, destination: str, frame_index: int = 0) -> str:
    """Extract a still image from animated or multi-frame media."""
    require_pillow()
    image = open_image(source)
    try:
        frames = getattr(image, "n_frames", 1)
        if frame_index and frames > 1:
            image.seek(min(frame_index, frames - 1))
        still = ImageOps.exif_transpose(image.convert("RGB"))
        return _save(still, destination)
    finally:
        image.close()


def prepare_for_vision(source: str, max_side: int = 1024) -> Tuple[bytes, str]:
    """Return JPEG bytes and MIME type for a multimodal AI request."""
    require_pillow()
    import io

    image = open_image(source).convert("RGB")
    try:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85, optimize=True)
        return buffer.getvalue(), "image/jpeg"
    finally:
        image.close()


def is_image(path: str) -> bool:
    if not PILLOW_AVAILABLE:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def describe_output(path: str) -> str:
    """Short, safe description used in success messages."""
    image = open_image(path)
    try:
        return f"{image.width}x{image.height} {image.format}"
    finally:
        image.close()
