# Design System Master File — Third Shahrivar: We Were Here

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Third Shahrivar - We Were Here  
**Updated:** 2026-08-21  
**Category:** Music Event / Concert Landing Page + Payment Flow + Tracking  
**Aesthetic:** Gothic + Cute (Dark, dramatic, playful, high-contrast)

> **IMPLEMENTED 2026-08-21:** 3-step payment flow (info → card/receipt → pending) live on
> `index.html`, separate tracking page at `/track` (`track.html`), and order-review UI
> in the admin panel. See `pages/index.md`, `pages/track.md`, `pages/admin.md` for page-level rules.

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Primary | `#FFFFFF` | `--color-primary` | Headlines, key text, primary buttons |
| Secondary | `#B8B8C0` | `--color-secondary` | Body text, descriptions |
| Muted | `#7A7A85` | `--color-muted` | Placeholders, timestamps, helper text |
| Accent | `#D43F5A` | `--color-accent` | **Cute accent** — hearts, highlights, hover states |
| Accent Soft | `#E86B82` | `--color-accent-soft` | Lighter accent for gradients/glows |
| Background | `#0A0A0B` | `--color-bg` | Page background (near-black) |
| Surface | `#141416` | `--color-surface` | Cards, modals, elevated elements |
| Surface Light | `#1E1E22` | `--color-surface-light` | Hover states, inputs |
| Border | `#2A2A2E` | `--color-border` | Borders, dividers |
| Border Light | `#3A3A3F` | `--color-border-light` | Focus rings, active borders |
| Success | `#5EC98B` | `--color-success` | Approved status, success states |
| Warning | `#F5C542` | `--color-warning` | Pending status |
| Danger | `#FF5A5A` | `--color-danger` | Rejected status, errors |

**Color Notes:** Deep black base with pure white text. Single **cute accent** (soft pink-red `#D43F5A`) for playful Gothic contrast. No other colors.

### Typography

> **RTL-first:** All page copy is Persian. Both faces MUST have full Persian/Arabic glyph coverage.

- **Display Font:** **Vazirmatn** (variable 100–900) — headings use 800/900, tight tracking on Latin/digits only
- **UI Font:** **Vazirmatn** (variable) — body 400, buttons 600, labels 500
- **Mono Font:** **JetBrains Mono** (for serial numbers, card digits, code) — Latin/digits only

**Google Fonts:**
```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Vazirmatn:wght@100..900&display=swap');
```

**Fallback stack:** `'Vazirmatn', 'Segoe UI', Tahoma, sans-serif`

> **CRITICAL — Persian letter joining:** NEVER apply `letter-spacing` to Persian/Arabic text — it disconnects cursive letters ("ت ا ر ی خ"). `letter-spacing` ONLY safe on isolated glyphs: Latin letters and digits (serial numbers, card numbers).

**Type Scale:**

| Element | Font | Weight | Size | Line-height | Letter-spacing |
|---------|------|--------|------|-------------|----------------|
| Hero Title | Vazirmatn | 900 | `clamp(3.5rem, 14vw, 10rem)` | 0.85 | `-0.03em` (Latin only) |
| Section Title | Vazirmatn | 800 | `clamp(2rem, 5vw, 3.5rem)` | 1.0 | `-0.02em` |
| Card Title | Vazirmatn | 700 | `1.125rem` | 1.2 | `0` |
| Body | Vazirmatn | 400 | `1rem` | 1.7 | `0` |
| Label | Vazirmatn | 500 | `0.8125rem` | 1.4 | `0` |
| Button | Vazirmatn | 600 | `1rem` | 1.0 | `0.05em` (Latin) |
| Serial / Card | JetBrains Mono | 600 | `1.25rem` | 1.0 | `0.15em` |
| Small / Caption | Vazirmatn | 400 | `0.8125rem` | 1.5 | `0` |

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps, icon spacing |
| `--space-sm` | `8px` / `0.5rem` | Inline gaps, form element gaps |
| `--space-md` | `16px` / `1rem` | Standard padding, card padding |
| `--space-lg` | `24px` / `1.5rem` | Section inner padding |
| `--space-xl` | `32px` / `2rem` | Component gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |
| `--space-4xl` | `96px` / `6rem` | Major section separation |

### Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-none` | `0` | **Default** — Gothic sharp corners |
| `--radius-sm` | `4px` | Inputs, small badges |
| `--radius-md` | `8px` | Cards (cute softness) |
| `--radius-lg` | `16px` | Modals, large cards |
| `--radius-full` | `9999px` | Pills, badges, avatar |

**Rule:** Default to `0` (sharp). Use `--radius-md` ONLY for "cute" interactive elements (buttons, cards, inputs). Never on layout containers.

### Shadows & Glows

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.4)` | Subtle depth |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.5)` | Cards, dropdowns |
| `--shadow-lg` | `0 12px 24px rgba(0,0,0,0.6)` | Modals, sheets |
| `--glow-accent` | `0 0 24px rgba(212, 63, 90, 0.35)` | Accent glow on hover/focus |
| `--glow-white` | `0 0 32px rgba(255,255,255,0.08)` | Hero title subtle glow |

### Transitions

| Token | Value | Usage |
|-------|-------|-------|
| `--transition-fast` | `120ms ease` | Hover color changes |
| `--transition-base` | `200ms ease` | Standard (borders, backgrounds) |
| `--transition-slow` | `350ms ease` | Modals, panels, transforms |

### Texture & Atmosphere

- **Film grain overlay** — subtle static noise on `body::before` (opacity 0.03–0.05)
- **Scanlines** — optional subtle horizontal lines on hero (opacity 0.02)
- **Vignette** — subtle radial darkening at edges

---

## Component Specs

### Buttons

```css
/* Primary — White on Black (Gothic) */
.btn-primary {
  background: var(--color-primary);
  color: var(--color-bg);
  border: 2px solid var(--color-primary);
  padding: 14px 32px;
  border-radius: var(--radius-md);
  font-family: var(--font-ui);
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  transition: all var(--transition-base);
  cursor: pointer;
  position: relative;
  overflow: hidden;
}
.btn-primary::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--color-accent);
  transform: translateX(-101%);
  transition: transform var(--transition-base);
  z-index: -1;
}
.btn-primary:hover {
  background: var(--color-bg);
  color: var(--color-primary);
  border-color: var(--color-primary);
}
.btn-primary:hover::before {
  transform: translateX(0);
}
.btn-primary:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--color-accent-soft);
}

/* Secondary — Outline */
.btn-secondary {
  background: transparent;
  color: var(--color-primary);
  border: 2px solid var(--color-border-light);
  padding: 14px 32px;
  border-radius: var(--radius-md);
  font-family: var(--font-ui);
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  transition: all var(--transition-base);
  cursor: pointer;
}
.btn-secondary:hover {
  border-color: var(--color-primary);
  background: rgba(255,255,255,0.05);
}
.btn-secondary:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--color-primary);
}

/* Accent — Cute Gothic */
.btn-accent {
  background: var(--color-accent);
  color: var(--color-primary);
  border: 2px solid var(--color-accent);
  padding: 14px 32px;
  border-radius: var(--radius-md);
  font-family: var(--font-ui);
  font-size: 1rem;
  font-weight: 600;
  transition: all var(--transition-base);
  cursor: pointer;
  box-shadow: var(--glow-accent);
}
.btn-accent:hover {
  background: var(--color-accent-soft);
  border-color: var(--color-accent-soft);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(212, 63, 90, 0.4);
}
```

### Cards

```css
.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-lg);
  transition: all var(--transition-base);
}
.card:hover {
  border-color: var(--color-border-light);
  background: var(--color-surface-light);
  box-shadow: var(--shadow-md);
}
.card--interactive {
  cursor: pointer;
}
```

### Inputs

```css
.input-wrapper {
  position: relative;
}
.input-label {
  display: block;
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--color-secondary);
  margin-bottom: var(--space-xs);
}
.input {
  width: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  font-family: var(--font-ui);
  font-size: 1rem;
  color: var(--color-primary);
  transition: all var(--transition-fast);
}
.input::placeholder {
  color: var(--color-muted);
}
.input:focus {
  border-color: var(--color-border-light);
  outline: none;
  box-shadow: 0 0 0 2px var(--color-accent-soft);
}
.input.error {
  border-color: var(--color-danger);
}
.input.error:focus {
  box-shadow: 0 0 0 2px rgba(255, 90, 90, 0.3);
}
.input-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-muted);
  pointer-events: none;
}
.input-has-icon .input {
  padding-left: 44px;
}
```

### Badges / Status Pills

```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.badge--pending { background: rgba(245, 197, 66, 0.15); color: var(--color-warning); border: 1px solid var(--color-warning); }
.badge--approved { background: rgba(94, 201, 139, 0.15); color: var(--color-success); border: 1px solid var(--color-success); }
.badge--rejected { background: rgba(255, 90, 90, 0.15); color: var(--color-danger); border: 1px solid var(--color-danger); }
.badge--group { background: var(--color-surface-light); color: var(--color-secondary); border: 1px dashed var(--color-border); }
```

### Dividers

```css
.divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--color-border), transparent);
}
.divider--thick {
  height: 2px;
  background: var(--color-border);
}
```

---

## Style Guidelines

**Style:** **Gothic Cute** — Dark, dramatic, high-contrast monochrome with a single playful accent.

**Keywords:** Raw, stark, oversized typography, monochrome, concert poster, playful darkness, sharp edges with soft touches.

**Key Effects:**
- `font-size: clamp(3.5rem, 14vw, 10rem)` for hero, `font-weight: 900`
- **No letter-spacing on Persian text** (see typography rule)
- **Sharp corners by default** (`border-radius: 0`), rounded only on interactive "cute" elements
- Pure near-black background (`#0A0A0B`) with white text
- Massive whitespace, single-column centered layout
- Subtle film grain texture throughout
- Accent glow animations on interactive elements

### Page Pattern

**Pattern Name:** Event/Experience Landing + Payment Flow

- **Section Order (Landing):** 1. Hero (date/countdown/event name), 2. Experience concept, 3. Registration + Payment, 4. Post-event access, 5. Footer
- **Payment Flow:** Registration → Card Info → Receipt Upload → Pending → Approved → Ticket Reveal
- **Ticket Tracking Page:** Phone lookup → Status + Tickets
- **CTA Placement:** Hero (scroll to register) + Register section (primary) + Payment section (accent)
- **Conversion Strategy:** Scarcity (50 tickets), personalized experience, post-event value, payment flexibility

---

## Anti-Patterns (Do NOT Use)

- ❌ Complex navigation — Keep it single-page, no navbar
- ❌ Multiple colors — Strictly B&W + single accent
- ❌ Rounded corners on layout — Only on interactive cute elements
- ❌ Soft shadows as primary depth — Use borders first
- ❌ Emoji icons — Use SVG icons (Lucide style)
- ❌ Missing `cursor:pointer` — All clickable elements must have it
- ❌ Layout-shifting hovers — No scale transforms on cards
- ❌ Low contrast text — Maintain 7:1+ contrast on black
- ❌ Instant state changes — Use transitions (150-350ms)
- ❌ Invisible focus states — Accent focus ring on black background
- ❌ `letter-spacing` on Persian text — breaks cursive joining
- ❌ Latin-only display fonts — Must support Persian glyphs

---

## Pre-Delivery Checklist

- [ ] No emojis used as icons (use SVG instead)
- [ ] All layout corners sharp (`border-radius: 0`)
- [ ] Interactive elements have `cursor:pointer`
- [ ] Hover states with smooth transitions (150-350ms)
- [ ] Text contrast 7:1+ on black background
- [ ] Focus states visible (accent ring) for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed elements
- [ ] No horizontal scroll on mobile
- [ ] Fonts loaded: Vazirmatn (Persian), JetBrains Mono (digits)
- [ ] Persian text has NO letter-spacing
- [ ] Serial/card numbers use JetBrains Mono with letter-spacing
- [ ] Single accent color used consistently