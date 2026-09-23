"""Stage 1 normalization and FR-6 geolocation resolution."""

import pytest

from aquaplot.inputs import InvalidImage, decode_image, resolve_region

from conftest import make_image

IRVINE = (33.6846, -117.8265)
SAN_DIEGO = (32.7157, -117.1611)


def test_decodes_jpeg_and_png_to_rgb():
    for fmt in ("JPEG", "PNG"):
        decoded = decode_image(make_image(fmt))
        assert decoded.format == fmt
        assert decoded.image.mode == "RGB"
        assert decoded.image.size == (64, 48)


def test_decodes_heic():
    decoded = decode_image(make_image("HEIF"))
    assert decoded.format == "HEIF"
    assert decoded.image.mode == "RGB"


def test_rejects_non_image_bytes():
    with pytest.raises(InvalidImage):
        decode_image(b"definitely not an image")


def test_rejects_unsupported_format():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="BMP")
    with pytest.raises(InvalidImage, match="unsupported"):
        decode_image(buf.getvalue())


def test_reads_exif_gps_with_hemisphere_signs():
    decoded = decode_image(make_image(gps=IRVINE))
    assert decoded.gps is not None
    lat, lon = decoded.gps
    assert lat == pytest.approx(IRVINE[0], abs=1e-4)
    assert lon == pytest.approx(IRVINE[1], abs=1e-4)
    assert lon < 0  # W reference must produce a negative longitude


def test_no_gps_when_exif_absent():
    assert decode_image(make_image()).gps is None


def test_region_precedence_exif_over_user():
    """FR-6: where the photo was taken beats where it was uploaded from."""
    region = resolve_region(IRVINE, *SAN_DIEGO)
    assert region.source == "exif"
    assert (region.lat, region.lon) == IRVINE


def test_region_falls_back_to_user_then_none():
    user = resolve_region(None, *SAN_DIEGO)
    assert user.source == "user" and (user.lat, user.lon) == SAN_DIEGO
    none = resolve_region(None, None, None)
    assert none.source == "none" and none.lat is None


def test_resolve_region_does_not_guess_a_place():
    """Turning coordinates into a jurisdiction needs the network, so it is not done here."""
    region = resolve_region(IRVINE, None, None)
    assert region.place is None and region.chain == [] and region.known is False
