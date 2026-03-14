---
name: klearai-pptx
description: "Klear.ai branded presentation template. Use this skill when creating Klear.ai-specific presentations, pitch decks, product overviews, RFI responses, or customer-facing slide decks. Applies Klear.ai brand voice, positioning, deck structure, and content rules. Output is MARKDOWN — the md-to-pptx converter handles visual branding automatically."
---

# Klear.ai Presentation Template Skill

## CRITICAL INSTRUCTION

Your ENTIRE response must be the raw slide markdown. Do NOT write a task completion report, do NOT describe what you would create, do NOT explain your approach, do NOT wrap in code fences. Start your response with `# Deck Title` and output ONLY the slide markdown — nothing else. The post-processor converts it to a branded .pptx file automatically.

This skill provides brand-specific guidance for creating Klear.ai presentations through the IWO2 markdown pipeline. You write **markdown** following the format spec below. The post-processor (`md-to-pptx.py`) applies Klear.ai brand colors, layout, and styling automatically.

## Brand Positioning

**Klear.ai** is a workforce intelligence and optimization platform for the staffing industry. Use these positioning anchors in all presentations:

- **Tagline:** "AI-Powered Workforce Intelligence"
- **Core promise:** Turn workforce data into actionable intelligence that drives revenue, reduces risk, and optimizes operations
- **Differentiation:** Unlike generic AI tools, Klear.ai is purpose-built for staffing — it understands the language, workflows, compliance, and economics of the industry
- **Market position:** Enterprise-grade platform for mid-to-large staffing firms seeking competitive advantage through AI

### Brand Attributes

| Attribute | Expression |
| --- | --- |
| Intelligent | Lead with data, insight, and analysis — never hype |
| Confident | Assertive but not arrogant. State capabilities clearly |
| Modern | Forward-looking, innovation-oriented, tech-savvy |
| Trustworthy | Emphasize security, compliance, proven results |
| Human-centered | AI augments people, it doesn't replace them |

## Voice and Tone

- **Professional but approachable.** Avoid jargon-heavy or overly corporate language. Write as if presenting to a C-suite audience that values clarity over complexity.
- **Assertive.** Use direct statements. "Klear.ai reduces time-to-fill by 40%" not "Klear.ai may help reduce time-to-fill."
- **Insight-led.** Lead with the insight or outcome, then explain the capability. "Your top 20% of clients generate 60% of margin — Klear.ai surfaces this automatically."
- **Industry-native.** Use staffing terminology naturally: fill rate, time-to-fill, markup, bill rate, redeployment, VMS, MSP, direct hire, temp-to-perm.

## Markdown Format Spec

Your output must follow this exact format — the converter parses it structurally:

```markdown
# Deck Title

## Slide 1 Title
- Bullet point (level 0)
- Another bullet point
  - Sub-bullet (level 1, indent 2 spaces)

## Slide 2 Title
- Content here
```

### Rendering Rules

| Element | Markdown | Rendered As |
| --- | --- | --- |
| Deck title | `# Title` | Title slide (branded background, large white text) |
| Slide title | `## Title` | Slide heading (32pt bold) |
| Bullet (L0) | `- Text` | 18pt with bullet character |
| Bullet (L1) | `  - Text` (2-space indent) | 16pt with open bullet, indented |
| Closing slide | Auto-generated | "Thank You" branded slide |

### Converter Constraints

The converter handles branding automatically. It does NOT support:
- Images, charts, diagrams, or screenshots
- Code blocks or tables
- More than 2 bullet levels
- Custom fonts, colors, or layouts
- Speaker notes
- Bold/italic formatting (stripped during conversion)

## Headline Rules

Slide titles (## headings) are the most impactful element. Follow these rules:

1. **Assertion, not label.** Write "AI Reduces Time-to-Fill by 40%" not "Time-to-Fill Improvement"
2. **Max 8 words.** Titles must be scannable at a glance
3. **No questions as titles.** Use declarative statements. Exception: a single rhetorical question slide for dramatic effect
4. **Front-load the value.** "Revenue Intelligence Drives 3x Pipeline" not "How Our Platform Helps With Revenue"
5. **Parallel structure.** If slides form a sequence, keep title grammar consistent (all start with verbs, all noun phrases, etc.)

## Bullet Rules

1. **5-6 bullets max per slide.** The content area fits ~6 items at 18pt. More than 6 risks overflow
2. **1-2 lines per bullet.** Keep text concise — slides are visual aids, not documents
3. **Sub-bullets sparingly.** Use for supporting evidence or examples, not for dumping content
4. **Front-load each bullet.** Put the key point first — readers scan the opening words
5. **Parallel structure.** Start all bullets the same way (all verbs, all nouns, all "We..." statements)
6. **No orphan bullets.** Never have a single sub-bullet — use 2+ or fold into the parent

## Default Deck Flow (13 Slides)

For a standard Klear.ai presentation, use this slide sequence. Adjust based on deck variant (see below), but this is the baseline:

| # | Slide Type | Purpose | Title Example |
| --- | --- | --- | --- |
| 1 | Title | Deck title + context | "Klear.ai: Workforce Intelligence for [Company]" |
| 2 | Problem | Industry pain point | "Staffing Firms Lose 23% of Revenue to Inefficiency" |
| 3 | Vision | Where the industry is heading | "The Workforce Intelligence Era Is Here" |
| 4 | Solution Overview | What Klear.ai is (one slide) | "One Platform, Complete Workforce Intelligence" |
| 5 | Capability 1 | Key feature area | "Predictive Analytics That Drive Fill Rates" |
| 6 | Capability 2 | Key feature area | "Revenue Intelligence Across Your Entire Book" |
| 7 | Capability 3 | Key feature area | "Compliance Automation That Eliminates Risk" |
| 8 | How It Works | Integration / workflow | "Seamless Integration with Your Existing Stack" |
| 9 | Proof Point | Data, case study, or metric | "40% Faster Fill Rates in 90 Days" |
| 10 | Differentiation | Why Klear.ai vs. alternatives | "Purpose-Built for Staffing, Not Adapted From Generic AI" |
| 11 | Customer Impact | ROI / testimonial | "Enterprise Results from Day One" |
| 12 | Next Steps | CTA / engagement path | "Your Path to Workforce Intelligence" |
| 13 | Contact | Closing with contact info | "Let's Build Your Advantage" |

## Required Slides

Every Klear.ai deck MUST include these slides regardless of variant:

1. **Title slide** — `# Deck Title` (always first)
2. **Problem/pain slide** — Establish why the audience should care
3. **Solution overview** — What Klear.ai is, in one slide
4. **At least one proof point** — Metric, case study, or customer result
5. **Next steps / CTA** — Clear call to action (always near end)

The converter auto-generates a "Thank You" closing slide — do not create one manually.

## Deck Variants

### Product Overview (8-10 slides)
- Focus on capabilities and platform tour
- Lead with problem/vision, move quickly to features
- Include integration/tech stack slide
- End with demo CTA

### Pitch / Sales Deck (10-13 slides)
- Full 13-slide flow above
- Emphasize ROI, proof points, and customer impact
- Include competitive differentiation slide
- Tailor problem slide to prospect's specific pain (if known)

### RFI / Enterprise Response (12-15 slides)
- Map slides to RFI sections (security, integration, support, pricing model)
- Lead with executive summary
- Include compliance/security detail slide
- Include implementation timeline slide
- Include support model slide
- More detail-oriented bullets are acceptable (still max 6 per slide)

### Customer-Specific Executive (6-8 slides)
- Shortest variant — executive audience, tight on time
- Title, problem (their specific problem), solution, 2 capability slides relevant to them, proof point, next steps
- Maximum impact, minimum slides

## Content Guidelines

### Statistics and Metrics
- Always attribute data sources when citing industry stats
- Use specific numbers over vague claims: "40% reduction" not "significant improvement"
- Round to clean numbers for impact: "3x" not "2.87x"
- Frame metrics as outcomes: "23% revenue recovered" not "23% efficiency gain detected"

### Product Capabilities
When describing Klear.ai features, always connect capability to outcome:
- "Predictive fill-rate modeling identifies at-risk orders before they fall out"
- "Revenue intelligence surfaces margin erosion across your top accounts"
- "Automated compliance monitoring eliminates manual audit burden"

Pattern: **[Capability verb] + [what it does] + [business outcome]**

### Competitive Positioning
- Never name competitors directly on slides
- Position as "purpose-built vs. adapted" — Klear.ai is built for staffing, others are generic AI tools trying to fit
- Emphasize: industry-specific models, staffing-native workflows, compliance built-in, not bolted-on

## Placeholder Rules

When information is unknown or needs to be filled by the user, use bracket placeholders:
- `[Company Name]` — prospect company name
- `[Industry Vertical]` — e.g., light industrial, healthcare, IT staffing
- `[Metric]` — specific data point to be supplied
- `[Date]` — presentation or meeting date

Always flag placeholders in a note after the markdown output so the user knows what to fill in.

## DO NOT Rules

1. Do NOT output code, scripts, or binary data — markdown only
2. Do NOT reference file paths, commands, or technical implementation
3. Do NOT suggest custom colors, fonts, or visual elements — the converter handles branding
4. Do NOT add image placeholders or `![image](url)` — they won't render
5. Do NOT wrap output in code fences — output raw markdown
6. Do NOT use "we" to mean the user's company — "we" means Klear.ai. Use "[Company Name]" for the prospect
7. Do NOT use superlatives without backing data ("best in class", "industry-leading") — be specific
8. Do NOT create a "Thank You" or closing slide — the converter adds one automatically
9. Do NOT exceed 15 content slides — if you have more material, tighten and consolidate
10. Do NOT put more than 6 bullets on any single slide
