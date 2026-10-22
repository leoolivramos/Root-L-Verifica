"""Tests for photo, image, YouTube and video media extraction and analysis."""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np

from reliability.demo import FakeLLMGateway
from reliability.extraction.media import (
    extract_image_document,
    extract_video_document,
    extract_video_keyframes,
    extract_youtube_id,
    is_image_content,
    is_video_content,
    is_youtube_url,
)


def test_youtube_url_detection():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ")
    assert is_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_youtube_url("https://example.com/noticia")
    assert not is_youtube_url("https://vimeo.com/12345")


def test_youtube_id_extraction():
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://example.com/noticia") is None


def test_image_and_video_content_type_detection():
    assert is_image_content("image/jpeg", "https://example.com/foto.jpg")
    assert is_image_content("image/png", "https://example.com/img")
    assert is_image_content("application/octet-stream", "https://example.com/foto.webp")
    assert not is_image_content("text/html", "https://example.com/article")

    assert is_video_content("video/mp4", "https://example.com/video.mp4")
    assert is_video_content("application/octet-stream", "https://example.com/clip.webm")
    assert not is_video_content("text/html", "https://example.com/video-page")


def test_video_keyframe_extraction():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name

    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(tmp_path, fourcc, 10.0, (100, 100))
        for i in range(15):
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:] = (i * 15, 50, 150)
            out.write(img)
        out.release()

        with open(tmp_path, "rb") as vf:
            v_bytes = vf.read()

        frames = extract_video_keyframes(v_bytes, max_frames=3)
        assert len(frames) == 3
        assert all(len(f) > 0 for f in frames)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def test_extract_image_document_with_vision():
    gw = FakeLLMGateway()
    dummy_bytes = b"fake-jpeg-bytes"
    doc = await extract_image_document(gw, dummy_bytes, "image/jpeg", "https://example.com/print.jpg")
    assert doc.media_type == "image"
    assert doc.media_url == "https://example.com/print.jpg"
    assert "Análise Visual" in doc.text
    assert doc.metadata["byte_size"] == len(dummy_bytes)


async def test_extract_video_document_with_vision():
    gw = FakeLLMGateway()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(tmp_path, fourcc, 10.0, (60, 60))
        for _i in range(10):
            img = np.zeros((60, 60, 3), dtype=np.uint8)
            out.write(img)
        out.release()
        with open(tmp_path, "rb") as vf:
            v_bytes = vf.read()

        doc = await extract_video_document(gw, v_bytes, "https://example.com/clip.mp4")
        assert doc.media_type == "video"
        assert doc.media_url == "https://example.com/clip.mp4"
        assert "Análise Audiovisual" in doc.text
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
