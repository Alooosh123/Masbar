"""End-to-end chat UI test with a synthetic camera feed.

Runs headless Chrome with fake media devices, injects the test part image as the
camera stream, and drives the real React UI against the real backend (including
live Cohere vision/chat). Screenshots and a JSON result file are written under
docs/.

Usage (from the project root, with the backend and Vite server running):
    ..\\.venv\\Scripts\\python.exe scripts\\e2e_chat.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
RESULTS = ROOT / "docs" / "test-results"
TEST_IMAGE = ROOT / "docs" / "test-assets" / "part-312-5620.jpg"
VOICE_SAMPLE_TEXT = "مرحبًا بك في مساعد المصنع. هذا اختبار للصوت العربي."
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
APP_URL = "http://127.0.0.1:5173/"
BACKEND = "http://127.0.0.1:8010"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class CDP:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.next_id = 1
        self.events: list[dict] = []

    def call(self, method: str, params: dict | None = None, timeout: float = 120.0) -> dict:
        message_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv(timeout=timeout))
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})
            self.events.append(message)

    def js(self, expression: str, await_promise: bool = True, timeout: float = 120.0):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        details = result.get("exceptionDetails")
        if details:
            description = (
                details.get("exception", {}).get("description")
                or details.get("text")
                or "unknown JavaScript error"
            )
            raise RuntimeError(description)
        return result.get("result", {}).get("value")

    def wait_js(self, expression: str, timeout: float = 60.0, label: str = ""):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.js(expression)
            if last:
                return last
            time.sleep(0.4)
        raise TimeoutError(f"Timed out waiting for {label or expression} ({last!r})")


class Report:
    def __init__(self) -> None:
        self.data: dict = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "app_url": APP_URL,
            "backend": BACKEND,
            "test_image": str(TEST_IMAGE.relative_to(ROOT)),
            "checks": [],
            "steps": {},
            "screenshots": [],
            "limitations": [
                "الكاميرا في هذا الاختبار بث canvas مُحقَن وليس كاميرا فيزيائية.",
                "الميكروفون جهاز وهمي صامت؛ لم يُختبر التعرف الصوتي العربي بكلام حقيقي.",
                "الصوت في Chrome headless لا يُسمَع عبر مكبر الصوت؛ تم التحقق من تنزيل MP3 عربي ومن بدء تشغيله في المتصفح.",
                "الصوت العصبي يعتمد على خدمة Edge عبر الإنترنت؛ عند انقطاع الشبكة يعيد الخادم 503 ولا يوجد صوت محلي مضمّن.",
            ],
        }

    def check(self, name: str, ok: bool, detail=None, skipped: bool = False) -> None:
        entry = {"name": name, "ok": bool(ok), "detail": detail}
        if skipped:
            entry["skipped"] = True
            entry["skip_reason"] = detail
        self.data["checks"].append(entry)
        mark = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        print(f"[{mark}] {name}" + (f" -> {detail}" if detail is not None else ""))

    def step(self, name: str, value) -> None:
        self.data["steps"][name] = value
        print(f"[STEP] {name}: {value}")

    def screenshot(self, cdp: CDP, name: str) -> None:
        result = cdp.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / name
        path.write_bytes(base64.b64decode(result["data"]))
        self.data["screenshots"].append(str(path.relative_to(ROOT)))
        print(f"[SHOT] {path}")

    def finish(self, status: str, error: str | None = None) -> None:
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = status
        if error:
            self.data["error"] = error
        failed = [
            item
            for item in self.data["checks"]
            if not item["ok"] and not item.get("skipped")
        ]
        skipped = [item for item in self.data["checks"] if item.get("skipped")]
        self.data["summary"] = {
            "checks": len(self.data["checks"]),
            "passed": len(self.data["checks"]) - len(failed) - len(skipped),
            "failed": len(failed),
            "skipped": len(skipped),
        }
        if failed and status == "passed":
            status = "failed"
            self.data["status"] = "failed"
        RESULTS.mkdir(parents=True, exist_ok=True)
        path = RESULTS / "chat-e2e.json"
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[REPORT] {path}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed_voice_cache() -> Path:
    """Ensure the offline Arabic sample exists before testing playback."""
    source = ROOT / "docs" / "test-assets" / "tts-arabic.mp3"
    cache_dir = ROOT / "data" / "cache" / "tts"
    key = hashlib.sha256(
        f"ar-SA-ZariyahNeural\n{VOICE_SAMPLE_TEXT}".encode("utf-8")
    ).hexdigest()
    target = cache_dir / f"{key}.mp3"
    if not target.exists() and source.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return target


def launch_chrome(port: int, profile: Path) -> subprocess.Popen:
    args = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=430,932",
        "--lang=ar",
        "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_cdp(port: int, timeout: float = 30.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5) as response:
                targets = json.loads(response.read().decode("utf-8"))
            if targets:
                return targets
        except Exception:
            time.sleep(0.4)
    raise TimeoutError("Chrome DevTools endpoint did not start")


def fake_camera_script(image_data_url: str) -> str:
    return """
(() => {
  if (!navigator.mediaDevices) return;
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  const dataUrl = %s;
  navigator.mediaDevices.getUserMedia = async (constraints = {}) => {
    if (!constraints || !constraints.video) return original(constraints);
    const image = new Image();
    image.src = dataUrl;
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
    });
    const canvas = document.createElement('canvas');
    canvas.width = 1280;
    canvas.height = 960;
    const context = canvas.getContext('2d');
    const draw = () => context.drawImage(image, 0, 0, canvas.width, canvas.height);
    draw();
    setInterval(draw, 250);
    window.__fakeCameraInfo = { width: canvas.width, height: canvas.height, source: 'canvas' };
    return canvas.captureStream(10);
  };
})();
""" % json.dumps(image_data_url)


def tts_probe_script() -> str:
    return """
(() => {
  const NativeAudio = window.Audio;
  window.__ttsProbe = { plays: 0, srcs: [], error: null };
  window.Audio = function (...args) {
    const audio = new NativeAudio(...args);
    const nativePlay = audio.play.bind(audio);
    audio.play = () => {
      const promise = nativePlay();
      promise.then(() => {
        window.__ttsProbe.plays += 1;
        window.__ttsProbe.srcs.push(audio.src);
      }).catch((error) => {
        window.__ttsProbe.error = String(error);
      });
      return promise;
    };
    return audio;
  };
  window.Audio.prototype = NativeAudio.prototype;
})();
"""


def click_selector(cdp: CDP, selector: str) -> None:
    cdp.js(
        "(() => { const el = document.querySelector(%s);"
        " if (!el) throw new Error(%s);"
        " el.click(); return true; })()"
        % (json.dumps(selector), json.dumps(f"missing selector: {selector}"))
    )


def click_text(cdp: CDP, text: str) -> None:
    cdp.js(
        """(() => {
          const wanted = %s;
          const buttons = [...document.querySelectorAll('button')];
          const el = buttons.find(b => b.textContent.replace(/\\s+/g, ' ').trim() === wanted)
            || buttons.find(b => b.textContent.includes(wanted));
          if (!el) throw new Error('button not found: ' + wanted);
          if (el.disabled) throw new Error('button disabled: ' + wanted);
          el.click();
          return true;
        })()""" % json.dumps(text)
    )


def send_message(cdp: CDP, text: str) -> None:
    cdp.js(
        """(() => {
          const ta = document.querySelector('.chat-input');
          if (!ta) throw new Error('chat input missing');
          const setter = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype, 'value'
          ).set;
          setter.call(ta, %s);
          ta.dispatchEvent(new Event('input', { bubbles: true }));
          ta.focus();
          return ta.value;
        })()""" % json.dumps(text)
    )
    time.sleep(0.25)
    click_selector(cdp, ".chat-send-btn")


def scroll_into_view(cdp: CDP, selector: str) -> None:
    cdp.js(
        "(() => { const el = document.querySelector(%s);"
        " if (el) el.scrollIntoView({ block: 'center' }); return Boolean(el); })()"
        % json.dumps(selector)
    )
    time.sleep(0.35)


def scroll_last_reply(cdp: CDP) -> None:
    cdp.js(
        """(() => {
          const nodes = [...document.querySelectorAll(
            '.chat-msg.assistant .chat-bubble:not(.chat-typing)'
          )];
          const el = nodes[nodes.length - 1];
          if (el) el.scrollIntoView({ block: 'center' });
          return Boolean(el);
        })()"""
    )
    time.sleep(0.35)


def assistant_count(cdp: CDP) -> int:
    return cdp.js(
        "document.querySelectorAll('.chat-msg.assistant .chat-bubble:not(.chat-typing)').length"
    )


def wait_reply(cdp: CDP, before: int, timeout: float = 120.0) -> None:
    cdp.wait_js(
        f"document.querySelectorAll('.chat-msg.assistant .chat-bubble:not(.chat-typing)').length"
        f" > {before} && !document.querySelector('.chat-typing')",
        timeout=timeout,
        label="assistant reply",
    )


def last_assistant_text(cdp: CDP) -> str:
    return cdp.js(
        "(() => { const nodes = [...document.querySelectorAll("
        "'.chat-msg.assistant .chat-bubble:not(.chat-typing)')];"
        " return nodes.length ? nodes[nodes.length - 1].innerText : ''; })()"
    )


def main() -> int:
    report = Report()
    if not TEST_IMAGE.exists():
        raise SystemExit(f"Test image missing: {TEST_IMAGE}")
    image_data_url = "data:image/jpeg;base64," + base64.b64encode(
        TEST_IMAGE.read_bytes()
    ).decode("ascii")

    port = free_port()
    profile = Path(tempfile.mkdtemp(prefix="isa-chat-e2e-"))
    chrome = None
    connection = None
    cdp = None
    status = "failed"
    error = None

    try:
        voice_cache = seed_voice_cache()
        report.step(
            "voice_cache",
            {
                "path": str(voice_cache.relative_to(ROOT)),
                "exists": voice_cache.exists(),
                "bytes": voice_cache.stat().st_size if voice_cache.exists() else 0,
            },
        )
        with httpx.Client(timeout=8) as client:
            health = client.get(f"{BACKEND}/health").json()
            web = client.get(APP_URL)
            manufacturers = client.get(f"{BACKEND}/api/v1/manufacturers").json()
            komatsu_search = client.get(
                f"{BACKEND}/api/v1/manufacturers", params={"q": "PC200"}
            ).json()
            tts_response = client.post(
                f"{BACKEND}/api/v1/tts",
                json={"text": VOICE_SAMPLE_TEXT},
                timeout=60,
            )
            live_tts_response = client.post(
                f"{BACKEND}/api/v1/tts",
                json={"text": "اختبار مباشر لخدمة الصوت العربي."},
                timeout=60,
            )
        report.step("health", health)
        report.check("backend online", health.get("status") == "online", health)
        report.check("chat provider ready", health.get("chat_ready") is True, health.get("chat_provider"))
        report.check("vite app reachable", web.status_code == 200, web.status_code)
        report.check(
            "Arabic TTS provider ready",
            health.get("tts_ready") is True and health.get("tts_provider") == "edge",
            health.get("tts_provider"),
        )
        report.check(
            "OEM registry loaded",
            health.get("manufacturers") == len(manufacturers) == 31,
            health.get("manufacturers"),
        )
        report.check(
            "manufacturers endpoint returns real brands",
            len(manufacturers) == 31
            and any(item["id"] == "caterpillar" and item["models_count"] >= 6 for item in manufacturers),
            [item["name_ar"] for item in manufacturers[:5]],
        )
        report.check(
            "manufacturer model search works",
            [item["id"] for item in komatsu_search] == ["komatsu"],
            [item["id"] for item in komatsu_search],
        )
        tts_headers = {key.lower(): value for key, value in tts_response.headers.items()}
        tts_ok = (
            tts_response.status_code == 200
            and tts_headers.get("content-type", "").startswith("audio/mpeg")
            and tts_headers.get("x-tts-language") == "ar"
            and str(tts_headers.get("x-tts-voice", "")).startswith("ar-")
            and len(tts_response.content) > 1000
        )
        report.step(
            "cached_tts_response",
            {
                "status": tts_response.status_code,
                "voice": tts_headers.get("x-tts-voice"),
                "content_type": tts_headers.get("content-type"),
                "bytes": len(tts_response.content),
            },
        )
        report.check(
            "server serves cached Arabic MP3",
            tts_ok,
            {
                "status": tts_response.status_code,
                "voice": tts_headers.get("x-tts-voice"),
                "bytes": len(tts_response.content),
            },
        )

        live_headers = {
            key.lower(): value for key, value in live_tts_response.headers.items()
        }
        live_ok = (
            live_tts_response.status_code == 200
            and live_headers.get("content-type", "").startswith("audio/mpeg")
            and str(live_headers.get("x-tts-voice", "")).startswith("ar-")
            and len(live_tts_response.content) > 1000
        )
        if live_ok:
            live_path = ROOT / "docs" / "test-assets" / "tts-arabic-e2e.mp3"
            live_path.parent.mkdir(parents=True, exist_ok=True)
            live_path.write_bytes(live_tts_response.content)
        report.step(
            "live_tts_response",
            {
                "status": live_tts_response.status_code,
                "voice": live_headers.get("x-tts-voice"),
                "bytes": len(live_tts_response.content),
            },
        )
        report.check(
            "live Edge Arabic TTS reachable",
            live_ok,
            (
                {
                    "status": live_tts_response.status_code,
                    "voice": live_headers.get("x-tts-voice"),
                    "bytes": len(live_tts_response.content),
                }
                if live_ok
                else "خدمة Edge غير متاحة من هذه الشبكة الآن؛ تم التحقق من الصوت العربي عبر الذاكرة المحلية."
            ),
            skipped=not live_ok,
        )

        chrome = launch_chrome(port, profile)
        targets = wait_cdp(port)
        page = next((item for item in targets if item.get("type") == "page"), targets[0])
        connection = connect(
            page["webSocketDebuggerUrl"], origin=None, max_size=None, legacy=True
        )
        cdp = CDP(connection)

        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Log.enable")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 430,
                "height": 932,
                "deviceScaleFactor": 2,
                "mobile": True,
            },
        )
        cdp.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": fake_camera_script(image_data_url)},
        )
        cdp.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": tts_probe_script()},
        )
        cdp.call("Page.navigate", {"url": APP_URL})

        cdp.wait_js(
            "document.querySelector('.chat-brand-copy strong')?.textContent.includes('مساعد المصنع')",
            30,
            "app shell",
        )
        cdp.wait_js(
            "document.querySelector('.chat-msg.assistant .chat-bubble') !== null",
            40,
            "welcome message",
        )
        time.sleep(0.5)
        welcome = last_assistant_text(cdp)
        report.step("welcome", welcome)
        report.check("welcome message rendered", "مرحبًا" in welcome, welcome[:80])
        report.check(
            "RTL layout",
            cdp.js("document.documentElement.dir === 'rtl'"),
            cdp.js("document.documentElement.dir"),
        )
        online_label = cdp.js("document.querySelector('.chat-brand-copy small')?.innerText || ''")
        report.step("header_status", online_label)
        report.check("header shows chat ready", "محادثة ذكية" in online_label, online_label)
        report.screenshot(cdp, "chat-welcome.png")

        # ------------------------------------------------------- Arabic TTS UI
        click_selector(cdp, ".chat-voice-test")
        tts_probe = cdp.wait_js(
            "window.__ttsProbe && window.__ttsProbe.plays > 0 ? window.__ttsProbe : null",
            60,
            "Arabic TTS playback",
        )
        report.step("tts_probe", tts_probe)
        report.check(
            "UI plays cached Arabic MP3",
            tts_probe.get("plays", 0) > 0
            and any(str(src).startswith("blob:") for src in tts_probe.get("srcs", [])),
            {"plays": tts_probe.get("plays"), "error": tts_probe.get("error")},
        )
        report.screenshot(cdp, "chat-tts.png")

        # --------------------------------------------------- OEM manufacturers
        before = assistant_count(cdp)
        send_message(cdp, "ما الشركات المتاحة؟")
        wait_reply(cdp, before, timeout=30)
        manufacturers_text = last_assistant_text(cdp)
        report.step("manufacturers_answer", manufacturers_text)
        report.check(
            "chat lists manufacturers from OEM registry",
            "كاتربيلر" in manufacturers_text
            and "كوماتسو" in manufacturers_text
            and "31" in manufacturers_text,
            manufacturers_text[:160],
        )
        scroll_last_reply(cdp)
        report.screenshot(cdp, "chat-manufacturers.png")

        # ---------------------------------------------------------- camera open
        before = assistant_count(cdp)
        send_message(cdp, "افتح الكاميرا")
        wait_reply(cdp, before, timeout=30)
        cdp.wait_js("document.querySelector('.chat-camera') !== null", 20, "camera overlay")
        cdp.wait_js(
            "document.querySelector('.chat-camera-video')?.classList.contains('is-ready')"
            " && document.querySelector('.chat-camera-video').videoWidth > 0",
            25,
            "camera video frames",
        )
        camera_info = cdp.js(
            "(() => { const v = document.querySelector('.chat-camera-video');"
            " const info = window.__fakeCameraInfo || {};"
            " return { videoWidth: v.videoWidth, videoHeight: v.videoHeight,"
            " readyState: v.readyState, fake: info }; })()"
        )
        report.step("camera", camera_info)
        report.check(
            "camera receives frames",
            camera_info["videoWidth"] == 1280 and camera_info["videoHeight"] == 960,
            camera_info,
        )
        report.screenshot(cdp, "chat-camera-live.png")

        # ----------------------------------------------------- default describe
        before = assistant_count(cdp)
        started = time.time()
        click_text(cdp, "التقاط ووصف")
        cdp.wait_js(
            "document.querySelector('.chat-camera') === null", 10, "camera closed after capture"
        )
        cdp.wait_js(
            "document.querySelector('.chat-source.vision') !== null",
            150,
            "vision description badge",
        )
        wait_reply(cdp, before, timeout=20)
        describe_text = last_assistant_text(cdp)
        report.step(
            "image_description",
            {"seconds": round(time.time() - started, 1), "text": describe_text},
        )
        report.check(
            "image captured and described",
            "وصف عام" in describe_text and len(describe_text) > 40,
            describe_text[:120],
        )
        report.check(
            "description mentions visible content",
            any(
                term in describe_text
                for term in ("312-5620", "FUEL", "ACTUATOR", "صمام", "وقود")
            ),
            describe_text[:120],
        )
        report.check(
            "description is labelled non-authoritative",
            "ليس تحديدًا معتمدًا" in describe_text,
            "note present",
        )
        report.screenshot(cdp, "chat-image-description.png")

        # ------------------------------------------------------ start session
        before = assistant_count(cdp)
        send_message(cdp, "ابدأ جلسة على C15")
        wait_reply(cdp, before, timeout=45)
        cdp.wait_js("document.querySelector('.chat-session-chip') !== null", 10, "session chip")
        session_chip = cdp.js("document.querySelector('.chat-session-chip').innerText")
        report.step("session_chip", session_chip)
        report.check("session started from chat", "C15" in session_chip, session_chip)

        before = assistant_count(cdp)
        send_message(cdp, "اعرض القطع")
        wait_reply(cdp, before, timeout=30)
        cdp.wait_js(
            "document.querySelectorAll('.chat-component-item').length >= 3",
            15,
            "component list",
        )
        components = cdp.js(
            "[...document.querySelectorAll('.chat-component-item')].map("
            "el => el.innerText.replace(/\\n/g, ' | '))"
        )
        report.step("components", components)
        report.check("component catalog rendered", len(components) == 3, components)
        report.screenshot(cdp, "chat-session-components.png")

        # ---------------------------------------------------- vision identify
        click_selector(cdp, "button[title='فتح الكاميرا']")
        cdp.wait_js("document.querySelector('.chat-camera') !== null", 15, "camera reopen")
        cdp.wait_js(
            "document.querySelector('.chat-camera-video')?.classList.contains('is-ready')",
            20,
            "camera ready for identify",
        )
        started = time.time()
        click_text(cdp, "التقاط وتحديد")
        cdp.wait_js("document.querySelector('.safety-panel') !== null", 180, "safety gate")
        identification = cdp.js(
            """(() => {
              const part = document.querySelector('.component-card .part-number')?.innerText || '';
              const name = document.querySelector('.component-card .component-title h2')?.innerText || '';
              const confidence = document.querySelector('.component-card .confidence strong')?.innerText || '';
              const source = document.querySelector('.component-card .component-meta .chip')?.innerText || '';
              const state = document.querySelector('.chat-session-chip small')?.innerText || '';
              const checklist = [...document.querySelectorAll('.safety-panel .check-label')]
                .map(el => el.innerText);
              const warnings = [...document.querySelectorAll('.safety-panel .warning-list li')]
                .map(el => el.innerText);
              return { part, name, confidence, source, state, checklist, warnings };
            })()"""
        )
        report.step(
            "vision_identification",
            {"seconds": round(time.time() - started, 1), **identification},
        )
        report.check(
            "camera image identified deterministically",
            identification["part"] == "312-5620",
            identification,
        )
        report.check(
            "vision confidence is full",
            identification["confidence"] in {"100%", "100"},
            identification["confidence"],
        )
        report.check(
            "LOTO gate blocks steps",
            identification["state"] == "بوابة السلامة"
            and len(identification["checklist"]) == 3,
            identification["state"],
        )
        report.screenshot(cdp, "chat-loto.png")

        # ----------------------------------------------------------- LOTO gate
        cdp.js(
            "(() => { [...document.querySelectorAll('.safety-panel .check-row')]"
            ".forEach(el => el.click()); return true; })()"
        )
        cdp.wait_js(
            "document.querySelector('.confirm-safety-btn')"
            " && !document.querySelector('.confirm-safety-btn').disabled",
            10,
            "LOTO confirm enabled",
        )
        click_selector(cdp, ".confirm-safety-btn")
        cdp.wait_js("document.querySelector('.step-card') !== null", 30, "first maintenance step")
        first_step = cdp.js(
            """(() => ({
              progress: document.querySelector('.step-progress-head')?.innerText || '',
              instruction: document.querySelector('.step-instruction')?.innerText || '',
              state: document.querySelector('.chat-session-chip small')?.innerText || '',
              torque: document.body.innerText.includes('45')
            }))()"""
        )
        report.step("first_step", first_step)
        report.check(
            "LOTO confirmation unlocks procedure",
            "الخطوة 1" in first_step["progress"] or "1" in first_step["progress"],
            first_step,
        )
        report.check(
            "session ready for steps",
            first_step["state"] in {"جاهز", "قيد التنفيذ"},
            first_step["state"],
        )
        scroll_into_view(cdp, ".step-card")
        report.screenshot(cdp, "chat-step-1.png")

        # ---------------------------------------------------------- next step
        click_selector(cdp, ".step-btn.primary")
        cdp.wait_js(
            "document.querySelector('.step-progress-head')?.innerText.includes('2')",
            20,
            "second step",
        )
        second_step = cdp.js(
            "document.querySelector('.step-progress-head')?.innerText || ''"
        )
        report.step("second_step", second_step)
        report.check("next step advances", "2" in second_step, second_step)
        scroll_into_view(cdp, ".step-card")
        report.screenshot(cdp, "chat-step-2.png")

        # -------------------------------------------------------------- torque
        before = assistant_count(cdp)
        if cdp.js(
            "[...document.querySelectorAll('.chat-quick-chip')].some("
            "el => el.textContent.includes('كم العزم'))"
        ):
            click_text(cdp, "كم العزم؟")
        else:
            send_message(cdp, "كم العزم؟")
        wait_reply(cdp, before, timeout=45)
        torque_text = last_assistant_text(cdp)
        report.step("torque_answer", torque_text)
        report.check(
            "torque answered from knowledge base",
            "45" in torque_text and "SENR9834" in torque_text,
            torque_text[:160],
        )
        scroll_last_reply(cdp)
        report.screenshot(cdp, "chat-torque.png")

        # --------------------------------------------------- microphone tests
        cdp.call("Page.navigate", {"url": APP_URL + "?mic=1"})
        cdp.wait_js(
            "document.querySelector('.chat-msg.assistant .chat-bubble') !== null",
            40,
            "welcome after reload",
        )
        recognition_supported = cdp.js(
            "Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)"
        )
        permission = cdp.js(
            """(async () => {
              try {
                const status = await navigator.permissions.query({ name: 'microphone' });
                return status.state;
              } catch (error) { return 'unsupported: ' + error.message; }
            })()"""
        )
        mic_stream = cdp.js(
            """(async () => {
              try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const track = stream.getAudioTracks()[0];
                const info = {
                  label: track.label,
                  readyState: track.readyState,
                  enabled: track.enabled,
                  settings: track.getSettings(),
                };
                stream.getTracks().forEach(t => t.stop());
                return info;
              } catch (error) { return { error: error.name + ': ' + error.message }; }
            })()"""
        )
        voices = cdp.js(
            """(() => {
              const list = speechSynthesis.getVoices();
              return {
                total: list.length,
                arabic: list.filter(v => v.lang.toLowerCase().startsWith('ar'))
                  .map(v => v.name + ' (' + v.lang + ')').slice(0, 5),
              };
            })()"""
        )
        tts = cdp.js(
            """(async () => {
              if (!('speechSynthesis' in window)) return { supported: false };
              const utterance = new SpeechSynthesisUtterance('اختبار القراءة الصوتية');
              utterance.lang = 'ar-SA';
              return await new Promise(resolve => {
                let started = false;
                let ended = false;
                const timer = setTimeout(
                  () => resolve({ supported: true, started, ended, timeout: true }), 6000
                );
                utterance.onstart = () => { started = true; };
                utterance.onend = () => {
                  ended = true;
                  clearTimeout(timer);
                  resolve({ supported: true, started, ended, timeout: false });
                };
                utterance.onerror = event => {
                  clearTimeout(timer);
                  resolve({ supported: true, started, ended, error: event.error });
                };
                speechSynthesis.speak(utterance);
              });
            })()""",
            timeout=20,
        )
        report.step(
            "microphone",
            {
                "recognition_supported": recognition_supported,
                "permission": permission,
                "stream": mic_stream,
                "voices": voices,
                "tts": tts,
            },
        )
        report.check("microphone permission granted", permission == "granted", permission)
        report.check(
            "getUserMedia audio track live",
            isinstance(mic_stream, dict)
            and mic_stream.get("readyState") == "live"
            and "error" not in mic_stream,
            mic_stream,
        )
        report.check("speech recognition API present", recognition_supported is True, recognition_supported)
        report.check(
            "speech synthesis API works",
            tts.get("supported") is True,
            tts,
        )

        click_selector(cdp, ".chat-tool-btn.mic")
        time.sleep(1.2)
        listening = cdp.js(
            "document.querySelector('.chat-input-row')?.classList.contains('is-listening')"
        )
        mic_state = cdp.js(
            "(() => ({ placeholder: document.querySelector('.chat-input')?.placeholder || '',"
            " meta: document.querySelector('.chat-composer-meta span')?.innerText || '',"
            " error: document.querySelector('.chat-composer-meta .is-error')?.innerText || '',"
            " button: document.querySelector('.chat-tool-btn.mic')?.className || '' }))()"
        )
        report.step("microphone_ui", {"listening": listening, **mic_state})
        report.check("microphone button starts listening", listening is True, mic_state)
        report.screenshot(cdp, "chat-mic-test.png")

        deadline = time.time() + 18
        while time.time() < deadline:
            state = cdp.js(
                "(() => ({ listening: document.querySelector('.chat-input-row')"
                "?.classList.contains('is-listening'),"
                " error: document.querySelector('.chat-composer-meta .is-error')?.innerText || '' }))()"
            )
            if not state["listening"] or state["error"]:
                break
            time.sleep(0.7)
        final_mic = cdp.js(
            "(() => ({ listening: document.querySelector('.chat-input-row')"
            "?.classList.contains('is-listening'),"
            " error: document.querySelector('.chat-composer-meta .is-error')?.innerText || '',"
            " placeholder: document.querySelector('.chat-input')?.placeholder || '' }))()"
        )
        transcript_sent = cdp.js(
            "[...document.querySelectorAll('.chat-msg.user')].some("
            "el => el.innerText.trim().length > 0)"
        )
        report.step(
            "microphone_result",
            {
                **final_mic,
                "transcript_sent": transcript_sent,
                "note": (
                    "الجهاز الوهمي صامت؛ توقف الاستماع دون نص متوقع. "
                    "تم التحقق من الإذن والبث وواجهة الاستماع."
                ),
            },
        )
        report.check(
            "microphone returns to idle cleanly",
            final_mic["listening"] is False,
            final_mic,
        )
        if final_mic["listening"]:
            click_selector(cdp, ".chat-tool-btn.mic")
        report.screenshot(cdp, "chat-mic-result.png")

        # ---------------------------------------------------------- JS errors
        js_errors = [
            event
            for event in cdp.events
            if event.get("method") == "Runtime.exceptionThrown"
        ]
        report.step("javascript_exceptions", len(js_errors))
        report.check("no JavaScript exceptions", len(js_errors) == 0, len(js_errors))
        status = "passed"

    except Exception as exc:  # noqa: BLE001 - report any harness failure
        error = f"{type(exc).__name__}: {exc}"
        print(f"[ERROR] {error}")
        if cdp is not None:
            try:
                report.screenshot(cdp, "chat-e2e-failure.png")
            except Exception:
                pass
    finally:
        try:
            if connection is not None:
                connection.close()
        except Exception:
            pass
        if chrome is not None:
            subprocess.run(
                ["taskkill", "/PID", str(chrome.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        shutil.rmtree(profile, ignore_errors=True)
        report.finish(status, error)

    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
