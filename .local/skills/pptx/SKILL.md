---
name: pptx
description: "Use this skill when creating PowerPoint presentations, slide decks, or pitch decks. Your output is MARKDOWN — a post-processor converts it to .pptx automatically. Never generate code, scripts, or binary files."
---

# PPTX Skill — IWO2 Markdown Pipeline

## CRITICAL INSTRUCTION

Your ENTIRE response must be the raw slide markdown. Do NOT write a task completion report, do NOT describe what you would create, do NOT explain your approach. Start your response with `# Deck Title` and output nothing but the slide markdown. The post-processor will convert it to a .pptx file automatically.

## How It Works

You write **markdown**. The IWO2 post-processor (`md-to-pptx.py`) converts your markdown into a branded .pptx file automatically. You do NOT run any scripts, generate any code, or produce binary files.

## Markdown Format Spec

```markdown
# Deck Title

## Slide 1 Title
- Bullet point (level 0)
- Another bullet point
  - Sub-bullet (level 1, indent 2 spaces)
  - Another sub-bullet

## Slide 2 Title
- Content here
```

### Rules

| Element | Markdown | Rendered As |
| --- | --- | --- |
| Deck title | `# Title` | Title slide (navy bg, white text, 44pt) |
| Slide title | `## Title` | Slide heading (navy, 32pt bold) |
| Bullet (level 0) | `- Text` | 18pt with bullet character |
| Bullet (level 1) | `  - Text` (2-space indent) | 16pt with open bullet, indented |
| Closing slide | Auto-generated | "Thank You" slide (navy bg) |

### What the converter does automatically

- Strips `**bold**` and `*italic*` markers (do not rely on them for meaning)
- Removes `Slide N:` prefixes from titles
- Applies Klear.ai brand colors (lavender accent `#7B68EE`, midnight blue `#041F55`, white smoke bg `#F0F0F0`)
- Adds slide numbers, top accent bar, and closing "Thank You" slide
- Sets widescreen 13.333" x 7.5" layout

### What the converter does NOT support

- Images, charts, or diagrams (text only)
- Code blocks or tables
- More than 2 bullet levels
- Custom fonts or colors (hardcoded to brand)
- Speaker notes

## Content Guidelines

1. **5-6 bullets max per slide.** The content area is ~5" tall with 18pt text. More than 6 bullets risks overflow.
2. **Keep bullet text to 1-2 lines.** Long paragraphs as bullets will wrap and crowd the slide.
3. **Use sub-bullets sparingly.** They reduce to 16pt — useful for supporting detail, not for dumping all content.
4. **One idea per slide.** If you have 8 points, split across 2 slides rather than cramming.
5. **Aim for 8-12 content slides** for a standard deck. The converter adds title + closing = total slide count + 2.
6. **Front-load the key message** in each bullet. Readers scan the first few words.

## What NOT to Do

- Do NOT output JavaScript, Python, pptxgenjs, or any code
- Do NOT reference scripts, commands, or file paths
- Do NOT suggest custom colors, fonts, or layouts — the converter handles branding
- Do NOT add image placeholders or `![image](url)` syntax — they won't render
- Do NOT wrap output in code fences — output raw markdown only
