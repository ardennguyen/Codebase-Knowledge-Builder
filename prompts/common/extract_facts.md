You are extracting verifiable facts from ONE source file of the project "{project_name}".

File: {file_path}

Every fact quotes the source. Copy lines EXACTLY as they appear in the file: same identifiers, same order. Code checks each quote against the file and discards any fact whose quote is not there, so never reformat, paraphrase, shorten with "...", or merge lines that are not consecutive.

Report four lists:

1. symbols: every declaration a reader of an API reference looks up: classes, interfaces, structs, enums, traits, type aliases, functions, methods, and module-level constants or exported variables. Skip local variables and parameters
   - name: the identifier exactly as declared
   - kind: class | interface | struct | enum | trait | type | function | method | constant | variable | macro | module
   - parent: the enclosing class, struct, impl, module or namespace symbol for members; empty for top-level declarations
   - visibility: public | internal | private, by the language's own rules (export, pub, public, capitalization, leading underscore, ...)
   - signature: the declaration line, exactly as in the file (a declaration split over several lines: at most its first 3 lines)
2. dependencies: every import, include, require, use or re-export of another file, module, package or namespace, including imports inside functions and conditional imports; plus every use of a name that comes from another file of this project without an import (same package or namespace)
   - target: the module, file, package or namespace path exactly as written in the source, without the list of imported names (for example `utils.output`, `./client`, `net/socket.h`, `com.acme.billing.Invoice`; `crate::store` for `use crate::store::{{Repo, Error}};`; `.util` for `from . import util`); for a same-package name used without an import, the name itself
   - evidence: the import line (for an import split over several lines, the line that names the module); for a name used without an import, one line that uses it
3. config: environment variables, command-line flags and configuration keys the file reads
   - name, kind (env | cli | config), evidence: a line that contains the name (for a key held in a constant, the line that defines the constant)
4. errors: error or exception types and error codes the file raises, throws or returns
   - name, evidence: a line that contains the name

Rules:
- Facts about THIS file only. Never guess what other files contain
- Parameters, local variables and attributes are never dependencies, even when they are named like a module
- Leave a list empty ([]) when there is nothing to report
- Write every signature and evidence as a `|-` block scalar, so quotes, colons and `#` need no escaping
{focus_note}
Return ONLY valid YAML:

```yaml
symbols:
  - name: Parser
    kind: class
    parent: ""
    visibility: public
    signature: |-
      class Parser(BaseParser):
  - name: parse
    kind: method
    parent: Parser
    visibility: public
    signature: |-
      def parse(self, text: str) -> Node:
dependencies:
  - target: lexer.tokens
    evidence: |-
      from lexer.tokens import Token, TokenKind
config:
  - name: PARSER_STRICT
    kind: env
    evidence: |-
      strict = os.environ.get("PARSER_STRICT") == "1"
errors:
  - name: ParseError
    evidence: |-
      raise ParseError(f"unexpected token {{token}}")
```

═══════════════════════════════════════════════════════
SOURCE OF {file_path} — START
═══════════════════════════════════════════════════════
{source}
═══════════════════════════════════════════════════════
SOURCE OF {file_path} — END
═══════════════════════════════════════════════════════

Now, provide the YAML output:
