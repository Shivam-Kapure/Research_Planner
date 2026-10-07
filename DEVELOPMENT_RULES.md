# Development Rules

These rules apply to all contributors, including AI assistants.

## Git
1. Never run `git commit` or `git push` automatically. Team members commit manually.
2. Never manipulate git history (no rebase, amend, reset, force-push or squash of shared history).
3. At the end of each phase, the assistant reports whether to commit, which files to commit and the exact commit message. It does not commit.

## Integrity
4. Never fabricate commits, contributions, execution traces, test results or any other project evidence.
5. Execution traces must come from real runs that show actual agent handoffs.
6. Tests must exercise actual behaviour. No tautological tests, and no mocks that bypass the logic under test.
7. No placeholder application code written just to make the repository look complete.

## Security
8. Never put secrets, API keys, passwords or database credentials in tracked files. Use untracked environment configuration, with only example files committed.
9. User Groq/Gemini keys are supplied at runtime after authentication and are never committed.

## Process
10. Inspect existing files before creating or modifying anything.
11. Make the smallest coherent change the current phase needs.
12. Stay within the current phase's scope. Do not install dependencies or choose the stack before the phase that calls for it.
13. Keep development token-efficient: no unnecessary docs or explanations, and do not restate the requirements.
