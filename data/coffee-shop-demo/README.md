<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-gold?style=for-the-badge" alt="MIT License">
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" alt="CSS3">
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript">
  <img src="https://img.shields.io/badge/Responsive-4CAF50?style=for-the-badge" alt="Responsive">
</p>

<h1 align="center">Ember & Brew</h1>

<p align="center">
  <strong>A premium, open-source coffee shop website template</strong><br>
  Beautiful. Responsive. Ready to deploy.
</p>

<p align="center">
  <a href="#features">Features</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#tech-stack">Tech Stack</a> &middot;
  <a href="#screenshots">Screenshots</a> &middot;
  <a href="#customization">Customization</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

---

## About

Ember & Brew is a fully responsive, single-page website template designed for coffee shops, cafes, roasteries, and specialty beverage businesses. Built with vanilla HTML, CSS, and JavaScript -- no frameworks, no build tools, no dependencies. Just open `index.html` and you're live.

The design draws on warm, artisan aesthetics: dark browns, soft creams, and gold accents. Typography pairs **Playfair Display** (headings) with **Inter** (body text) via Google Fonts for a refined editorial feel.

## Features

- **Hero Section** -- Full-viewport background with parallax scrolling and animated text entrance
- **About Section** -- Two-column layout with story text, key stats, and a feature image
- **Interactive Menu** -- Filterable categories (Espresso, Drip & Pour Over, Cold Brew, Pastries) with hover animations
- **Photo Gallery** -- Responsive grid with hover overlays and zoom transitions
- **Contact & Location** -- Hours of operation, address, phone, plus a styled contact form
- **Sticky Navigation** -- Transparent-to-solid nav bar on scroll with smooth section linking
- **Mobile Responsive** -- Hamburger menu, stacked layouts, and touch-friendly interactions
- **CSS Animations** -- Intersection Observer-powered fade-in effects for menu items and sections
- **Dark Warm Theme** -- CSS custom properties for easy color customization
- **Zero Dependencies** -- No npm, no build step, no framework lock-in
- **SEO Ready** -- Semantic HTML5, proper heading hierarchy, descriptive alt text
- **Accessible** -- Keyboard-navigable, proper focus states, ARIA-compatible structure

## Screenshots

| Desktop | Mobile |
|---------|--------|
| ![Desktop Hero](docs/screenshots/desktop-hero.png) | ![Mobile Menu](docs/screenshots/mobile-menu.png) |
| ![Desktop Menu](docs/screenshots/desktop-menu.png) | ![Mobile Nav](docs/screenshots/mobile-nav.png) |

> Screenshots coming soon. To generate your own, open `index.html` in a browser and capture at 1440px (desktop) and 375px (mobile).

## Quick Start

### Option 1: Direct Download

```bash
# Clone the repository
git clone https://github.com/cybershieldagency/ember-and-brew.git

# Navigate to the project
cd ember-and-brew

# Open in your browser
open index.html
```

That's it. No install. No build. No config.

### Option 2: GitHub Pages

1. Fork this repository
2. Go to **Settings > Pages**
3. Set source to **Deploy from a branch** > `main` / `root`
4. Your site will be live at `https://your-username.github.io/ember-and-brew/` (or `https://cybershieldagency.github.io/ember-and-brew/` for the main repo)

### Option 3: Local Development Server

If you want live reload during development:

```bash
# Using Python
python3 -m http.server 3000

# Using Node.js (npx)
npx serve .

# Using PHP
php -S localhost:3000
```

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| **HTML5** | Semantic structure and content |
| **CSS3** | Styling, animations, responsive design |
| **Vanilla JavaScript** | Intersection Observer, menu filtering, nav behavior |
| **Google Fonts** | Playfair Display (headings) + Inter (body) |
| **Unsplash** | High-quality stock photography |
| **CSS Custom Properties** | Theming and color management |
| **GitHub Actions** | Automated deployment to GitHub Pages |

### Design Tokens

```css
--primary:    #3E2723   /* Dark Coffee */
--secondary:  #D7CCC8   /* Light Cream */
--accent:     #FFB300   /* Gold */
--bg-dark:    #1A120B   /* Deep Background */
--bg-light:   #F5F5F5   /* Light Background */
```

## Project Structure

```
ember-and-brew/
├── index.html              # Single-page website (all HTML, CSS, JS)
├── README.md               # This file
├── LICENSE                  # MIT License
├── CONTRIBUTING.md          # Contribution guidelines
├── CHANGELOG.md            # Version history
├── package.json            # Project metadata (optional, for tooling)
├── .gitignore              # Git ignore rules
├── .github/
│   ├── workflows/
│   │   └── deploy.yml      # GitHub Pages deployment
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md   # Bug report template
│       └── feature_request.md  # Feature request template
└── docs/
    └── screenshots/        # Project screenshots
```

## Customization

### Changing Colors

All colors are defined as CSS custom properties in `:root`. Edit these values in `index.html`:

```css
:root {
    --primary: #3E2723;    /* Change to your brand's dark color */
    --secondary: #D7CCC8;  /* Change to your brand's light color */
    --accent: #FFB300;      /* Change to your brand's accent color */
}
```

### Updating Menu Items

Each menu item follows this structure:

```html
<div class="menu-item" data-category="espresso">
    <div class="menu-img">
        <img src="your-image-url" alt="Item Name">
    </div>
    <div class="menu-details">
        <div class="menu-header">
            <h3 class="menu-title">Item Name</h3>
            <span class="menu-price">$X.XX</span>
        </div>
        <p class="menu-desc">Description of the item.</p>
    </div>
</div>
```

Set `data-category` to match one of the filter buttons: `espresso`, `drip`, `cold`, or `pastry`.

### Adding New Categories

1. Add a new filter button in the `.menu-filters` div
2. Add menu items with the matching `data-category` value
3. The JavaScript filter logic handles the rest automatically

### Replacing Images

All images use Unsplash URLs. Replace with your own photos:
- Hero: 1920px wide recommended
- Menu items: 600px wide recommended
- Gallery: 800px wide recommended

## Browser Support

| Browser | Version |
|---------|---------|
| Chrome | 80+ |
| Firefox | 75+ |
| Safari | 13+ |
| Edge | 80+ |
| Mobile Safari | iOS 13+ |
| Chrome Android | 80+ |

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Guide

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/your-feature`
3. **Commit** your changes: `git commit -m 'Add your feature'`
4. **Push** to the branch: `git push origin feature/your-feature`
5. **Open** a Pull Request

### What We're Looking For

- Accessibility improvements
- Performance optimizations
- New section templates (testimonials, team, blog)
- Dark mode toggle
- Multi-language support
- Integration examples (Netlify, Vercel, Cloudflare Pages)

## License

This project is licensed under the **MIT License** -- see the [LICENSE](LICENSE) file for details.

You are free to use this template for personal and commercial projects. Attribution is appreciated but not required.

---

<p align="center">
  Built with care by <a href="https://github.com/cybershieldagency">Cybershield Agency</a> and the open-source community<br>
  <strong>Ember & Brew</strong> -- Where every cup tells a story
</p>
