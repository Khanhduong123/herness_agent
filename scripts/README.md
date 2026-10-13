# Utility Scripts

This directory contains standalone utility scripts for automated inspection, audits, and validations.

---

## 1. Design & Viewport Audit (`design-audit.mjs`)

`design-audit.mjs` is a standalone, MCP-free design audit script. It opens a web page or local HTML file in Chromium (via Playwright), captures full-page screenshots across 6 standard viewport tiers, and performs automated heuristic checks for common web UI/UX defects:
- Horizontal overflow and layout breakage
- Unsized media (`<img>` tags lacking explicit dimensions causing Cumulative Layout Shift)
- Missing `alt` attributes on images
- Mobile touch target sizes (< 44×44px on viewports <= 480px)
- Focus visibility and indicator presence for accessibility
- Missing accessible names on buttons and interactive links
- Heading hierarchy (ensuring single `<h1>`)
- Document metadata (`<meta name="viewport">`, `lang` attribute)
- WCAG AA text contrast ratio heuristics
- Page errors and browser console errors

### Supported Viewports
- **Mobile:** `360×800` (mobile-360), `390×844` (mobile-390)
- **Tablet:** `768×1024` (tablet-768)
- **Laptop:** `1024×768` (laptop-1024)
- **Desktop:** `1440×900` (desktop-1440), `1920×1080` (wide-1920)

### Prerequisites

Playwright and Chromium are required to run the browser audit:
```bash
npm install -g playwright && npx playwright install chromium
```
*(Or install locally in your project: `npm install playwright && npx playwright install chromium`)*

### CLI Usage

Display help and usage details:
```bash
node scripts/design-audit.mjs --help
```

Audit a live web URL:
```bash
node scripts/design-audit.mjs --url http://localhost:3000 --out audit-output
```

Audit a local HTML file:
```bash
node scripts/design-audit.mjs --file ./index.html
```

Specify a custom Chromium executable path:
```bash
node scripts/design-audit.mjs --url http://localhost:3000 --executable /path/to/chromium
```
Or use the environment variable:
```bash
export PW_EXECUTABLE_PATH=/path/to/chromium
```

### Outputs
The audit outputs artifacts to `--out <dir>` (default: `audit-output`):
- `report.md`: Structured Markdown audit report detailing findings grouped by severity (HIGH, MEDIUM, LOW), console errors, and viewport screenshots.
- `report.json`: Machine-readable JSON summary containing all findings and console logs.
- `screenshots/`: Full-page screenshots across all audited viewport sizes.
