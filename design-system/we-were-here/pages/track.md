# Track Page Overrides

> **PROJECT:** We Were Here
> **Generated:** 2026-10-11 03:34:28
> **Page Type:** General

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** Hero with search bar > Popular categories > FAQ accordion > Contact/support CTA

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Clean, high readability. Minimal color. Category icons in brand color. Success green for resolved.

### Component Overrides

- Avoid: Block or ignore autofill
- Avoid: No feedback after submit
- Avoid: Placeholder-only inputs

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Tonal elevation (overlay colors instead of strong shadows), pill-shaped buttons and chips (borderRadius 999), emphasized easing Easing.bezier(0.2,0,0,1), state layers (pressed overlays 10–15% opacity), Reanimated-filled label float for inputs, HapticFeedback on FAB/toggles
- Forms: Use autocomplete attribute properly
- Forms: Show loading then success/error state
- Accessibility: Use label with for attribute or wrap input
- CTA Placement: Search bar prominent + Contact CTA for unresolved questions
