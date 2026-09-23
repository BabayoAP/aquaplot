"""Stage 1 input normalization (PRD §6.1) and geolocation resolution (FR-6).

Decoding lives here so the API layer never touches Pillow directly, and so the
pipeline receives an already-validated RGB image plus a resolved region.

Geolocation precedence follows FR-6 exactly: EXIF GPS first, then coordinates the
user supplied (the browser's geolocation API, in practice), then "unknown". EXIF
wins over the browser because EXIF records where the *photo* was taken, while the
browser records where the *upload* happens, and those differ for any photo taken
earlier in the field - and for a stream assessment the difference is the whole
point, since the reading belongs to the reach, not to the sofa it was uploaded from.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from fractions import Fraction

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .schema import Region

register_heif_opener()

SUPPORTED_FORMATS = {"JPEG", "PNG", "HEIF"}  # JPEG / PNG / HEIC, the three a phone produces
MAX_IMAGE_BYTES = 25 * 1024 * 1024

_GPS_IFD = 0x8825
_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4


class InvalidImage(ValueError):
    """Raised for input that is not a decodable JPEG/PNG/HEIC."""


@dataclass(frozen=True, slots=True)
class DecodedImage:
    image: Image.Image  # RGB, orientation applied
    format: str
    gps: tuple[float, float] | None


def decode_image(data: bytes) -> DecodedImage:
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage(f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage("could not decode image; JPEG, PNG or HEIC required") from exc
    fmt = img.format or ""
    if fmt not in SUPPORTED_FORMATS:
        raise InvalidImage(f"unsupported image format {fmt or 'unknown'}; JPEG, PNG or HEIC required")
    gps = _read_gps(img)
    # Orientation must be applied before any detector sees the pixels, otherwise a
    # phone photo taken in portrait arrives sideways and bounding boxes are wrong.
    img = ImageOps.exif_transpose(img) or img
    return DecodedImage(image=img.convert("RGB"), format=fmt, gps=gps)


def _read_gps(img: Image.Image) -> tuple[float, float] | None:
    try:
        gps = img.getexif().get_ifd(_GPS_IFD)
    except Exception:  # malformed EXIF must never fail the request (PRD §5.2 degrade gracefully)
        return None
    if not gps or _GPS_LAT not in gps or _GPS_LON not in gps:
        return None
    try:
        lat = _dms_to_degrees(gps[_GPS_LAT], gps.get(_GPS_LAT_REF, "N"))
        lon = _dms_to_degrees(gps[_GPS_LON], gps.get(_GPS_LON_REF, "E"))
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _dms_to_degrees(dms, ref) -> float:
    deg, minutes, seconds = (float(Fraction(x)) for x in dms)
    value = deg + minutes / 60 + seconds / 3600
    ref = ref.decode() if isinstance(ref, bytes) else str(ref)
    return -value if ref.upper() in ("S", "W") else value


def resolve_region(
    exif_gps: tuple[float, float] | None,
    user_lat: float | None,
    user_lon: float | None,
) -> Region:
    """FR-6 precedence: EXIF, then user-supplied, then unknown.

    This function only decides *which* coordinates to believe. Turning them into a
    place is ``places.PlaceResolver``'s job and needs the network, so it happens in
    the pipeline where a failure can degrade gracefully rather than here, where it
    would fail the request.
    """
    if exif_gps is not None:
        lat, lon = exif_gps
        return Region(source="exif", lat=lat, lon=lon)
    if user_lat is not None and user_lon is not None:
        return Region(source="user", lat=user_lat, lon=user_lon)
    return Region(source="none")
