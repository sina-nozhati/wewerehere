# Index Page Overrides

> **PROJECT:** We Were Here
> **Generated:** 2026-10-11 03:53:16
> **Page Type:** Landing / Marketing

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** Hero (date/location/countdown) > Speakers grid > Agenda/schedule > Sponsors > Register CTA

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Urgency colors (countdown). Event branding. Speaker cards professional. Sponsor logos neutral.

### Component Overrides

- Avoid: Missing or incorrect viewport
- Avoid: Expect z-index to work across contexts
- Avoid: Use arbitrary large z-index values

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: z-index stacking, box-shadow elevation (4 levels), transform: translateZ(), backdrop-filter, parallax
- Responsive: Use width=device-width initial-scale=1
- Layout: Understand what creates new stacking context
- Layout: Define z-index scale system (10 20 30 50)
- CTA Placement: Register CTA sticky + After speakers + Bottom
