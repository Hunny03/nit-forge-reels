#!/usr/bin/env python3
"""Makes one vertical (1080x1920) NIMCET study reel per run.

Maths   -> Gemini writes a Manim scene (self-heals up to 3 times), falls back to slides.
Others  -> Gemini writes 4-5 slides + narration, rendered with Pillow.
Voice   -> edge-tts (Hinglish), gTTS as backup. Video + audio merged with ffmpeg.

Test without any keys:  python generate_reel.py --dry-run
"""
import asyncio
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
MAX_VIDEOS = 40
DRY = "--dry-run" in sys.argv or os.getenv("DRY_RUN") == "1"
VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
PATTERN = ["Maths", "Maths", "Reasoning", "Maths", "Computer"]  # Maths is 60% of the paper
ACCENT = {"Maths": (255, 159, 28), "Reasoning": (46, 196, 182), "Computer": (155, 93, 229)}


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
    (ROOT / path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ------------------------------------------------------------------ topic
def pick_topic(syllabus, history):
    done = set(history.get("done", []))
    remaining = [t for t in syllabus if t["id"] not in done]
    if not remaining:  # a full cycle is finished: start the next one
        history["cycle"] = history.get("cycle", 1) + 1
        history["done"] = []
        remaining = list(syllabus)
    want = PATTERN[history.get("total", 0) % len(PATTERN)]
    for t in remaining:
        if t["subject"] == want:
            return t
    return remaining[0]


# ----------------------------------------------------------------- gemini
def gemini_text(prompt, json_mode=False):
    from google import genai
    from google.genai import types

    keys = [k for k in re.split(r"[\s,]+", os.environ.get("GEMINI_API_KEY", "")) if k]
    if not keys:
        raise RuntimeError("GEMINI_API_KEY secret nahi mila")
    chosen = os.getenv("GEMINI_MODEL", "").strip()
    models = []
    for m in [chosen, "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]:
        if m and m not in models:
            models.append(m)
    last = None
    for model in models:
        for key in keys:
            client = genai.Client(api_key=key)
            for attempt in range(3):
                try:
                    cfg = types.GenerateContentConfig(
                        temperature=0.7,
                        response_mime_type="application/json" if json_mode else None,
                    )
                    resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                    if resp.text:
                        return resp.text
                except Exception as e:  # noqa: BLE001
                    last = e
                    msg = str(e)
                    log(f"  gemini {model} attempt {attempt + 1}: {msg[:140]}")
                    if any(x in msg for x in ("404", "NOT_FOUND", "429", "RESOURCE_EXHAUSTED",
                                              "403", "401", "PERMISSION_DENIED", "API key")):
                        break  # next key / model
                    time.sleep(6 * (attempt + 1))  # busy: wait and retry
    raise RuntimeError(f"Gemini fail ho gaya: {last}")


def strip_fences(t):
    t = t.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


# -------------------------------------------------------------------- tts
def media_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


async def _edge(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE).save(str(path))


def tts(text, path):
    path = pathlib.Path(path)
    if DRY:  # a quiet tone so the pipeline can be tested offline
        secs = max(2.0, len(text.split()) * 0.38)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={secs}",
             "-af", "volume=0.05", "-c:a", "libmp3lame", str(path)])
        return
    try:
        asyncio.run(_edge(text, path))
        if path.exists() and path.stat().st_size > 2000:
            return
    except Exception as e:  # noqa: BLE001
        log("  edge-tts fail:", str(e)[:140])
    from gtts import gTTS
    gTTS(text, lang="en", tld="co.in").save(str(path))


# ----------------------------------------------------------------- slides
def _font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold
             else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    for n in names:
        for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/"):
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


def render_slide(path, subject, label, heading, bullets, idx, total):
    accent = ACCENT.get(subject, (255, 159, 28))
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # vertical gradient background
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(11 + 12 * t), int(18 + 20 * t), int(32 + 40 * t)))

    # topic chip
    cf = _font(40, True)
    cw = int(d.textlength(label, font=cf)) + 70
    d.rounded_rectangle([60, 90, 60 + cw, 170], radius=40, fill=accent)
    d.text((95, 106), label, font=cf, fill=(20, 20, 30))

    # heading
    hs = 84
    while hs > 52:
        hf = _font(hs, True)
        hl = _wrap(d, heading, hf, W - 140)
        if len(hl) <= 3:
            break
        hs -= 6
    hf = _font(hs, True)
    hl = _wrap(d, heading, hf, W - 140)
    y = 270
    for line in hl:
        d.text((70, y), line, font=hf, fill=(255, 255, 255))
        y += hs + 14
    d.rectangle([70, y + 10, 330, y + 18], fill=accent)
    y += 80

    # bullets as cards
    bs = 62
    while bs >= 38:
        bf = _font(bs)
        wrapped = [_wrap(d, b, bf, W - 330) for b in bullets]
        need = sum(len(w) * (bs + 12) + 70 for w in wrapped)
        if y + need < H - 260:
            break
        bs -= 4
    bf = _font(bs)
    wrapped = [_wrap(d, b, bf, W - 330) for b in bullets]
    total_h = sum(len(w) * (bs + 12) + 78 for w in wrapped)
    y += max(0, (H - 300 - y - total_h) // 3)  # centre the cards a little
    for n, lines in enumerate(wrapped, 1):
        ch = len(lines) * (bs + 12) + 50
        d.rounded_rectangle([60, y, W - 60, y + ch], radius=32, fill=(28, 40, 66))
        d.ellipse([90, y + ch // 2 - 34, 158, y + ch // 2 + 34], fill=accent)
        nf = _font(40, True)
        d.text((124, y + ch // 2), str(n), font=nf, fill=(20, 20, 30), anchor="mm")
        ty = y + 25
        for line in lines:
            d.text((190, ty), line, font=bf, fill=(236, 240, 248))
            ty += bs + 12
        y += ch + 28

    # progress dots + footer
    for i in range(total):
        cx = W // 2 - (total - 1) * 28 + i * 56
        d.ellipse([cx - 10, 1760, cx + 10, 1780], fill=accent if i == idx else (70, 82, 110))
    ff = _font(34)
    d.text((W // 2, 1850), "NIT Forge  |  NIMCET 2027", font=ff, fill=(150, 160, 185), anchor="mm")
    img.save(path)


def ffmpeg_ok(cmd):
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg fail: " + r.stderr[-600:])


def build_slide_reel(data, subject, label, out_mp4, work):
    slides = data["slides"][:5]
    segs = []
    for i, s in enumerate(slides):
        img = work / f"slide_{i}.png"
        render_slide(img, subject, label, s["heading"], s["bullets"][:3], i, len(slides))
        aud = work / f"say_{i}.mp3"
        tts(s["say"], aud)
        dur = media_duration(aud) + 0.6
        seg = work / f"seg_{i}.mp4"
        ffmpeg_ok(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(img), "-i", str(aud),
                   "-vf", f"scale={W}:{H},format=yuv420p", "-af", "apad", "-t", f"{dur:.2f}",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-r", "30",
                   "-c:a", "aac", "-ar", "44100", "-ac", "2", str(seg)])
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs))
    ffmpeg_ok(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
               "-c", "copy", "-movflags", "+faststart", str(out_mp4)])


SLIDE_PROMPT = """You are an NIMCET (NIT MCA entrance, India) coaching teacher making a 30-45 second vertical study reel.
Subject: {subject}
Chapter: {chapter}
Topic: {topic}
Focus: {focus}
{avoid}
Return ONLY JSON: {{"title": "...", "slides": [{{"heading": "...", "bullets": ["...", "..."], "say": "..."}}]}}
Rules:
- 4 or 5 slides. Slide 1 is a hook (a question or common mistake). The last slide is a quick recap or exam tip.
- heading: at most 6 words. bullets: 2 or 3 per slide, each at most 9 words.
- say: what the teacher speaks for that slide, 1 or 2 short sentences (12 to 22 words), simple Hinglish in Roman letters.
- Plain Unicode text only for maths (x\u00b2, \u221a, \u03c0, \u2264). No LaTeX, no markdown.
- Be correct. Check every formula and calculation. Teach one high-yield idea, not everything.
- title: catchy, at most 60 characters."""


def make_slide_data(topic, titles):
    if DRY:
        return {"title": "Dry run: " + topic["topic"], "slides": [
            {"heading": "Kya tum ye galti karte ho?", "bullets": ["Pehle formula yaad karo", "Phir values daalo"], "say": "Aaj ek chhota sa trick dekhte hain jo exam mein time bachata hai."},
            {"heading": topic["topic"], "bullets": ["Key idea ek line mein", "Ek solved example", "Common trap"], "say": "Is topic ka main idea ye hai, aur isse ek solved example se samajhte hain."},
            {"heading": "Quick recap", "bullets": ["Formula", "Trick", "Practice 5 questions"], "say": "Recap: formula yaad rakho, trick lagao, aur paanch sawal practice karo."},
        ]}
    avoid = ("Do not repeat these earlier reel titles on this topic: " + "; ".join(titles)) if titles else ""
    prompt = SLIDE_PROMPT.format(subject=topic["subject"], chapter=topic["chapter"],
                                 topic=topic["topic"], focus=topic["focus"], avoid=avoid)
    for _ in range(3):
        try:
            data = json.loads(strip_fences(gemini_text(prompt, json_mode=True)))
            ok = [s for s in data["slides"] if s.get("heading") and s.get("bullets") and s.get("say")]
            if len(ok) >= 3:
                data["slides"] = ok
                return data
        except Exception as e:  # noqa: BLE001
            log("  slide data retry:", str(e)[:140])
    raise RuntimeError("Slide data nahi ban paya")


# ------------------------------------------------------------------ manim
MANIM_HEADER = '''from manim import *
config.pixel_width = 1080
config.pixel_height = 1920
config.frame_width = 9.0
config.frame_height = 16.0
config.background_color = "#0B1220"
'''

MANIM_PROMPT = """You are an NIMCET maths teacher who writes Manim Community Edition (Python) scenes for 30-45 second vertical study reels.
Chapter: {chapter}
Topic: {topic}
Focus: {focus}
{avoid}
Write ONE reel explaining one high-yield formula, shortcut trick or PYQ-style idea from this topic.

Reply in EXACTLY this format, nothing else:
===TITLE===
(catchy title, max 60 characters)
===NARRATION===
(about 80 to 110 words of spoken simple Hinglish in Roman letters; no symbols or LaTeX in it; say maths in words)
===CODE===
(complete Python code)

Code rules:
- Start with: from manim import *   (do NOT set any config.* values; they are set for you)
- Define exactly one class: class ReelScene(Scene) with a construct(self) method.
- The frame is PORTRAIT, 9 units wide and 16 units tall (x from -4.5 to 4.5, y from -8 to 8). Keep every object inside x in [-4, 4] and y in [-7.5, 7.5].
- Keep text readable on a phone: Text font_size at least 40; MathTex font_size 44 to 64. Use .scale_to_fit_width(8) on anything wide.
- Use MathTex(r"...") for formulas (raw strings). Use only standard LaTeX that amsmath supports. Use Text for words.
- Use only Manim Community API: Write, FadeIn, FadeOut, Create, Transform, ReplacementTransform, Indicate, Circumscribe, VGroup, Axes, Line, Square, etc. No images, no external files, no ThreeDScene, no sound.
- Total animation time about 35 to 40 seconds (add up run_time and self.wait). Finish with a short FadeOut.
- Build the idea step by step: hook, formula, one worked example, one exam tip. Be mathematically correct."""

FIX_PROMPT = """This Manim Community Edition scene failed to render.
Fix it and return ONLY the complete corrected Python code (no explanation, no markdown fences).
Keep the class name ReelScene(Scene). Keep everything inside x in [-4, 4], y in [-7.5, 7.5].
Do not set config.* values. Avoid risky LaTeX; if a MathTex line caused the error, simplify it.

--- CODE ---
{code}

--- ERROR (last lines) ---
{err}"""


def parse_manim_reply(text):
    t = text.strip()
    try:
        title = re.search(r"===TITLE===\s*(.*?)\s*===NARRATION===", t, re.S).group(1).strip()
        narr = re.search(r"===NARRATION===\s*(.*?)\s*===CODE===", t, re.S).group(1).strip()
        code = strip_fences(t.split("===CODE===", 1)[1])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Manim reply ka format galat tha") from e
    return title.splitlines()[0][:60], narr, code


def clean_code(code):
    lines = [l for l in code.splitlines() if not l.strip().startswith("config.")]
    code = "\n".join(lines)
    if "from manim import" not in code:
        code = "from manim import *\n" + code
    return code


def render_manim(code, work):
    scene = work / "scene.py"
    scene.write_text(MANIM_HEADER + "\n" + clean_code(code) + "\n", encoding="utf-8")
    media = work / "media"
    r = run([sys.executable, "-m", "manim", "render", "-qm", "--disable_caching",
             "--media_dir", str(media), str(scene), "ReelScene"], cwd=str(work))
    if r.returncode != 0:
        return None, (r.stderr or r.stdout)[-1800:]
    found = sorted(media.glob("videos/scene/*/ReelScene.mp4"))
    if not found:
        return None, "manim finished but no ReelScene.mp4 found"
    return found[-1], ""


def build_manim_reel(topic, titles, out_mp4, work):
    avoid = ("Do not repeat these earlier reel titles on this topic: " + "; ".join(titles)) if titles else ""
    reply = gemini_text(MANIM_PROMPT.format(chapter=topic["chapter"], topic=topic["topic"],
                                            focus=topic["focus"], avoid=avoid))
    title, narration, code = parse_manim_reply(reply)
    video, err = None, ""
    for attempt in range(1, 4):
        log(f"  manim render attempt {attempt}")
        video, err = render_manim(code, work)
        if video:
            break
        log("  render error:", err[-300:].replace("\n", " | "))
        if attempt < 3:
            code = strip_fences(gemini_text(FIX_PROMPT.format(code=code, err=err[-1500:])))
    if not video:
        raise RuntimeError("Manim 3 baar fail hua")

    audio = work / "narration.mp3"
    tts(narration, audio)
    dv, da = media_duration(video), media_duration(audio)
    total = max(dv, da) + 0.3
    pad = max(0.0, da - dv) + 1.0
    ffmpeg_ok(["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-filter_complex",
               f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f},scale={W}:{H},format=yuv420p[v];[1:a]apad[a]",
               "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-r", "30",
               "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out_mp4)])
    return title


# ------------------------------------------------------------------- main
def main():
    syllabus = load_json("syllabus.json", [])
    history = load_json("history.json", {"cycle": 1, "total": 0, "done": [], "titles": []})
    reels = load_json("reels.json", [])
    VIDEOS.mkdir(exist_ok=True)

    topic = pick_topic(syllabus, history)
    label = f"{topic['subject']} \u2022 {topic['chapter']}"
    prior = [t["title"] for t in history.get("titles", []) if t["id"] == topic["id"]]
    n = history.get("total", 0) + 1
    fname = f"reel_{n:04d}_{topic['subject'].lower()}.mp4"
    out = VIDEOS / fname
    log(f"Topic: {label} / {topic['topic']}  ->  {fname}")

    work = pathlib.Path(tempfile.mkdtemp())
    title = None
    try:
        if topic["subject"] == "Maths" and not DRY:
            try:
                title = build_manim_reel(topic, prior, out, work)
            except Exception as e:  # noqa: BLE001
                log("Manim path fail, slides se bana raha hoon:", str(e)[:200])
        if title is None:
            data = make_slide_data(topic, prior)
            build_slide_reel(data, topic["subject"], label, out, work)
            title = data["title"][:60]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if not out.exists() or out.stat().st_size < 10000:
        raise SystemExit("Video nahi bani")

    repo = os.getenv("GITHUB_REPOSITORY", "USER/nit-forge-reels")
    url = f"https://raw.githubusercontent.com/{repo}/main/videos/{fname}"
    reels.insert(0, {"title": title, "topic": label, "url": url})

    # keep only the latest MAX_VIDEOS
    reels = reels[:MAX_VIDEOS]
    keep = {r["url"].rsplit("/", 1)[-1] for r in reels}
    for f in VIDEOS.glob("*.mp4"):
        if f.name not in keep:
            f.unlink()

    history["done"] = history.get("done", []) + [topic["id"]]
    history["total"] = n
    history.setdefault("titles", []).append({"id": topic["id"], "title": title, "cycle": history.get("cycle", 1)})
    save_json("reels.json", reels)
    save_json("history.json", history)
    log(f"Done: {title}  ({out.stat().st_size // 1024} KB, {media_duration(out):.1f}s)")


if __name__ == "__main__":
    main()

