Review all uncommitted changes for quality:

1. Run `git diff` to see all changes
2. Check for:
   - Security issues (hardcoded secrets, SQL injection, XSS)
   - Debug statements left in code
   - Missing error handling at system boundaries
   - Naming consistency
   - Test coverage for new logic
3. Provide a brief verdict: ship it, or list specific issues to fix
