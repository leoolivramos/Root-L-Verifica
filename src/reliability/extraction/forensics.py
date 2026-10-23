"""Forensic media inspection: EXIF metadata, editing software detection, cryptographic hashes, GPS and ELA."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from datetime import datetime
from typing import Any

import cv2
from PIL import ExifTags, Image

EDITING_SOFTWARE_KEYWORDS = (
    "photoshop",
    "lightroom",
    "canva",
    "gimp",
    "snapseed",
    "photopea",
    "vsco",
    "pixlr",
    "picsart",
    "midjourney",
    "stable diffusion",
    "dall-e",
    "adobe",
    "affinity",
    "corel",
    "facetune",
    "inshot",
    "capcut",
)


def _format_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"


def _dms_to_decimal(dms: Any, ref: str) -> float | None:
    try:
        if isinstance(dms, (list, tuple)) and len(dms) >= 3:
            deg = float(dms[0])
            minute = float(dms[1])
            sec = float(dms[2])
            val = deg + (minute / 60.0) + (sec / 3600.0)
            if ref.upper() in ("S", "W"):
                val = -val
            return round(val, 6)
    except Exception:
        return None
    return None


def analyze_image_forensics(raw_bytes: bytes, filename: str = "imagem") -> dict[str, Any]:
    """Extract cryptographic integrity, camera EXIF, editing software signatures, and GPS coordinates."""
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    md5 = hashlib.md5(raw_bytes).hexdigest()
    size_bytes = len(raw_bytes)
    size_formatted = _format_size(size_bytes)

    out: dict[str, Any] = {
        "media_type": "image",
        "filename": filename,
        "sha256": sha256,
        "md5": md5,
        "size_bytes": size_bytes,
        "size_formatted": size_formatted,
        "analysis_timestamp": datetime.now().isoformat(),
        "has_exif": False,
        "is_edited": False,
        "software_detected": None,
        "camera_make": None,
        "camera_model": None,
        "date_original": None,
        "date_digitized": None,
        "gps": None,
        "dimensions": None,
        "format": None,
        "observations": [],
        "alerts": [],
    }

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        out["format"] = img.format or "UNKNOWN"
        w, h = img.size
        out["dimensions"] = {
            "width": w,
            "height": h,
            "megapixels": round((w * h) / 1_000_000.0, 2),
            "mode": img.mode,
        }
    except Exception as exc:
        out["observations"].append(f"Não foi possível decodificar cabeçalho da imagem: {exc}")
        return out

    # EXIF extraction
    try:
        exif_raw = img.getexif()
        if exif_raw:
            out["has_exif"] = True
            exif_dict: dict[str, Any] = {}
            for tag_id, value in exif_raw.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                exif_dict[tag_name] = value

            # Check sub-IFDs (ExifIFD and GPSInfo)
            try:
                exif_ifd = exif_raw.get_ifd(ExifTags.IFD.Exif)
                for tag_id, value in exif_ifd.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    exif_dict.setdefault(tag_name, value)
            except Exception:
                pass

            try:
                gps_ifd = exif_raw.get_ifd(ExifTags.IFD.GPSInfo)
                gps_dict: dict[str, Any] = {}
                for tag_id, value in gps_ifd.items():
                    tag_name = ExifTags.GPSTAGS.get(tag_id, str(tag_id))
                    gps_dict[tag_name] = value

                if "GPSLatitude" in gps_dict and "GPSLatitudeRef" in gps_dict:
                    lat = _dms_to_decimal(gps_dict["GPSLatitude"], gps_dict["GPSLatitudeRef"])
                    lon = _dms_to_decimal(gps_dict.get("GPSLongitude"), gps_dict.get("GPSLongitudeRef", "W"))
                    if lat is not None and lon is not None:
                        out["gps"] = {
                            "latitude": lat,
                            "longitude": lon,
                            "google_maps": f"https://www.google.com/maps?q={lat},{lon}",
                            "osm": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}",
                        }
                        out["observations"].append(f"Geolocalização GPS encontrada: {lat}, {lon}")
            except Exception:
                pass

            # Camera metadata
            out["camera_make"] = exif_dict.get("Make")
            out["camera_model"] = exif_dict.get("Model")
            out["date_original"] = (
                exif_dict.get("DateTimeOriginal")
                or exif_dict.get("DateTimeDigitized")
                or exif_dict.get("DateTime")
            )

            # Check software/manipulation indicators
            software_val = exif_dict.get("Software") or exif_dict.get("ProcessingSoftware")
            if software_val and isinstance(software_val, str):
                s_lower = software_val.lower()
                for kw in EDITING_SOFTWARE_KEYWORDS:
                    if kw in s_lower:
                        out["is_edited"] = True
                        out["software_detected"] = software_val
                        msg = (
                            f"Software de manipulação gráfica identificado nos metadados: '{software_val}'. "
                            "Indício técnico de pós-processamento, edição ou montagem."
                        )
                        out["alerts"].append(msg)
                        out["observations"].append(msg)
                        break

            if out["camera_make"] or out["camera_model"]:
                out["observations"].append(
                    f"Dispositivo de captura: {out['camera_make'] or ''} {out['camera_model'] or ''}".strip()
                )
            if out["date_original"]:
                out["observations"].append(f"Data de captura registrada: {out['date_original']}")

    except Exception as exc:
        out["observations"].append(f"Aviso durante leitura de EXIF: {exc}")

    if not out["has_exif"]:
        out["observations"].append(
            "Metadados EXIF ausentes (padrão em imagens compartilhadas em redes sociais como WhatsApp, Instagram ou Twitter)."
        )

    return out


def analyze_video_forensics(raw_bytes: bytes, filename: str = "video.mp4") -> dict[str, Any]:
    """Extract cryptographic integrity and container properties of video files."""
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    md5 = hashlib.md5(raw_bytes).hexdigest()
    size_bytes = len(raw_bytes)

    out: dict[str, Any] = {
        "media_type": "video",
        "filename": filename,
        "sha256": sha256,
        "md5": md5,
        "size_bytes": size_bytes,
        "size_formatted": _format_size(size_bytes),
        "analysis_timestamp": datetime.now().isoformat(),
        "duration_seconds": None,
        "fps": None,
        "frame_count": None,
        "dimensions": None,
        "observations": [],
        "alerts": [],
    }

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            dur = round(frame_count / fps, 2) if fps > 0 else None

            out["fps"] = round(fps, 2)
            out["frame_count"] = frame_count
            out["dimensions"] = {"width": w, "height": h}
            out["duration_seconds"] = dur
            if dur:
                out["observations"].append(f"Duração estimada: {dur}s ({frame_count} frames a {fps:.1f} fps)")
            if w and h:
                out["observations"].append(f"Resolução de vídeo: {w}x{h}")
        cap.release()
    except Exception as exc:
        out["observations"].append(f"Aviso durante leitura de propriedades de vídeo: {exc}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return out
