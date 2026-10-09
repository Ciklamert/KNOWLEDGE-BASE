---
description: Enhance a request with the AI-BRAIN knowledge base, then carry it out
argument-hint: <what you want to do>
---
1. Call the `brain` MCP tool `enhance_prompt` with prompt = "$ARGUMENTS". If the current git branch is not `main`,
   also pass `repo`, `branch`, `base_commit` (`git merge-base HEAD origin/main`) and `changed_files`
   (`git diff --name-only origin/main...HEAD` plus the files in `git status --porcelain`).
2. Show the enhanced prompt briefly, then follow it: check the listed files in the working copy, use the `brain` tools
   (`search`, `symbol`, `trace`, `snippet`, `read`, `grep`, `files`) for anything missing, implement the change, and
   check every acceptance criterion.
