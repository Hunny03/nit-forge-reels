#!/usr/bin/env python3
"""Generates vertical (1080x1920) NIMCET study reels covering Maths, Reasoning,
Computer, and English tricks—each with a random topic, shortcut/exam trick,
anti-repeat tracking, and refined Hinglish voiceover.
"""
import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).parent
VIDEOS = ROOT / "videos"
W, H = 1080, 1920
DRY = "--dry-run" in sys.argv or os.getenv("DRY_RUN") == "1"

PREFERRED_VOICES = [
    v.strip()
    for v in (
        os.getenv("TTS_VOICE", ""),
        "hi-IN-MadhurNeural",
        "hi-IN-SwaraNeural",
        "en-IN-NeerjaNeural",
    )
    if v.strip()
]

PATTERN = ["Maths", "Reasoning", "Computer", "English", "Maths"]
ACCENT = {
    "Maths": (255, 159, 28),
    "Reasoning": (46, 196, 182),
    "Computer": (155, 93, 229),
    "English": (76, 201, 240),
}

ENGLISH_TRICK_TOPICS = [
    {
        "id": "eng_sva_trick",
        "subject": "English",
        "chapter": "Grammar & Error Spotting",
        "topic": "Subject-Verb Agreement Traps",
        "focus": "Trick for 'along with / together with / as well as / neither-nor / either-or' and collective nouns in exams.",
    },
    {
        "id": "eng_tense_cond_trick",
        "subject": "English",
        "chapter": "Tenses & Conditionals",
        "topic": "Conditional Sentences Shortcut",
        "focus": "Fast elimination trick for Zero, First, Second, and Third conditionals ('had + V3 -> would have + V3').",
    },
    {
        "id": "eng_voice_narration_trick",
        "subject": "English",
        "chapter": "Active-Passive & Narration",
        "topic": "Tense-Backshift & Modal Trick",
        "focus": "Quick rule to spot wrong options in direct-indirect speech and passive voice without translating full sentences.",
    },
    {
        "id": "eng_prepo_idiom_trick",
        "subject": "English",
        "chapter": "Vocabulary & Usage",
        "topic": "Fixed Prepositions & High-Freq Traps",
        "focus": "Exam shortcut for words like 'prefer to', 'senior to', 'prevent from', and spotting tone in idioms/fillers.",
    },
]


def log(*a):
    print(*a, flush=True)


def load_json(path, default):
    p = ROOT / path
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save_json(path, data):
    (ROOT / path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def parse_args():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--count", type=int, default=0)
    args, _ = p.parse_known_args()
    env_count = int(os.getenv("REEL_COUNT", "25") or "25")
    count = args.count if args.count > 0 else env_count
    return args.dry_run or DRY, max(1, count)


def _build_pool(syllabus):
    pool = list(syllabus)
    existing_ids = {t.get("id") for t in pool}
    for et in ENGLISH_TRICK_TOPICS:
        if et["id"] not in existing_ids:
            pool.append(et)
    return pool


def _signature(subject, chapter, topic, trick_or_title=""):
    raw = f"{subject}|{chapter}|{topic}|{trick_or_title}".strip().lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def pick_topic(pool, history):
    used_sigs = set(history.get("used_sigs", []))
    used_topics = set(history.get("used_topics", []))
    want = PATTERN[history.get("total", 0) % len(PATTERN)]

    def is_fresh(t):
        key = f"{t['subject']}|{t['chapter']}|{t['topic']}".lower()
        return key not in used_topics

    candidates = [t for t in pool if t["subject"] == want and is_fresh(t)]
    if not candidates:
        candidates = [t for t in pool if is_fresh(t)]
    if not candidates:
        history["cycle"] = history.get("cycle", 1) + 1
        history["used_topics"] = []
        history["done"] = []
        candidates = [t for t in pool if t["subject"] == want] or list(pool)

    idx = history.get("total", 0) % len(candidates)
    chosen = candidates[idx]
    sig = _signature(chosen["subject"], chosen["chapter"], chosen["topic"])
    if sig in used_sigs and len(candidates) > 1:
        chosen = candidates[(idx + 1) % len(candidates)]
    return chosen


def _split_keys(raw):
    return [k.strip() for k in re.split(r"[\s,]+", raw or "") if k.strip()]


def _groq_fallback(prompt, json_mode=False):
    keys = _split_keys(os.environ.get("GROQ_API_KEY", ""))
    if not keys:
        return None
    model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    import urllib.request

    for key in keys:
        for attempt in range(2):
            try:
                payload = {
                    "model": model,
                    "temperature": 0.75,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                        "User-Agent": "Mozilla/5.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    txt = (body["choices"][0]["message"]["content"] or "").strip()
                    if txt:
                        return txt
            except Exception as e:  # noqa: BLE001
                log(f"  groq {model} attempt {attempt + 1}: {str(e)[:120]}")
                time.sleep(2 * (attempt + 1))
    return None


def gemini_text(prompt, json_mode=False):
    from google import genai
    from google.genai import types

    keys = _split_keys(os.environ.get("GEMINI_API_KEY", ""))
    chosen = os.getenv("GEMINI_MODEL", "").strip()
    models = []
    for m in [
        chosen,
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3-flash-preview",
    ]:
        if m and m not in models:
            models.append(m)

    last = None
    if keys:
        for model in models:
            for key in keys:
                client = genai.Client(api_key=key)
                for attempt in range(3):
                    try:
                        cfg = types.GenerateContentConfig(
                            temperature=0.75,
                            response_mime_type="application/json" if json_mode else None,
                        )
                        resp = client.models.generate_content(
                            model=model, contents=prompt, config=cfg
                        )
                        if resp.text:
                            return resp.text
                    except Exception as e:  # noqa: BLE001
                        last = e
                        msg = str(e)
                        log(f"  gemini {model} attempt {attempt + 1}: {msg[:140]}")
                        if any(
                            x in msg
                            for x in (
                                "404",
                                "NOT_FOUND",
                                "429",
                                "RESOURCE_EXHAUSTED",
                                "403",
                                "401",
                                "PERMISSION_DENIED",
                                "API key",
                            )
                        ):
                            break
                        time.sleep(5 * (attempt + 1))

    g = _groq_fallback(prompt, json_mode=json_mode)
    if g:
        return g
    if not keys:
        raise RuntimeError("GEMINI_API_KEY secret nahi mila")
    raise RuntimeError(f"Gemini fail ho gaya: {last}")


def strip_fences(t):
    t = t.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def media_duration(path):
    r = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _clean_for_tts(text):
    t = re.sub(r"[*_`#]+", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


async def _edge_try_voices(text, path):
    import edge_tts

    last_err = None
    for voice in PREFERRED_VOICES:
        try:
            await edge_tts.Communicate(text, voice, rate="+3%").save(str(path))
            if path.exists() and path.stat().st_size > 2000:
                return voice
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(str(last_err or "edge-tts failed"))


def tts(text, path, dry=False):
    path = pathlib.Path(path)
    clean = _clean_for_tts(text)
    if dry:
        secs = max(2.2, len(clean.split()) * 0.36)
        run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=330:duration={secs}",
                "-af",
                "volume=0.05",
                "-c:a",
                "libmp3lame",
                str(path),
            ]
        )
        return
    try:
        asyncio.run(_edge_try_voices(clean, path))
        if path.exists() and path.stat().st_size > 2000:
            return
    except Exception as e:  # noqa: BLE001
        log("  edge-tts fail:", str(e)[:140])
    from gtts import gTTS

    gTTS(clean, lang="hi", tld="co.in").save(str(path))


def _font(size, bold=False):
    names = (
        ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
        if bold
        else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    )
    for n in names:
        for d in (
            "/usr/share/fonts/truetype/dejavu/",
            "/usr/share/fonts/truetype/liberation/",
        ):
            if os.path.exists(d + n):
                return ImageFont.truetype(d + n, size)
    return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_single_line(draw, text, max_size, min_size, max_w, bold=True):
    sz = max_size
    while sz > min_size:
        f = _font(sz, bold)
        if draw.textlength(text, font=f) <= max_w:
            return text, f, sz
        sz -= 2
    f = _font(min_size, bold)
    trimmed = text
    while len(trimmed) > 3 and draw.textlength(trimmed + "...", font=f) > max_w:
        trimmed = trimmed[:-1].rstrip()
    if trimmed != text:
        trimmed = trimmed + "..."
    return trimmed, f, min_size


def render_slide(path, subject, label, heading, bullets, idx, total):
    accent = ACCENT.get(subject, (255, 159, 28))
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line(
            [(0, y), (W, y)],
            fill=(int(11 + 12 * t), int(18 + 20 * t), int(32 + 40 * t)),
        )

    pill_text, cf, _ = _fit_single_line(d, label, 38, 26, W - 190, bold=True)
    cw = min(W - 120, int(d.textlength(pill_text, font=cf)) + 64)
    d.rounded_rectangle([60, 88, 60 + cw, 164], radius=38, fill=accent)
    d.text((92, 126), pill_text, font=cf, fill=(20, 20, 30), anchor="lm")

    hs = 76
    while hs > 48:
        hf = _font(hs, True)
        hl = _wrap(d, heading, hf, W - 150)
        if len(hl) <= 2:
            break
        hs -= 4
    hf = _font(hs, True)
    hl = _wrap(d, heading, hf, W - 150)[:3]

    y = 240
    for line in hl:
        d.text((70, y), line, font=hf, fill=(255, 255, 255))
        y += hs + 14

    d.rectangle([70, y + 8, 320, y + 16], fill=accent)
    y += 64

    bottom_limit = H - 250
    avail_h = max(200, bottom_limit - y)

    safe_bullets = [b.strip() for b in bullets if b and b.strip()][:3]
    bs = 54
    while bs >= 34:
        line_step = bs + 16
        wrapped = [_wrap(d, b, _font(bs), W - 360)[:3] for b in safe_bullets]
        need = sum(len(w) * line_step + 48 for w in wrapped) + max(0, len(wrapped) - 1) * 24
        if need <= avail_h:
            break
        bs -= 2

    bf = _font(bs)
    line_step = bs + 16
    wrapped = [_wrap(d, b, bf, W - 360)[:3] for b in safe_bullets]
    total_h = sum(len(w) * line_step + 48 for w in wrapped) + max(0, len(wrapped) - 1) * 24
    y += max(0, (avail_h - total_h) // 3)

    for n, lines in enumerate(wrapped, 1):
        ch = len(lines) * line_step + 42
        if y + ch > bottom_limit:
            break
        d.rounded_rectangle([60, y, W - 60, y + ch], radius=30, fill=(28, 40, 66))
        d.ellipse([88, y + ch // 2 - 32, 152, y + ch // 2 + 32], fill=accent)
        nf = _font(36, True)
        d.text((120, y + ch // 2), str(n), font=nf, fill=(20, 20, 30), anchor="mm")
        ty = y + 22
        for line in lines:
            d.text((184, ty), line, font=bf, fill=(236, 240, 248))
            ty += line_step
        y += ch + 24

    for i in range(total):
        cx = W // 2 - (total - 1) * 28 + i * 56
        d.ellipse(
            [cx - 10, 1755, cx + 10, 1775],
            fill=accent if i == idx else (70, 82, 110),
        )
    ff = _font(34)
    d.text(
        (W // 2, 1845),
        "NIMCET  |  Topic + Trick Reel",
        font=ff,
        fill=(150, 160, 185),
        anchor="mm",
    )
    img.save(path)


def ffmpeg_ok(cmd):
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg fail: " + r.stderr[-600:])


def _vertical_916_filter(extra_prefix=""):
    return (
        f"{extra_prefix}"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=#0B1220,"
        f"setsar=1,format=yuv420p"
    )


def build_slide_reel(data, subject, label, out_mp4, work, dry=False):
    slides = data["slides"][:5]
    segs = []
    for i, s in enumerate(slides):
        img = work / f"slide_{i}.png"
        render_slide(img, subject, label, s["heading"], s["bullets"][:3], i, len(slides))
        aud = work / f"say_{i}.mp3"
        tts(s["say"], aud, dry=dry)
        dur = max(2.2, media_duration(aud) + 0.5)
        seg = work / f"seg_{i}.mp4"
        ffmpeg_ok(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(img),
                "-i",
                str(aud),
                "-vf",
                _vertical_916_filter(),
                "-af",
                "apad",
                "-t",
                f"{dur:.2f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "25",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(seg),
            ]
        )
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs))
    ffmpeg_ok(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    )


SLIDE_PROMPT = """You are an NIMCET (NIT MCA entrance, India) mentor creating a high-value study reel.
Subject: {subject}
Chapter: {chapter}
Topic: {topic}
Focus: {focus}
{avoid}

Every reel MUST teach:
1) One clear topic/concept explanation (and one concrete worked mini-example), PLUS
2) One actionable exam shortcut / trick / elimination rule for NIMCET.

Return ONLY JSON: {{"title": "...", "trick_tag": "...", "slides": [{{"heading": "...", "bullets": ["...", "..."], "say": "..."}}]}}
Rules:
- 4 or 5 slides covering: topic hook/concept, worked example, shortcut/exam trick, and mistake trap.
- heading: at most 5 words, never wraps past 2 lines.
- bullets: 2 or 3 per slide, each at most 7 words.
- say: natural, refined Hinglish explanation (like a sharp Indian mentor; clear, conversational, zero fluff; 15 to 28 words per slide; plain words without raw symbols/LaTeX).
- Plain Unicode text only for maths (x², √, π, ≤). No LaTeX, no markdown.
- title: catchy and specific to this topic & trick, at most 60 characters."""


def make_slide_data(topic, used_titles, dry=False):
    if dry:
        return {
            "title": f"Trick: {topic['topic'][:45]}",
            "trick_tag": "Quick Elimination Trick",
            "slides": [
                {
                    "heading": topic["topic"][:32],
                    "bullets": ["Core concept & rule", "When it applies", "Quick check"],
                    "say": "Aaj ek kaam ka topic aur uski exam trick dekhte hain jo NIMCET mein time bachati hai.",
                },
                {
                    "heading": "Shortcut & Trick",
                    "bullets": ["Check boundary values", "Eliminate wrong options", "Verify fast"],
                    "say": "Pehle options check karo aur boundary case lagao, isse calculation aadhi ho jaati hai.",
                },
                {
                    "heading": "Common Trap",
                    "bullets": ["Don't skip sign check", "Read question carefully"],
                    "say": "Bas sign aur condition ka dhyan rakhna, wahi sabse zyada silly mistake hoti hai.",
                },
            ],
        }
    avoid = (
        "Do NOT repeat these earlier reel titles or tricks: " + "; ".join(used_titles[-25:])
        if used_titles
        else ""
    )
    prompt = SLIDE_PROMPT.format(
        subject=topic["subject"],
        chapter=topic["chapter"],
        topic=topic["topic"],
        focus=topic["focus"],
        avoid=avoid,
    )
    for _ in range(3):
        try:
            data = json.loads(strip_fences(gemini_text(prompt, json_mode=True)))
            ok = [
                s
                for s in data["slides"]
                if s.get("heading") and s.get("bullets") and s.get("say")
            ]
            if len(ok) >= 3:
                data["slides"] = ok
                return data
        except Exception as e:  # noqa: BLE001
            log("  slide data retry:", str(e)[:140])
    raise RuntimeError("Slide data nahi ban paya")


MANIM_HEADER = """from manim import *
config.pixel_width = 1080
config.pixel_height = 1920
config.frame_width = 9.0
config.frame_height = 16.0
config.background_color = "#0B1220"
"""

MANIM_PROMPT = """You are an NIMCET maths mentor writing a Manim Community Edition (Python) scene for a crisp study reel.
Chapter: {chapter}
Topic: {topic}
Focus: {focus}
{avoid}

Teach ONE distinct topic concept + ONE worked example + ONE exam shortcut/trick.

Reply in EXACTLY this format, nothing else:
===TITLE===
(catchy title, max 60 characters)
===NARRATION===
(refined, natural Hinglish explanation in Roman letters; clear and engaging mentor tone; around 75 to 125 words; spell out math symbols in words so TTS sounds natural)
===CODE===
(complete Python code)

Code rules:
- Start with: from manim import *   (do NOT set any config.* values)
- Define exactly one class: class ReelScene(Scene) with a construct(self) method.
- Frame is 9x16 (x in [-4.5, 4.5], y in [-8, 8]). Keep every object strictly inside x in [-3.8, 3.8] and y in [-6.8, 6.8].
- Text font_size at least 36; MathTex font_size 40 to 56. Scale wide items so width <= 7.6.
- CRITICAL FOR NO OVERLAP: Before introducing a new step or worked example, FadeOut previous step/example mobjects so text never overlaps.
- Use MathTex(r"...") for formulas (raw strings). Use only standard amsmath LaTeX. Use Text for words.
- End with a clean summary/trick card rather than an empty screen."""

FIX_PROMPT = """This Manim Community Edition scene failed to render.
Fix it and return ONLY the complete corrected Python code (no explanation, no markdown fences).
Keep class ReelScene(Scene). Keep everything strictly inside x in [-3.8, 3.8] and y in [-6.8, 6.8].
Do not set config.* values. Avoid risky LaTeX.

--- CODE ---
{code}

--- ERROR (last lines) ---
{err}"""


def parse_manim_reply(text):
    t = text.strip()
    try:
        title = (
            re.search(r"===TITLE===\s*(.*?)\s*===NARRATION===", t, re.S)
            .group(1)
            .strip()
        )
        narr = (
            re.search(r"===NARRATION===\s*(.*?)\s*===CODE===", t, re.S)
            .group(1)
            .strip()
        )
        code = strip_fences(t.split("===CODE===", 1)[1])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Manim reply ka format galat tha") from e
    return title.splitlines()[0][:60], narr, code


def clean_code(code):
    lines = [l for l in code.splitlines() if not l.strip().startswith("config.")]
    code = "\n".join(lines)
    if "from manim import" not in code:
        code = "from manim import *\n" + code

    guard_helper = """
    def _fit_all_mobjects(self):
        for m in list(self.mobjects):
            try:
                if m.width > 7.8:
                    m.scale_to_fit_width(7.8)
                if m.height > 13.8:
                    m.scale_to_fit_height(13.8)
                dx = 0.0
                if m.get_right()[0] > 3.95:
                    dx = 3.95 - m.get_right()[0]
                elif m.get_left()[0] < -3.95:
                    dx = -3.95 - m.get_left()[0]
                dy = 0.0
                if m.get_top()[1] > 7.1:
                    dy = 7.1 - m.get_top()[1]
                elif m.get_bottom()[1] < -7.1:
                    dy = -7.1 - m.get_bottom()[1]
                if dx != 0.0 or dy != 0.0:
                    m.shift([dx, dy, 0.0])
            except Exception:
                pass
"""
    if "def construct(self):" in code and "_fit_all_mobjects" not in code:
        code = code.replace("def construct(self):", guard_helper + "\n    def construct(self):", 1)
        code = code + "\n        self._fit_all_mobjects()\n"
    return code


def render_manim(code, work):
    scene = work / "scene.py"
    scene.write_text(MANIM_HEADER + "\n" + clean_code(code) + "\n", encoding="utf-8")
    media = work / "media"
    r = run(
        [
            sys.executable,
            "-m",
            "manim",
            "render",
            "-qm",
            "--disable_caching",
            "--media_dir",
            str(media),
            str(scene),
            "ReelScene",
        ],
        cwd=str(work),
    )
    if r.returncode != 0:
        return None, (r.stderr or r.stdout)[-1800:]
    found = sorted(media.glob("videos/scene/*/ReelScene.mp4"))
    if not found:
        return None, "manim finished but no ReelScene.mp4 found"
    return found[-1], ""


def build_manim_reel(topic, used_titles, out_mp4, work, dry=False):
    avoid = (
        "Do NOT repeat these earlier reel titles or tricks: " + "; ".join(used_titles[-25:])
        if used_titles
        else ""
    )
    reply = gemini_text(
        MANIM_PROMPT.format(
            chapter=topic["chapter"],
            topic=topic["topic"],
            focus=topic["focus"],
            avoid=avoid,
        )
    )
    title, narration, code = parse_manim_reply(reply)
    video, err = None, ""
    for attempt in range(1, 4):
        log(f"  manim render attempt {attempt}")
        video, err = render_manim(code, work)
        if video:
            break
        log("  render error:", err[-300:].replace("\n", " | "))
        if attempt < 3:
            code = strip_fences(
                gemini_text(FIX_PROMPT.format(code=code, err=err[-1500:]))
            )
    if not video:
        raise RuntimeError("Manim 3 baar fail hua")

    audio = work / "narration.mp3"
    tts(narration, audio, dry=dry)
    dv, da = media_duration(video), media_duration(audio)
    total = max(dv, da) + 0.4
    pad = max(0.0, da - dv) + 0.5
    ffmpeg_ok(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f},{_vertical_916_filter()}[v];[1:a]apad[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{total:.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    )
    return title


def generate_one(pool, history, reels, dry=False):
    topic = pick_topic(pool, history)
    label = f"{topic['subject']} \u2022 {topic['chapter']}"
    used_titles = [t.get("title", "") for t in history.get("titles", []) if t.get("title")]
    n = history.get("total", 0) + 1
    fname = f"reel_{n:04d}_{topic['subject'].lower()}.mp4"
    out = VIDEOS / fname
    log(f"[{n}] Topic: {label} / {topic['topic']}  ->  {fname}")

    work = pathlib.Path(tempfile.mkdtemp())
    title = None
    try:
        if topic["subject"] == "Maths" and not dry:
            try:
                title = build_manim_reel(topic, used_titles, out, work, dry=dry)
            except Exception as e:  # noqa: BLE001
                log("  Manim path fail, slides se bana raha hoon:", str(e)[:200])
        if title is None:
            data = make_slide_data(topic, used_titles, dry=dry)
            build_slide_reel(data, topic["subject"], label, out, work, dry=dry)
            title = data["title"][:60]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if not out.exists() or out.stat().st_size < 10000:
        raise RuntimeError("Video nahi bani")

    repo = os.getenv("GITHUB_REPOSITORY", "USER/nit-forge-reels")
    url = f"https://raw.githubusercontent.com/{repo}/main/videos/{fname}"
    reels.insert(0, {"title": title, "topic": label, "url": url})

    topic_key = f"{topic['subject']}|{topic['chapter']}|{topic['topic']}".lower()
    used_topics = set(history.get("used_topics", []))
    used_topics.add(topic_key)
    used_sigs = set(history.get("used_sigs", []))
    used_sigs.add(_signature(topic["subject"], topic["chapter"], topic["topic"], title))

    history["done"] = history.get("done", []) + [topic["id"]]
    history["used_topics"] = sorted(used_topics)
    history["used_sigs"] = sorted(used_sigs)
    history["total"] = n
    history.setdefault("titles", []).append(
        {
            "id": topic["id"],
            "title": title,
            "topic": topic["topic"],
            "cycle": history.get("cycle", 1),
        }
    )
    save_json("reels.json", reels)
    save_json("history.json", history)
    log(
        f"  Done: {title}  ({out.stat().st_size // 1024} KB, {media_duration(out):.1f}s)"
    )


def main():
    dry, count = parse_args()
    syllabus = load_json("syllabus.json", [])
    pool = _build_pool(syllabus)
    history = load_json(
        "history.json",
        {"cycle": 1, "total": 0, "done": [], "used_topics": [], "used_sigs": [], "titles": []},
    )
    reels = load_json("reels.json", [])
    VIDEOS.mkdir(exist_ok=True)

    created = 0
    for idx in range(count):
        try:
            generate_one(pool, history, reels, dry=dry)
            created += 1
        except Exception as e:  # noqa: BLE001
            log(f"  Reel {idx + 1}/{count} skip/error: {str(e)[:200]}")
            if created == 0 and idx == count - 1:
                raise
            time.sleep(2)

    log(f"Batch complete: {created}/{count} reels generated. Total stored: {len(reels)}")


if __name__ == "__main__":
    main()