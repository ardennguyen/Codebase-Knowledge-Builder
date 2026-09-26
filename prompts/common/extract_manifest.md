You are reading ONE manifest or configuration file of the project "{project_name}" to learn which names its code is imported by.

File: {file_path}

Code elsewhere in the project may import this project's own code by a declared name instead of a file path: a workspace or package name (`@acme/api`), a module path (`example.com/shop`), a crate or distribution name (`shop-core`, `acme-billing`), or a path alias (`@lib/*` for `src/lib/*`). Report what this file declares. Code checks every quote against the file and discards what is not there, so copy lines EXACTLY.

Report two lists:

1. provides: every name under which this file makes the code of its own folder importable (the package, module, crate or workspace-member name it declares; not its dependencies on other packages)
   - name: the name exactly as written
   - entry: the entry file this file declares for that name, exactly as written (for example `src/index.ts`, `src/lib.rs`); leave it out when the file declares none
   - evidence: the line that contains the name
2. aliases: every import path alias this file defines for the project's own code (for example `paths`, `alias`, `baseUrl` settings)
   - alias: the alias exactly as written (for example `@lib/*`)
   - target: the path it maps to, exactly as written (for example `src/lib/*`)
   - base: the base directory the target is relative to, exactly as written, when the file sets one (for example tsconfig `baseUrl`); leave it out otherwise
   - evidence: the line that contains both the alias and the target

Rules:
- Only what THIS file declares. Leave a list empty ([]) when there is nothing to report
- Dependencies on other packages, scripts, versions and tool settings are not reported
- Write every evidence as a `|-` block scalar

Return ONLY valid YAML:

```yaml
provides:
  - name: "@acme/api"
    entry: src/index.ts
    evidence: |-
        "name": "@acme/api",
aliases:
  - alias: "@lib/*"
    target: src/lib/*
    base: .
    evidence: |-
          "@lib/*": ["src/lib/*"],
```

═══════════════════════════════════════════════════════
SOURCE OF {file_path} — START
═══════════════════════════════════════════════════════
{source}
═══════════════════════════════════════════════════════
SOURCE OF {file_path} — END
═══════════════════════════════════════════════════════

Now, provide the YAML output:
