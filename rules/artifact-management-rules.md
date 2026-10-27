# Artifact Management Rules

1. **Project-local output.** Save generated artifacts in the user's project, never in the plugin installation directory. The project root is the working directory of the Claude Code session.
2. **Output location.** `<project-root>/atomic_requirements/atomic_requirements.json`. Create the `atomic_requirements/` directory if it does not exist.
3. **Never modify source documents.** The original requirement files are read-only inputs. No tool call may write to, move or delete them.
4. **Validate before writing.** The complete output must pass the validator (`scripts/validate-atomic-requirements.py`) and the semantic quality checks before it is written to the project. Intermediate drafts live in a temporary directory outside the project and the plugin.
5. **No silent overwrite.** Check whether the output file exists first. If it does, explain the situation, state that IDs will be freshly assigned (see `requirement-id-rules.md`), and ask the user whether to replace it, save under a different file name in the same directory, or cancel. Do nothing until the user answers.
6. **Verify after writing.** Read the saved file back, confirm it exists, parses as JSON and passes the validator, and that it matches the validated draft.
7. **Report exact paths.** Report the absolute path of the saved file and of every source file analysed.
8. **Exclude generated artifacts from sources.** `atomic_requirements/` and its contents are never treated as requirement sources.
