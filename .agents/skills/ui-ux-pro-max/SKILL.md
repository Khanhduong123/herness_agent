---
name: ui-ux-pro-max
description: Comprehensive UI/UX Pro Max intelligence engine with design system recommendations, BM25 style/color search, typography pairings, component rules, and stack-specific guidelines. Use when crafting visual designs, choosing color palettes, styling components, selecting fonts, generating design tokens, building responsive layouts, or conducting UX review across web and mobile frameworks.
---

# UI/UX Pro Max Skill

## Overview

The `ui-ux-pro-max` skill provides evidence-backed design intelligence and search tools across 12 design domains (styles, colors, charts, landing pages, products, UX guidelines, typography, icons, GSAP motions, React, web best practices, Google fonts) and 16 framework stacks (React, React Native, Vue, Svelte, Astro, SwiftUI, Flutter, HTML/Tailwind, and more).

## When to Use

- Generating design systems (`--design-system`) for applications, SaaS dashboards, and landing pages.
- Choosing color palettes with contrast verification (`--domain color`).
- Selecting typography pairings with Google Fonts imports (`--domain typography` or `--domain google-fonts`).
- Looking up data visualization recommendations and chart types (`--domain chart`).
- Searching UX interaction dos and don'ts with code examples (`--domain ux`).
- Applying framework-specific design and accessibility best practices (`--stack <stack>`).
- Calibrating design dials (`--variance`, `--motion`, `--density`) for tailored UI tokens.

## CLI Search Engine Usage

The search engine can be executed from any directory using Python:

```bash
# General domain search
python .agents/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain>

# Full design system generation (tokens, typography, colors, patterns)
python .agents/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system

# Framework stack guidelines
python .agents/skills/ui-ux-pro-max/scripts/search.py "<query>" --stack <stack>

# JSON formatted output
python .agents/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain> --json
```

### Supported Domains
- `style`: UI styles (Glassmorphism, Bento, Brutalism, Minimalism, Neumorphism, etc.)
- `color`: Curated palettes with contrast notes and semantic roles
- `chart`: Chart selection, data types, accessibility fallbacks
- `landing`: Landing page conversion patterns and section layouts
- `product`: Product recommendations, style pairings, and dashboard styles
- `ux`: Interaction patterns, severity, dos and don'ts, code examples
- `typography` / `google-fonts`: Font pairings, Google Fonts URLs, CSS imports
- `icons`: Icon recommendations and component imports
- `gsap`: Motion animation presets and parameters
- `react` / `web`: React and web engineering guidelines

### Supported Stacks
`react`, `react-native`, `flutter`, `swiftui`, `html-tailwind`, `nextjs`, `vue`, `svelte`, `astro`, `nuxtjs`, `nuxt-ui`, `shadcn`, `jetpack-compose`, `threejs`, `angular`, `laravel`.

### Design System Dials
- `--variance` (1-10): Visual boldness and asymmetry
- `--motion` (1-10): Motion intensity and GSAP snippets
- `--density` (1-10): Information density and spacing scales
