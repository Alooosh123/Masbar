from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

try:  # Imported lazily so the rest of the API still works if TTS is disabled.
    import edge_tts
except Exception:  # pragma: no cover - only when the optional dependency is absent
    edge_tts = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# Only Arabic neural voices are accepted. This prevents a client from asking for
# an English voice while the UI is supposed to speak Arabic.
ARABIC_VOICES: dict[str, str] = {
    "ar-SA-ZariyahNeural": "زَريّة — سعودي (أنثى)",
    "ar-SA-HamedNeural": "حامد — سعودي (ذكر)",
    "ar-EG-SalmaNeural": "سلمى — مصري (أنثى)",
    "ar-EG-ShakirNeural": "شاكر — مصري (ذكر)",
    "ar-AE-FatimaNeural": "فاطمة — إماراتي (أنثى)",
    "ar-AE-HamdanNeural": "حمدان — إماراتي (ذكر)",
    "ar-JO-SanaNeural": "سناء — أردني (أنثى)",
    "ar-JO-TaimNeural": "تيم — أردني (ذكر)",
}

DEFAULT_ARABIC_VOICE = "ar-SA-ZariyahNeural"


class TtsError(RuntimeError):
    """Raised when Arabic speech synthesis fails."""


@dataclass
class TtsResult:
    audio: bytes
    mime_type: str
    voice: str


def tts_is_available(provider: str) -> bool:
    return (provider or "").strip().lower() == "edge" and edge_tts is not None


class EdgeTtsAdapter:
    """Arabic neural TTS through Microsoft Edge's online speech service.

    The service is remote, so failures are surfaced explicitly instead of
    silently falling back to an English system voice.
    """

    def __init__(
        self,
        default_voice: str = DEFAULT_ARABIC_VOICE,
        timeout_seconds: float = 25.0,
        max_cache_entries: int = 32,
        cache_dir: Path | None = None,
    ) -> None:
        self.default_voice = (
            default_voice if default_voice in ARABIC_VOICES else DEFAULT_ARABIC_VOICE
        )
        self.timeout_seconds = timeout_seconds
        self.max_cache_entries = max_cache_entries
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    @staticmethod
    def _cache_key(text: str, voice: str) -> str:
        return hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()

    def _read_disk_cache(self, text: str, voice: str) -> bytes | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{self._cache_key(text, voice)}.mp3"
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path.read_bytes()
        except OSError:  # pragma: no cover - unreadable cache is not fatal
            logger.warning("Arabic TTS disk cache could not be read: %s", path)
        return None

    def _write_disk_cache(self, text: str, voice: str, audio: bytes) -> None:
        if self.cache_dir is None or not audio:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self.cache_dir / f"{self._cache_key(text, voice)}.mp3"
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(audio)
            tmp.replace(path)
        except OSError:  # pragma: no cover - disk cache is best-effort
            logger.warning("Arabic TTS disk cache could not be written.")

    async def synthesize(self, text: str, voice: str | None = None) -> TtsResult:
        if edge_tts is None:
            raise TtsError("محرك الصوت العربي غير مثبت على الخادم.")
        clean = " ".join((text or "").split())
        if not clean:
            raise TtsError("النص المطلوب نطقه فارغ.")
        selected = voice or self.default_voice
        if selected not in ARABIC_VOICES:
            raise TtsError("الصوت المطلوب ليس صوتًا عربيًا معتمدًا.")

        cache_key = (clean, selected)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return TtsResult(audio=cached, mime_type="audio/mpeg", voice=selected)

        disk_cached = self._read_disk_cache(clean, selected)
        if disk_cached is not None:
            self._cache[cache_key] = disk_cached
            if len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)
            return TtsResult(audio=disk_cached, mime_type="audio/mpeg", voice=selected)

        try:
            audio = await asyncio.wait_for(
                self._collect(clean, selected), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise TtsError("انتهت مهلة خدمة الصوت العربي. أعد المحاولة.") from exc
        except Exception as exc:  # network / service errors
            raise TtsError("تعذر الاتصال بخدمة الصوت العربي الآن.") from exc

        if not audio:
            raise TtsError("لم تُرجع خدمة الصوت أي بيانات.")

        self._cache[cache_key] = audio
        if len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)
        self._write_disk_cache(clean, selected, audio)
        return TtsResult(audio=audio, mime_type="audio/mpeg", voice=selected)

    async def _collect(self, text: str, voice: str) -> bytes:
        assert edge_tts is not None
        communicate = edge_tts.Communicate(text, voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)
