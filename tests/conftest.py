import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from riffle.app import app
from riffle.identify import NullIdentifier
from riffle.pipeline import Pipeline


@pytest.fixture
def client() -> TestClient:
    # The app selects a real identifier at import time; tests must never reach a
    # model or the network unless they install their own fakes.
    app.state.pipeline = Pipeline(identifier=NullIdentifier(), status=None)
    return TestClient(app)


def make_image(fmt: str = "JPEG", gps: tuple[float, float] | None = None, size=(64, 48)) -> bytes:
    """A small solid image, optionally with an EXIF GPS IFD in real camera layout."""
    img = Image.new("RGB", size, (90, 140, 60))
    kwargs = {}
    if gps is not None:
        lat, lon = gps
        exif = Image.Exif()
        ifd = exif.get_ifd(0x8825)
        ifd[1] = "N" if lat >= 0 else "S"
        ifd[2] = _to_dms(abs(lat))
        ifd[3] = "E" if lon >= 0 else "W"
        ifd[4] = _to_dms(abs(lon))
        kwargs["exif"] = exif.tobytes()
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _to_dms(value: float) -> tuple[float, float, float]:
    deg = int(value)
    minutes_f = (value - deg) * 60
    minutes = int(minutes_f)
    seconds = round((minutes_f - minutes) * 60, 4)
    return (float(deg), float(minutes), seconds)
