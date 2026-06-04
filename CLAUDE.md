# KIBANA-OO Project

## Overview

This is the KIBANA-OO project. Update this section with project description as it evolves.

## Development Guidelines

- Follow conventional commits: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`
- Write tests before or alongside implementation
- Keep PRs focused and small
- All code must pass linting and tests before commit
- Never commit `.env` files or secrets

## Architecture

_Document architecture decisions here as the project develops._

## Custom Slash Commands

- `/status` — Show project status: recent commits, uncommitted changes, TODOs
- `/review` — Review uncommitted changes for quality, security, naming
- `/clean` — Scan for TODOs, dead code, oversized files

## Conventions

- Use clear, descriptive variable and function names
- Prefer composition over inheritance
- Handle errors explicitly — no silent failures
- Keep functions small and focused (single responsibility)
- Use `.editorconfig` settings (2-space indent, LF line endings, UTF-8)

## Project Structure

```
.claude/              # Claude Code configuration
  commands/           # Custom slash commands
  hooks/              # Automation hooks
  settings.json       # Permission rules
.github/              # GitHub templates and CI
  ISSUE_TEMPLATE/     # Bug report and feature request templates
  workflows/          # GitHub Actions CI pipeline
  pull_request_template.md
.editorconfig         # Editor-agnostic formatting rules
.gitignore            # Ignored files and directories
CLAUDE.md             # This file — project guidelines for Claude
```

## Important Files

_Track key files and their purposes here as the project grows._
