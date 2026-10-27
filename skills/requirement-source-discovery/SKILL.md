---
name: requirement-source-discovery
description: Resolve a user-supplied folder name, directory path or filename to Markdown requirement files, handle ambiguous matches, and read each file completely. Use when locating or reading the source for a requirements analysis.
---

# Requirement Source Discovery

Phase 1 supports **Markdown (`.md`) files only**. Do not parse `.txt`, `.pdf`, `.docx` or any other format.

The project root is the working directory of the session. Resolve everything against it.

## 1. Resolve the user's input

Classify the input and resolve it in this order:

| Input | Resolution |
|---|---|
| Absolute path (`D:/x/BRD.md`, `/home/x/reqs`) | Use directly. |
| Relative path (`./requirements/`, `docs/BRD.md`) | Resolve against the project root. |
| Folder name (`requirements`) | Look for a directory with that name directly under the project root, then anywhere under it (Glob `**/<name>`, skipping excluded directories). |
| Filename (`BRD.md`) | Glob `**/<name>` under the project root, skipping excluded directories. |

Then:

1. **No match / path does not exist:** say so and ask for a valid location. Do not guess.
2. **Several matches:** list every candidate with its full path and ask the user to choose. Never pick one silently.
3. **Outside the project root:** an absolute path outside the project root is acceptable only after the user confirms they want it read.
4. **File that is not `.md`:** explain that Phase 1 supports only Markdown and ask for a `.md` source.

## 2. Discover files in a directory

1. Collect `.md` files recursively (Glob `**/*.md` inside the directory).
2. Exclude hidden directories (names starting with `.`), `node_modules`, `atomic_requirements/` and other generated output directories, and temporary files (`~$*`, `*.tmp`, `*.bak`).
3. Remove duplicates (same resolved path; symlink targets already listed).
4. Count the non-Markdown files you did not process, by extension, so you can report them. Logs, temp files and generated reports are not reported individually.
5. Do not decide silently what is "relevant". If more than one `.md` file remains, show the full list (path and size or line count) and ask the user to confirm the source set. Files that look unrelated (for example `README.md`, `CHANGELOG.md`, `LICENSE.md`) stay on the list, marked as "probably not requirements", for the user to keep or drop.
6. A directory with no `.md` files: report that nothing eligible was found, mention any non-Markdown files present, and ask for another source.

## 3. Read each file completely

1. Get the line count with `wc -l` (or `(Get-Content -LiteralPath <file>).Count` on PowerShell) before reading.
2. Read with the Read tool. It returns a limited number of lines per call, so page with `offset` and `limit` until the last line has been read. Do not stop after the first page.
3. Read the whole file: headings, lists, tables, code blocks, quotes. Nothing is skipped because it looks unimportant.
4. If a file has very long lines that the tool truncates, read those lines another way (for example with Grep or a shell command) so no text is lost.
5. Record for each file: absolute path, total lines, lines read, status.

## 4. Detect problems

| Condition | Action |
|---|---|
| Empty file (0 bytes or only whitespace) | Tell the user. Stop or ask for another source. Do not count it as analysed. |
| Missing or inaccessible file | Explain the cause. Do not claim it was analysed. |
| Unreadable or binary content, encoding errors | Explain the issue. Do not claim it was analysed. |
| Read stopped early / lines read < total lines | Mark the file `PARTIAL`; do not claim full analysis. |
| Generated artifact (for example inside `atomic_requirements/`) | Never treat as a requirement source. |

## 5. Report accurately

State the number of files confirmed, the number fully read, any `PARTIAL` or failed files, and the non-Markdown files excluded. If anything was not fully read, say so in the final summary instead of claiming completion.

Never write to, move or delete a source file.
