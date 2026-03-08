#!/usr/bin/env python3
"""Convert markdown slide content to .pptx using python-pptx.

Usage:
  python3 md-to-pptx.py --input input.md --output output.pptx [--title "Deck Title"]
  echo "## Slide 1\nContent" | python3 md-to-pptx.py --output output.pptx

Expects markdown with ## headings as slide separators.
"""

import argparse
import re
import sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR


def parse_slides(markdown: str) -> tuple[str | None, list[dict]]:
    """Parse markdown into an optional deck title and slide dicts.

    Returns (deck_title, slides) where deck_title is extracted from # H1 if present.
    """
    slides = []
    deck_title = None

    # Extract H1 title if present (used as deck title, not a slide)
    h1_match = re.match(r'^#\s+(.+?)$', markdown.strip(), re.MULTILINE)
    if h1_match:
        deck_title = h1_match.group(1).strip()

    # Split on ## headings (slide boundaries)
    parts = re.split(r'^##\s+', markdown, flags=re.MULTILINE)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Skip the preamble before first ## (contains # title or intro text)
        if not slides and not re.match(r'^[^\n]+\n', part):
            continue
        # Skip preamble text that's just the H1 title area
        if not slides and h1_match and part.startswith(h1_match.group(1).strip()):
            continue

        lines = part.split('\n', 1)
        title = lines[0].strip().rstrip('#').strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        # Clean up the title (remove "Slide N:" prefix if present)
        title = re.sub(r'^Slide\s*\d+\s*[:–-]\s*', '', title, flags=re.IGNORECASE).strip()

        if not title:
            continue

        # Parse bullet points and paragraphs
        bullets = []
        for line in body.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Remove markdown bold/italic
            cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
            cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
            # Detect bullet level
            if line.startswith('- ') or line.startswith('* '):
                bullets.append({'text': cleaned[2:].strip(), 'level': 0})
            elif line.startswith('  - ') or line.startswith('  * '):
                bullets.append({'text': cleaned.strip().lstrip('-* ').strip(), 'level': 1})
            else:
                bullets.append({'text': cleaned, 'level': 0})

        slides.append({'title': title, 'bullets': bullets})

    return deck_title, slides


def build_pptx(slides: list[dict], title: str, output_path: str):
    """Build a .pptx file from parsed slide data."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Color palette
    NAVY = RGBColor(0x09, 0x1C, 0x53)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)
    LIGHT_BG = RGBColor(0xF3, 0xF4, 0xFA)
    ACCENT = RGBColor(0x8B, 0x49, 0xE2)
    DARK_TEXT = RGBColor(0x2D, 0x2D, 0x2D)
    SUBTITLE_COLOR = RGBColor(0x66, 0x66, 0x88)

    # --- Title slide ---
    slide_layout = prs.slide_layouts[6]  # Blank layout
    slide = prs.slides.add_slide(slide_layout)

    # Navy background
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = NAVY

    # Title text
    left = Inches(1)
    top = Inches(2.2)
    width = Inches(11.333)
    height = Inches(2)
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER

    # Accent line
    from pptx.shapes.autoshape import Shape
    line_left = Inches(4.5)
    line_top = Inches(4.4)
    line_width = Inches(4.333)
    line_height = Pt(4)
    shape = slide.shapes.add_shape(
        1, line_left, line_top, line_width, line_height  # MSO_SHAPE.RECTANGLE
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT
    shape.line.fill.background()

    # --- Content slides ---
    for i, s in enumerate(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank

        # Light background
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = LIGHT_BG

        # Slide number
        num_left = Inches(12.2)
        num_top = Inches(0.3)
        num_box = slide.shapes.add_textbox(num_left, num_top, Inches(0.8), Inches(0.4))
        num_tf = num_box.text_frame
        num_p = num_tf.paragraphs[0]
        num_p.text = f"{i + 1}"
        num_p.font.size = Pt(12)
        num_p.font.color.rgb = SUBTITLE_COLOR
        num_p.alignment = PP_ALIGN.RIGHT

        # Top accent bar
        bar = slide.shapes.add_shape(
            1, Inches(0), Inches(0), prs.slide_width, Pt(6)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = ACCENT
        bar.line.fill.background()

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.5), Inches(1))
        title_tf = title_box.text_frame
        title_tf.word_wrap = True
        title_p = title_tf.paragraphs[0]
        title_p.text = s['title']
        title_p.font.size = Pt(32)
        title_p.font.bold = True
        title_p.font.color.rgb = NAVY

        # Content bullets
        content_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.8), Inches(11.5), Inches(5))
        content_tf = content_box.text_frame
        content_tf.word_wrap = True

        for j, bullet in enumerate(s['bullets']):
            if j == 0:
                p = content_tf.paragraphs[0]
            else:
                p = content_tf.add_paragraph()

            p.text = bullet['text']
            p.font.size = Pt(18) if bullet['level'] == 0 else Pt(16)
            p.font.color.rgb = DARK_TEXT
            p.space_after = Pt(8)
            p.level = bullet['level']

            # Add bullet character
            if bullet['level'] == 0:
                p.text = f"\u2022  {bullet['text']}"
            else:
                p.text = f"    \u25E6  {bullet['text']}"

    # --- Closing slide ---
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = NAVY

    txBox = slide.shapes.add_textbox(Inches(1), Inches(2.8), Inches(11.333), Inches(1.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "Thank You"
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER

    prs.save(output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Convert markdown slides to .pptx")
    parser.add_argument('--input', '-i', help='Input markdown file (or stdin)')
    parser.add_argument('--output', '-o', required=True, help='Output .pptx file path')
    parser.add_argument('--title', '-t', default='Presentation', help='Deck title for title slide')
    args = parser.parse_args()

    if args.input:
        markdown = Path(args.input).read_text()
    else:
        markdown = sys.stdin.read()

    if not markdown.strip():
        print("Error: empty input", file=sys.stderr)
        sys.exit(1)

    deck_title, slides = parse_slides(markdown)
    if not slides:
        print("Error: no slides found (expected ## headings)", file=sys.stderr)
        sys.exit(1)

    # Use detected H1 title if no explicit --title was provided
    final_title = args.title if args.title != 'Presentation' else (deck_title or args.title)

    output = build_pptx(slides, final_title, args.output)
    # Output JSON result for the calling process
    import json
    print(json.dumps({
        "success": True,
        "path": str(output),
        "slideCount": len(slides) + 2,  # +2 for title and closing slides
    }))


if __name__ == '__main__':
    main()
