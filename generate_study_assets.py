import json
import os
import re
import time
import urllib.request
import urllib.error
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
from matplotlib.path import Path
import matplotlib.patches as mpatches
import numpy as np

GEMINI_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEY", "").split(",") if k.strip()]
MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]

CHAPTERS = [
    # Mathematics
    ("Maths", "Sets, Relations & Functions"),
    ("Maths", "Complex Numbers & Quadratics"),
    ("Maths", "Sequences & Series"),
    ("Maths", "Permutations & Combinations"),
    ("Maths", "Binomial Theorem"),
    ("Maths", "Matrices & Determinants"),
    ("Maths", "Trigonometry & Inverse Trig"),
    ("Maths", "Straight Lines & Circles"),
    ("Maths", "Conic Sections"),
    ("Maths", "Limits, Continuity & Differentiability"),
    ("Maths", "Indefinite & Definite Integration"),
    ("Maths", "Area Under Curves & Differential Equations"),
    ("Maths", "Vectors & 3D Geometry"),
    ("Maths", "Probability & Statistics"),
    # Computer Awareness
    ("Computer", "Number Systems, Boolean Algebra & Logic Gates"),
    ("Computer", "Computer Organization, Memory & OS"),
    ("Computer", "DBMS, SQL & Networking"),
    ("Computer", "Data Structures & Programming Concepts"),
    # Logical Reasoning & Quant
    ("Reasoning", "Syllogisms, Blood Relations, Directions & Coding"),
    ("Reasoning", "Seating, Puzzles, Clocks, Calendars & Quant"),
    # General English
    ("English", "Tenses, Subject-Verb Agreement & Conditionals"),
    ("English", "Active-Passive, Narration, Articles & Vocab"),
]

ASSET_PROMPT = """You are creating a deep, exam-grade NIMCET (MCA entrance) study sheet and mind map for:
Subject: {subject}
Chapter: {chapter}

Return ONLY valid JSON with this exact schema:
{{
  "title": "{chapter}",
  "subject": "{subject}",
  "core_summary": "1 crisp exam-oriented summary line with key formula/rule",
  "formula_cards": [
    {{
      "heading": "Short topic label (2-4 words)",
      "lines": ["Line 1 (concise, <= 45 chars)", "Line 2 (concise, <= 45 chars)"]
    }}
  ],
  "mindmap_branches": [
    {{
      "branch_title": "Branch Name (2-3 words)",
      "color": "#1565C0",
      "points": [
        "Concept/rule/PYQ pattern (<= 42 chars)",
        "Example or trap (<= 42 chars)"
      ]
    }}
  ],
  "pyq_and_traps": [
    "NIMCET PYQ trend / common trap 1 (<= 65 chars)",
    "Shortcut / trap 2 (<= 65 chars)"
  ]
}}

Rules:
- Provide 6 to 8 formula_cards covering all essential formulas, identities, edge cases, and shortcuts.
- Provide 4 to 6 mindmap_branches covering concepts, PYQ patterns, solved mini-examples, and common traps.
- Keep every string concise so it fits inside boxes with ZERO text overlap.
- Use clean Unicode math symbols (π, θ, α, β, ω, √, ∫, ∑, ∈, ∪, ∩, ≤, ≥, ≠, →, ∴, ², ³) and avoid raw LaTeX backslashes."""


def call_gemini(prompt: str) -> dict:
    if not GEMINI_KEYS:
        raise RuntimeError("No GEMINI_API_KEY set in environment.")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.35,
        },
    }).encode("utf-8")

    for model in MODELS:
        for key in GEMINI_KEYS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in range(2):
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        txt = body["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if txt.startswith("```"):
                            txt = re.sub(r"^```[a-zA-Z]*", "", txt)
                            txt = re.sub(r"```$", "", txt).strip()
                        return json.loads(txt)
                except urllib.error.HTTPError as e:
                    if e.code in (400, 401, 403, 404, 429):
                        break
                    time.sleep(1.5 * (attempt + 1))
                except Exception:
                    time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"All Gemini models/keys failed for chapter prompt.")


def wrap_lines(text: str, max_chars: int = 38) -> list[str]:
    words = text.split()
    out = []
    cur = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur_len + add > max_chars and cur:
            out.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        out.append(" ".join(cur))
    return out


def render_formula_sheet(data: dict, out_prefix: str) -> None:
    cards = data.get("formula_cards", [])
    traps = data.get("pyq_and_traps", [])
    cols = 2
    rows = max(1, (len(cards) + cols - 1) // cols)

    fig_h = max(10.0, 2.2 + rows * 2.55 + (1.6 if traps else 0.4))
    fig, ax = plt.subplots(figsize=(12.0, fig_h), dpi=300)
    fig.patch.set_facecolor("#FFFDF7")
    ax.set_facecolor("#FFFDF7")
    ax.set_xlim(0, 12)
    ax.set_ylim(0, fig_h)
    ax.axis("off")

    # Header banner
    header = FancyBboxPatch(
        (0.4, fig_h - 1.45), 11.2, 1.1,
        boxstyle="round,pad=0.06,rounding_size=0.18",
        facecolor="#1B4332", edgecolor="none"
    )
    ax.add_patch(header)
    ax.text(0.7, fig_h - 0.78, f"NIMCET {data.get('subject', '')} • {data.get('title', '')}",
            fontsize=15.5, fontweight="bold", color="white", va="center")
    ax.text(0.7, fig_h - 1.18, data.get("core_summary", "")[:95],
            fontsize=10.5, color="#D8F3DC", va="center")

    palette = [
        ("#1565C0", "#F3F8FF"),
        ("#C62828", "#FFF5F5"),
        ("#2E7D32", "#F3FAF4"),
        ("#EF6C00", "#FFF8F0"),
        ("#6A1B9A", "#F9F3FC"),
        ("#00695C", "#F0FAF8"),
    ]

    card_w = 5.45
    card_h = 2.22
    gap_x = 0.3
    gap_y = 0.32
    top_y = fig_h - 1.75

    for idx, card in enumerate(cards[: rows * cols]):
        r = idx // cols
        c = idx % cols
        x0 = 0.4 + c * (card_w + gap_x)
        y0 = top_y - (r + 1) * card_h - r * gap_y

        accent, tint = palette[idx % len(palette)]
        box = FancyBboxPatch(
            (x0, y0), card_w, card_h,
            boxstyle="round,pad=0.04,rounding_size=0.15",
            facecolor=tint, edgecolor=accent, linewidth=1.6
        )
        ax.add_patch(box)

        badge = FancyBboxPatch(
            (x0 + 0.16, y0 + card_h - 0.46), len(card.get("heading", "")) * 0.11 + 0.35, 0.32,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=accent, edgecolor="none"
        )
        ax.add_patch(badge)
        ax.text(x0 + 0.3, y0 + card_h - 0.3, card.get("heading", ""),
                fontsize=10.0, fontweight="bold", color="white", va="center")

        wrapped = []
        for raw_line in card.get("lines", []):
            wrapped.extend(wrap_lines(str(raw_line), max_chars=44))

        line_y = y0 + card_h - 0.72
        for wl in wrapped[:5]:
            ax.text(x0 + 0.18, line_y, wl,
                    fontsize=10.5, color="#1A2332", va="center", family="DejaVu Sans")
            line_y -= 0.33

    if traps:
        trap_y = 0.35
        trap_h = 1.15
        tbox = FancyBboxPatch(
            (0.4, trap_y), 11.2, trap_h,
            boxstyle="round,pad=0.04,rounding_size=0.15",
            facecolor="#FFF8DC", edgecolor="#E65100", linewidth=1.5
        )
        ax.add_patch(tbox)
        ax.text(0.65, trap_y + trap_h - 0.28, "NIMCET PYQ TRAPS & SHORTCUTS",
                fontsize=10.5, fontweight="bold", color="#E65100", va="center")
        ty = trap_y + trap_h - 0.58
        for t_item in traps[:2]:
            for wl in wrap_lines(f"• {t_item}", max_chars=105)[:1]:
                ax.text(0.65, ty, wl, fontsize=9.8, color="#1F242D", va="center")
                ty -= 0.28

    plt.tight_layout(pad=0.1)
    fig.savefig(f"{out_prefix}.png", dpi=300, facecolor="#FFFDF7")
    fig.savefig(f"{out_prefix}.svg", facecolor="#FFFDF7")
    plt.close(fig)


def render_mind_map(data: dict, out_prefix: str) -> None:
    branches = data.get("mindmap_branches", [])
    n = max(1, len(branches))

    fig, ax = plt.subplots(figsize=(14.0, 10.0), dpi=300)
    fig.patch.set_facecolor("#FFFFF9")
    ax.set_facecolor("#FFFFF9")
    ax.set_xlim(-7.0, 7.0)
    ax.set_ylim(-5.0, 5.0)
    ax.axis("off")

    # Subtle dot grid
    gx = np.linspace(-6.5, 6.5, 27)
    gy = np.linspace(-4.5, 4.5, 19)
    XX, YY = np.meshgrid(gx, gy)
    ax.scatter(XX, YY, s=3.5, color="#E2DDD0", zorder=0)

    # Top title strip
    ax.text(0.0, 4.62, f"{data.get('subject', '')} MIND MAP • {data.get('title', '')}",
            fontsize=15.0, fontweight="bold", color="#1B4332", ha="center", va="center")

    # Left and right balanced branch positions to guarantee zero overlap
    left_slots = [(-3.4, 2.3), (-3.7, 0.0), (-3.4, -2.3)]
    right_slots = [(3.4, 2.3), (3.7, 0.0), (3.4, -2.3)]
    slots = []
    for i in range(n):
        if i % 2 == 0:
            slots.append((right_slots[(i // 2) % len(right_slots)], True))
        else:
            slots.append((left_slots[(i // 2) % len(left_slots)], False))

    for i, br in enumerate(branches[:6]):
        (bx, by), is_right = slots[i]
        color = br.get("color", "#1565C0")

        # Curved limb from center (0, 0) to (bx, by)
        ctrl_x = bx * 0.5
        ctrl_y = by * 0.85
        verts = [(0.0, 0.0), (ctrl_x, ctrl_y), (bx, by)]
        codes = [Path.MOVETO, Path.CURVE3, Path.CURVE3]
        patch = mpatches.PathPatch(
            Path(verts, codes), facecolor="none", edgecolor=color, lw=5.0, capstyle="round", zorder=2
        )
        ax.add_patch(patch)

        # Branch title pill
        b_title = br.get("branch_title", f"Branch {i+1}")
        ax.text(
            bx, by + 0.52, b_title.upper(),
            fontsize=11.0, fontweight="bold", color=color,
            ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor=color, lw=1.5),
            zorder=4
        )

        # Sub-points stacked cleanly below branch node without colliding
        pts = []
        for p in br.get("points", []):
            pts.extend(wrap_lines(f"• {p}", max_chars=34))

        py = by + 0.08
        for line in pts[:5]:
            ax.text(
                bx, py, line,
                fontsize=9.3, color="#1F242D",
                ha="center", va="center", zorder=4
            )
            py -= 0.30

    # Center node
    center_box = FancyBboxPatch(
        (-1.45, -0.65), 2.9, 1.3,
        boxstyle="round,pad=0.06,rounding_size=0.35",
        facecolor="#FFF8DC", edgecolor="#1F242D", linewidth=2.4, zorder=5
    )
    ax.add_patch(center_box)
    ax.text(0.0, 0.08, data.get("title", ""),
            fontsize=11.5, fontweight="bold", color="#1F242D", ha="center", va="center", zorder=6)
    ax.text(0.0, -0.34, data.get("subject", "").upper(),
            fontsize=9.0, fontweight="bold", color="#C62828", ha="center", va="center", zorder=6)

    plt.tight_layout(pad=0.1)
    fig.savefig(f"{out_prefix}.png", dpi=300, facecolor="#FFFFF9")
    fig.savefig(f"{out_prefix}.svg", facecolor="#FFFFF9")
    plt.close(fig)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    os.makedirs("assets/formulas", exist_ok=True)
    os.makedirs("assets/mindmaps", exist_ok=True)
    os.makedirs("assets/data", exist_ok=True)

    manifest = []
    for idx, (subject, chapter) in enumerate(CHAPTERS, 1):
        slug = f"{idx:02d}_{slugify(chapter)}"
        print(f"[{idx}/{len(CHAPTERS)}] Generating {subject}: {chapter}")
        prompt = ASSET_PROMPT.format(subject=subject, chapter=chapter)
        data = call_gemini(prompt)

        f_prefix = f"assets/formulas/{slug}"
        m_prefix = f"assets/mindmaps/{slug}"
        render_formula_sheet(data, f_prefix)
        render_mind_map(data, m_prefix)

        manifest.append({
            "id": slug,
            "subject": subject,
            "chapter": chapter,
            "formula_png": f"{f_prefix}.png",
            "formula_svg": f"{f_prefix}.svg",
            "mindmap_png": f"{m_prefix}.png",
            "mindmap_svg": f"{m_prefix}.svg",
        })
        time.sleep(1.5)

    with open("assets/data/study_assets_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Done! Generated {len(manifest)} high-res PNG + SVG formula sheets and mind maps.")


if __name__ == "__main__":
    main()
