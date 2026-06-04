#!/bin/bash
# Pre-commit quality check hook
# Add project-specific checks as the project evolves

echo "Running pre-commit checks..."

# Check for debug statements (customize patterns per language)
if git diff --cached --name-only | xargs grep -l "console\.log\|debugger\|binding\.pry\|import pdb" 2>/dev/null; then
  echo "WARNING: Debug statements found in staged files"
fi

echo "Pre-commit checks complete."
