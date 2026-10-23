"""Tests for forensic media analysis (EXIF, software detection, hashes, GPS)."""

from __future__ import annotations

import io

from PIL import Image

from reliability.extraction.forensics import analyze_image_forensics, analyze_video_forensics


def test_analyze_image_forensics_clean_image():
    # Create simple in-memory PNG
    img = Image.new("RGB", (320, 240), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()

    result = analyze_image_forensics(raw, filename="teste.png")
    assert result["media_type"] == "image"
    assert result["dimensions"]["width"] == 320
    assert result["dimensions"]["height"] == 240
    assert len(result["sha256"]) == 64
    assert len(result["md5"]) == 32
    assert result["is_edited"] is False
    assert result["software_detected"] is None


def test_analyze_image_forensics_photoshop_detection():
    # Create image with mock EXIF containing software signature
    img = Image.new("RGB", (200, 200), color=(50, 50, 50))
    exif = img.getexif()
    # Tag 305 is Software in EXIF specification
    exif[305] = "Adobe Photoshop 2024 (Windows)"
    exif[271] = "Canon"  # Make
    exif[272] = "EOS R5"  # Model

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw = buf.getvalue()

    result = analyze_image_forensics(raw, filename="montagem.jpg")
    assert result["has_exif"] is True
    assert result["is_edited"] is True
    assert "Adobe Photoshop" in result["software_detected"]
    assert result["camera_make"] == "Canon"
    assert result["camera_model"] == "EOS R5"
    assert len(result["alerts"]) >= 1


def test_analyze_video_forensics_dummy():
    # Test graceful handling on invalid or small video bytes
    result = analyze_video_forensics(b"dummy_video_bytes_12345678", filename="fake.mp4")
    assert result["media_type"] == "video"
    assert len(result["sha256"]) == 64
    assert result["size_bytes"] == len(b"dummy_video_bytes_12345678")
