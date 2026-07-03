# cfg / cmd syntax robustness audit (s-exe)

Scope: `cfg2sv.py` (.cfg → .sv generator/parser) and `run_case.py` (.cmd dispatcher/parser).
Test harness: `/tmp/cfg_robust/` (importer-based, no VCS build needed).
Coverage: 53 .cfg cases + 37 .cmd cases.

## TL;DR

| surface      | pass | real bugs | false-positive warnings | latent issues |
|--------------|-----:|----------:|------------------------:|--------------:|
| .cfg parser  | 48/53 | 4         | 1                       | 2             |
| .cmd parser  | 37/37 | 3         | 1                       | 1             |

Most bugs are **silent value corruption** — the parser accepts the input but
generates wrong / invalid output. The four .cfg bugs are concentrated in two
spots: dead helper `_strip_inline_comment` (cfg2sv.py:141) and block-detection
logic (cfg2sv.py:281). Fixing these is mechanical.

---

## Real bugs — `.cfg` side (cfg2sv.py)

### BUG 1 [HIGH] Inline `#` / `//` comments silently corrupt the value

- **File:** `tools/cfg2sv.py`
- **Symptom:** `int :: A = 5; # trailing comment` is accepted; the value
  stored is `'5 ; # trailing comment'` (the `# comment` is glued onto the
  value). Generated SV becomes `rand int A = 5 ; # trailing comment;` —
  `#` is NOT a SV comment, so VCS errors out at compile.
- **Root cause:** `_strip_inline_comment()` is defined at
  `tools/cfg2sv.py:141` but **never called**. Whole-line comment check is
  only `stripped.startswith('#')`. Inline `#` / `//` are tokenized into the
  value side.
- **Repro:**
  ```bash
  cd /tmp/cfg_robust/proj
  cat cfg/top.cfg
  #   foo_cfg {
  #     int :: A = 5; # trailing
  #     real :: B = 3.14; # also trailing
  #   }
  python3 tools/cfg2sv.py   # (s-exe project root)
  cat cfg/top.sv   # → rand int A = 5 ; # trailing;  (invalid SV)
  ```
- **Fix sketch:** call `_strip_inline_comment(raw)` at the top of the
  per-line block in `parse_cfg` BEFORE tokenizing; or strip everything from
  the first unquoted `#` / `//` onward. ~10 lines.

### BUG 2 [HIGH] One-line class/sub-object block → `IndexError`

- **File:** `tools/cfg2sv.py` block-detection logic
- **Symptom:** Writing `foo_cfg { int :: X = 5; }` on a single line raises
  `IndexError: list index out of range` instead of a friendly SyntaxError.
  Same for `sub_agent_cfg agent_a { int :: AGENT_ID = 7; }`.
- **Root cause:** the block-start detector at the `# Start of a class /
  sub-object block` section uses
  `('{' in line_tokens and not any(t == '::' for t in line_tokens[:-1]))`,
  which wrongly filters out blocks whose body contains `::`. Real project's
  `.cfg` files all use multi-line blocks, so the bug is **latent**.
- **Fix sketch:** when `{` is present and `}` is also present on the same
  line, treat it as a block start regardless of `::` presence; then feed
  the contents between `{` and `}` back through the parser as a sub-parse.
  Or require block starts on their own line.
- **Workaround:** always put the opening `{` on its own line.

### BUG 3 [MEDIUM] Field outside any class block → `IndexError`

- **File:** `tools/cfg2sv.py:447`
- **Symptom:** a `.cfg` starting with `int :: A = 1;` (no class block) raises
  `IndexError: list index out of range` instead of `SyntaxError: ... field
  declaration outside any class block`.
- **Root cause:** `top_kind, top_obj = stack[-1]` on an empty `stack`.
- **Fix sketch:** `if not stack: raise SyntaxError(f"{src_path}:{line_idx}: field
  declaration outside any class block")`.

### BUG 4 [LOW] UTF-8 BOM at file start → `IndexError`

- **File:** `tools/cfg2sv.py` `_cfg_line_iter` (line ~165)
- **Symptom:** saving a `.cfg` as UTF-8-with-BOM (Excel default, some Windows
  editors) causes `IndexError` because the `\ufeff` BOM gets prefixed to the
  first token.
- **Fix sketch:** `text = path.read_text(encoding='utf-8-sig')` (handles BOM
  automatically) or strip BOM once at the top of `_cfg_line_iter`.

---

## Real bugs — `.cmd` side (run_case.py)

### BUG 5 [MEDIUM] Inline `#` / `//` in `ssv_cfg:` value → propagates to cfg.info → wrong runtime value

- **File:** `tools/run_case.py` `build_cfg_info` (`body = s[len("ssv_cfg:"):].strip()`)
- **Symptom:**
  ```bash
  ssv_cfg: ENV_NAME = "hello" # comment
  ```
  ends up in `cfg.info` verbatim. At runtime the SV side's
  `ssv_unquote("\"hello\" # comment")` doesn't see a closing `"`, so it
  returns the string as-is and `ENV_NAME` becomes the literal text
  `"hello" # comment` (with the quote characters inside it!).
- **Root cause:** `read_cmd_with_includes` strips whole-line `#` / `//`
  only. Inline comments in values are not detected. The generated `cfg.info`
  faithfully preserves them, and the SV-side parser (`ssv_object.sv`) does
  the same.
- **Fix sketch:** strip everything from the first unquoted `#` / `//` onward
  in `build_cfg_info`'s value-extraction step. Same fix on the SV side
  (`apply_overrides_from_file` should strip inline comments from `val`).

### BUG 6 [LOW] `simv:` line with no arg silently produces empty cmdline arg

- **File:** `tools/run_case.py` `collect_prefixed`
- **Symptom:** A `.cmd` containing
  ```
  simv:
  simv: +UVM_TESTNAME=t
  ```
  produces `simv_arg_list = ['', '+UVM_TESTNAME=t']`. The empty string is
  appended to the simv command line as `argv[1]`. VCS may treat it as an
  empty filename or warning, but it's never the user's intent.
- **Fix sketch:** `if s: out.append(...)` in `collect_prefixed` to skip
  empty payloads.

### BUG 7 [LOW] Glob false-positive warning for array-index paths

- **File:** `tools/run_case.py` `_has_glob`
- **Symptom:** `ssv_cfg: MY_DYN_ARR[0] = 5` triggers
  `[run_case] warn: glob 'MY_DYN_ARR[0]' ... matched 0 candidates` —
  confusing because the user wrote an array-index assignment, not a glob.
- **Root cause:** `_has_glob(s)` returns True if `[` is in `s`. There's no
  way to distinguish glob char-set `agent_[ab]` from array index `ARR[0]`.
- **Fix sketch:** regex `re.fullmatch(r'.+\[\d+\]', s)` → not a glob; or
  document that array-index paths may emit a benign warning.

---

## Latent issues (not bugs, but worth noting)

| where | what |
|-------|------|
| `.cfg` parser | No line continuation (`\` does NOT join lines) |
| `.cfg` `@` include | Absolute paths break if you `cp -r` cfg/ to another project |
| `.cmd` `inc:` | No depth limit — only cycle detection prevents infinite recursion (cross-file cycle detection does work, confirmed) |
| `.cmd` parser | Unknown directives (`foo: bar`) silently treated as comments — fine, but the user might want a warning |
| `.cfg` `//` comment | `#` is recognized as whole-line; `//` is also recognized; both are NOT recognized inline (same as Bug 1) |
| `break:` parser | `break: 100ns` → `+kdb_stop=100ns` works; `break: 100` → `+kdb_stop=100` works; `break: start` and `break: 0` both map to `+kdb_stop=0` |

---

## Things that work correctly (good)

- `::` separator: with/without whitespace, asymmetric (`int::A`, `int :: A`, `int  ::  A`, `int:: A`, `int ::A`) — all parse the same.
- Single `:` inside `bit [7:0]` / `bit [31:16]` does NOT collide with `::`.
- `@` include: relative, absolute, env var `${HOME}` all work; missing-file
  and undefined-env errors are friendly with file/line info.
- `inc:` include: same — relative to `proj_root`, circular detection (self and cross-file), missing-file friendly errors.
- `seed:` last-wins; `seed: random` → random in [1, 2^31-1]; invalid `seed:` → fallback with warning.
- `break:` `start` / `0` / `100ns` all map correctly.
- `binary:` absolute and relative both resolve.
- `ssv_cfg:` path with `ssv_root_cfg.` prefix gets stripped to root-relative.
- `ssv_cfg:` value with `=` (`FOO = "a=b"`) splits on the FIRST `=` only.
- `ssv_cfg:` value with `#` INSIDE a quoted string is preserved verbatim.
- Glob: `*`, `?`, `[ab]` all expand via fnmatch; unmatched globs emit a
  warning but keep the original line (so SV can still surface a uvm_warning
  for unknown fields).
- `ssv_cfg:` scalar duplicates are last-wins; `ssv_cfg:` queue lines all
  push_back (accumulate).
- Empty file, whitespace-only file, missing `}` all raise friendly SyntaxError.

---

## Suggested fix order

1. **BUG 1** (cfg inline comments) — highest ROI; 10-line fix; covers many
   `.cmd` cases too if applied symmetrically.
2. **BUG 5** (cmd inline comments in values) — symmetric fix; same pattern.
3. **BUG 2** (one-line block) — decide policy: support one-line OR forbid it
   with a clear SyntaxError.
4. **BUG 3, 4** (IndexError UX) — trivial.
5. **BUG 6, 7** (simv-empty, glob false-positive) — cosmetic.
