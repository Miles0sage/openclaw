# Contributing to Ember & Brew

Thanks for your interest in contributing! This project is a coffee shop website template designed to be forked, customized, and deployed by anyone.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Open `index.html` in your browser (or run `npx serve .` for a local dev server)

## How to Contribute

### Reporting Bugs

- Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template
- Include browser, OS, and steps to reproduce
- Screenshots are always helpful

### Suggesting Features

- Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template
- Explain the use case, not just the solution

### Submitting Code

1. Create a branch from `main`: `git checkout -b feature/your-feature`
2. Make your changes
3. Test on mobile and desktop viewports
4. Ensure no console errors
5. Commit with a clear message: `git commit -m "feat: add seasonal menu toggle"`
6. Push and open a Pull Request against `main`

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `style:` formatting, no code change
- `refactor:` code restructuring
- `test:` adding or updating tests
- `chore:` maintenance tasks

## Code Style

- Use semantic HTML elements
- Keep CSS organized by section (nav, hero, menu, etc.)
- Use CSS custom properties (variables) defined in `:root`
- Mobile-first responsive design
- Accessible: proper alt text, ARIA labels, keyboard navigation
- No external CSS frameworks -- keep it vanilla

## Project Structure

```
ember-and-brew/
  index.html          # Main single-page site
  package.json        # Project metadata and scripts
  README.md           # Project documentation
  LICENSE             # MIT License
  CONTRIBUTING.md     # This file
  .github/
    workflows/        # CI/CD (GitHub Pages deploy)
    ISSUE_TEMPLATE/   # Bug report & feature request templates
```

## Questions?

Open a [Discussion](../../discussions) or file an issue. We're happy to help.
