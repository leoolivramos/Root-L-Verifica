"""Media extraction: photos, images, YouTube videos and direct video files."""

from __future__ import annotations

import os
import re
import tempfile
from urllib.parse import urlsplit

import cv2
import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from reliability.claims.llm import LLMGateway, Usage
from reliability.extraction.extractor import ExtractedDocument, registrable_domain

# Supported image extensions
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".avif")

# Supported video extensions
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v")

# YouTube URL regex
YOUTUBE_RE = re.compile(
    r"(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?.*v=|shorts\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)

IMAGE_VISION_PROMPT = """\
Você é um perito em análise visual e checagem de fatos.
Analise esta imagem/foto detalhadamente para verificação factual:

1. TEXTO NA IMAGEM (OCR): Transcreva com fidelidade e exatidão TODO texto visível na imagem (manchetes, legendas, placas, cartazes, documentos, prints de conversas/redes sociais, números e dados).
2. DESCRIÇÃO VISUAL E CONTEXTO: Descreva minuciosamente quem ou o que aparece na cena, ações em curso, cenário/localização aparente e símbolos visíveis.
3. ALEGAÇÕES FACTUAIS: Liste de forma explícita e clara quais alegações sobre fatos do mundo real esta imagem ou seu texto afirmam ou sugerem.
4. ANÁLISE DE AUTENTICIDADE: Avalie se há indícios visuais evidentes de IA generativa (distorções anatômicas, dedos/olhos imperfeitos, artefatos textuais ilegíveis), manipulação digital/Photoshop, ou se aparenta ser registro fotográfico autêntico.

Responda em português, de maneira objetiva, estruturada e detalhada.
"""

VIDEO_VISION_PROMPT = """\
Você é um perito em análise audiovisual e checagem de fatos.
Abaixo estão frames capturados deste vídeo ao longo de sua duração (início, meio e fim).
Analise o conteúdo do vídeo para verificação factual:

1. TEXTO NA TELA (OCR): Transcreva legendas, títulos, placas ou gráficos visíveis nos frames capturados.
2. DESCRIÇÃO DA CENA E AÇÃO: Descreva a sequência de acontecimentos, pessoas retratadas, local e ações desenvolvidas.
3. ALEGAÇÕES FACTUAIS: Liste de forma clara quais fatos ou acontecimentos o vídeo alega estarem ocorrendo.
4. ANÁLISE DE AUTENTICIDADE: Indique se aparenta ser gravação autêntica, encenação ou montagem com efeitos digitais.

Responda em português, de maneira objetiva, estruturada e detalhada.
"""


def is_youtube_url(url: str) -> bool:
    """Return True if url points to YouTube or YouTube Shorts."""
    return bool(YOUTUBE_RE.search(url))


def extract_youtube_id(url: str) -> str | None:
    """Extract 11-char video ID from YouTube URL."""
    m = YOUTUBE_RE.search(url)
    return m.group(1) if m else None


def is_image_content(content_type: str, url: str) -> bool:
    """Return True if content_type or URL indicates an image."""
    ctype = (content_type or "").lower().strip()
    if ctype.startswith("image/"):
        return True
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def is_video_content(content_type: str, url: str) -> bool:
    """Return True if content_type or URL indicates a video file."""
    ctype = (content_type or "").lower().strip()
    if ctype.startswith("video/"):
        return True
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)


async def extract_youtube_document(url: str) -> ExtractedDocument:
    """Extract metadata (oEmbed) and audio transcript for YouTube videos."""
    vid = extract_youtube_id(url)
    domain = registrable_domain(url)
    title = f"Vídeo do YouTube ({vid})"
    author = "YouTube"
    thumbnail = None

    # 1. Fetch metadata via YouTube oEmbed (no API key needed)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://www.youtube.com/oembed?url={url}&format=json")
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title") or title
                author = data.get("author_name") or author
                thumbnail = data.get("thumbnail_url")
    except Exception:
        pass

    # 2. Fetch transcript via youtube-transcript-api
    transcript_text = ""
    if vid:
        try:
            ytt = YouTubeTranscriptApi()
            # Try Portuguese first, then English, then Spanish
            fetched = ytt.fetch(vid, languages=("pt", "pt-BR", "en", "es"))
            snippets = [getattr(s, "text", str(s)) for s in fetched]
            transcript_text = " ".join(snippets)
        except Exception:
            # Fallback to whatever transcript/captions exist (including auto-generated)
            try:
                ytt = YouTubeTranscriptApi()
                t_list = ytt.list(vid)
                for t in t_list:
                    snippets = [getattr(s, "text", str(s)) for s in t.fetch()]
                    transcript_text = " ".join(snippets)
                    break
            except Exception:
                transcript_text = ""

    lines = [
        f"Título do Vídeo: {title}",
        f"Canal / Autor: {author}",
        f"URL: {url}",
    ]
    if transcript_text:
        lines.append(f"\nTranscrição Completa do Áudio do Vídeo:\n{transcript_text}")
    else:
        lines.append(
            "\n[Aviso: Este vídeo não possui transcrição ou legendas públicas disponíveis. "
            "A verificação utilizará o título, canal e contexto disponível.]"
        )

    full_text = "\n".join(lines)
    return ExtractedDocument(
        url=url,
        title=title,
        domain=domain,
        author=author,
        publisher="YouTube",
        text=full_text,
        metadata={"youtube_id": vid, "thumbnail_url": thumbnail, "has_transcript": bool(transcript_text)},
        media_type="youtube",
        media_url=url,
    )


def extract_video_keyframes(video_bytes: bytes, max_frames: int = 4) -> list[bytes]:
    """Sample evenly distributed keyframes from video bytes using OpenCV."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    frames: list[bytes] = []
    try:
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            return []

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            total_frames = 60

        indices = [int(total_frames * (i + 1) / (max_frames + 1)) for i in range(max_frames)]
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                # Resize if high resolution to save memory and tokens
                h, w = frame.shape[:2]
                if max(h, w) > 1024:
                    scale = 1024.0 / max(h, w)
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    frames.append(buf.tobytes())
        cap.release()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return frames


async def extract_image_document(
    gateway: LLMGateway, raw_bytes: bytes, content_type: str, url: str
) -> ExtractedDocument:
    """Analyze image with multimodal vision and build an ExtractedDocument."""
    mime = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        mime = "image/jpeg"

    analysis_text, usage = await gateway.analyze_image(
        raw_bytes, mime_type=mime, prompt=IMAGE_VISION_PROMPT
    )

    domain = registrable_domain(url)
    filename = urlsplit(url).path.split("/")[-1] or "imagem.jpg"
    title = f"Foto / Imagem: {filename}"

    full_text = (
        f"Arquivo de Imagem: {filename}\n"
        f"URL da Imagem: {url}\n\n"
        f"--- Análise Visual e OCR da Imagem ---\n{analysis_text}"
    )

    return ExtractedDocument(
        url=url,
        title=title,
        domain=domain,
        text=full_text,
        metadata={"mime_type": mime, "byte_size": len(raw_bytes), "usage": usage},
        media_type="image",
        media_url=url,
    )


async def extract_video_document(
    gateway: LLMGateway, raw_bytes: bytes, url: str
) -> ExtractedDocument:
    """Extract keyframes and analyze video with vision to build an ExtractedDocument."""
    frames = extract_video_keyframes(raw_bytes, max_frames=4)
    usage = Usage()
    analysis_text = ""

    if frames:
        analysis_text, usage = await gateway.analyze_frames(frames, prompt=VIDEO_VISION_PROMPT)
    else:
        analysis_text = "Não foi possível extrair frames válidos deste arquivo de vídeo para análise visual."

    domain = registrable_domain(url)
    filename = urlsplit(url).path.split("/")[-1] or "video.mp4"
    title = f"Vídeo: {filename}"

    full_text = (
        f"Arquivo de Vídeo: {filename}\n"
        f"URL do Vídeo: {url}\n\n"
        f"--- Análise Audiovisual dos Frames do Vídeo ---\n{analysis_text}"
    )

    return ExtractedDocument(
        url=url,
        title=title,
        domain=domain,
        text=full_text,
        metadata={"byte_size": len(raw_bytes), "frames_analyzed": len(frames), "usage": usage},
        media_type="video",
        media_url=url,
    )
