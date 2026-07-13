# ssv - The core of UVM verification environment parameter passing (copyable)

[English](README.md) | [简体中文](README.zh-CN.md)

**Core idea (4 steps)**:

1. Write the parameter source of truth in `.cfg` (e.g. `top.cfg`, `sub_agent.cfg`). `cfg2sv.py` generates `cfg/<class>.sv` (paired with the .cfg in the same directory) as classes `extends ssv_object`, and also generates `cfg/ssv_cfg_pkg.sv` and `cfg/all.cmd`.
2. Compile once: default simv = `sim/output/baseline/simv` (`sexe build`).
3. When running a case, Python reads `cases/<case>.cmd`, extracts the `ssv_cfg:` lines, **expands glob using Python's `fnmatch`**, and writes them as `sim/<variant>/run/<case>/cfg.info`; **changes the simv process's cwd to the case run dir** (same directory as cfg.info).
4. After simv starts, the test's `build_phase` calls `ssv_object::apply_overrides_in_cwd(root_cfg)`, which internally opens the relative path `"cfg.info"` → `dispatch_path` for dispatch. **The SV side does not read cases/*.cmd, does not read plusargs/env, does not do glob — it only consumes cfg.info under the cwd.**

**Directory**:

```
ssv/
├── cfg/                    # .cfg files (source of truth) + auto-generated .sv / ssv_cfg_pkg.sv / all.cmd
│   ├── top.cfg             # root cfg (auto-generated top.sv alongside)
│   ├── sub_agent.cfg       # sub-class cfg (auto-generated sub_agent.sv alongside)
│   ├── lib/                # optional subdir (pulled in via @)
│   │   └── scoreboard.cfg  #   .sv also in the same dir (in ssv_cfg_pkg.sv: `include "lib/scoreboard.sv")
│   ├── ssv_cfg_pkg.sv      # auto-generated — referenced by filelist
│   └── all.cmd             # auto-generated — cfg dump (Python glob expands the candidate set)
├── cases/                  # .cmd files (compile-time + run-time instructions)
├── tools/                  # cfg2sv.py + run_case.py + bin/sexe
├── tb/
│   ├── utiles/ssv/         # copyable minimal core (ssv_object.sv + ssv_pkg.sv)
│   ├── env/                # user sample env/agent
│   ├── tests/              # user sample tests
│   ├── filelist.f          # VCS filelist (references cfg/ssv_cfg_pkg.sv)
│   └── tb_top.sv           # testbench top (clock/reset stubs + run_test())
├── sim/                    # sim artifacts + compile flags
│   ├── build/              # compile flags .cmd (to add a build variant just add a file, no code change)
│   │   ├── baseline.cmd    # vlogan:/vcs:/precomp: lines → sim/output/baseline/simv
│   │   └── kdb.cmd         # → sim/output/kdb/simv
│   └── output/<variant>/   # compile artifacts
│       ├── simv            <- binary
│       ├── build/          <- VCS -Mdir / -Mlib
│       ├── logs/vcs.log    <- compile log
│       └── run/<case>/
│           ├── cfg.info    <- Python extracts ssv_cfg: lines from cases/<case>.cmd + expands glob
│           └── sim.log     <- case simulation log
└── (no gen/ — cfg+sv live in the same dir, so the whole tree is easy to copy to another project)
```

**`.cfg` file syntax**:

Each `.cfg` file defines at most one top-level class. A field uses `::` as the
type/name separator (not `:`, so packed ranges such as `bit [7:0]` remain
unambiguous). Semicolons and commas at the end of a value are optional.

```text
# or // comment; trailing comments are also allowed outside string literals

@./sub_agent.cfg                  # include a standalone cfg class (top level only)

ssv_root_cfg {                    # <class_name> { ... }
  int unsigned :: NUM_AGENTS = 2; # <type> :: <field> [= <SV literal>]
  bit [7:0]    :: MASK       = 'hff;
  string       :: ENV_NAME   = "demo #1";  # # inside quotes is data
  real         :: PERIOD_NS;               # omitted value defaults to 0.0
  int[]        :: COUNTERS   = '{1, 2, 3}; # dynamic array
  string[$]    :: NAMES;                   # queue

  sub_agent_cfg agent_a {          # <class_name> <instance_name> { ... }
    int    :: AGENT_ID = 0;         # overrides fields of the referenced class
    string :: NAME     = "agent_a";
  }
}
```

Grammar summary:

```text
cfg-file       := { include } class-block
include        := "@" path                         # outside class blocks only
class-block    := class-name "{" { field | sub-object } "}"
sub-object     := class-name instance-name "{" { field } "}"
field          := type "::" field-name [ "=" value ] [ ";" | "," ]
```

- Supported scalar types include `int`, `int unsigned`/`uint`, `bit`,
  `logic`, `byte`, `shortint`, `longint`, `real`, `string`, and packed
  `bit [...]` / `logic [...]`. Append `[]` for a dynamic array or `[$]` for
  a queue.
- A missing value defaults to `0` for integer-like types, `1'b0` for
  `bit`/`logic`, `0.0` for `real`, `""` for `string`, and the SystemVerilog
  empty assignment pattern for arrays/queues.
- A file may contain one top-level class. Nested class definitions are not
  allowed; a two-name block is a sub-object instance. The referenced class
  may come from another discovered `.cfg` file or an `@` include.
- A whole class or sub-object may also be written on one line, with fields
  separated by semicolons, for example
  `sub_agent_cfg { int :: ID = 0; bit :: ENABLE = 1'b1; }`.
- `#` and `//` start whole-line or trailing comments outside double-quoted
  strings. String literals preserve those characters.
- `@` accepts an absolute path or a path relative to the current `.cfg`;
  `$VAR` and `${VAR}` are expanded. Includes may be nested, but cycles are
  errors. Included classes remain independent and are not field-merged.

**`.cmd` file syntax**:

```
vlogan:        <args>        # compile-time flags (build only, optional)
vcs:           <args>        # compile-time flags (build only, optional).
                            # A `vcs: -l <file>` line writes the
                            # COMPILE log to <file>; both `<file>` and
                            # the relative-to-simv-dir resolution are
                            # yours. vcs is invoked with cwd = simv's
                            # own dir, so a relative `-l vcs.log` lands
                            # next to the simv binary.
simv:          <arg>         # runtime: append <arg> to the simv command
                            # line (one arg per line). This is the
                            # **only** way to pick a testclass (no
                            # defaulting allowed):
                            #   e.g.: simv: +UVM_TESTNAME=my_long_test
                            # A `simv: -l <file>` line writes the
                            # SIMULATION log to <file> via VCS's native
                            # `-l`; cwd=case run dir, so a relative
                            # `-l simv.log` lands in
                            # sim/<variant>/run/<case>/.
                            #
                            # Two scopes:
                            #   - in cases/<x>.cmd:  case-specific flags
                            #     (testclass, ucli dofile, ...)
                            #   - in sim/build/<v>.cmd:  variant-level
                            #     defaults; read at runtime and appended
                            #     BEFORE the case cmd's `simv:` lines.
                            #     For `-l` specifically, the case cmd's
                            #     line overrides (VCS uses the last one).
binary:        <path>        # runtime: pick which simv binary (path relative to sim/, optional)
ssv_cfg:       <path> = <val>
                            # runtime cfg override: Python reads this and writes it into cfg.info.
                            # Exact path: kept as-is. If the path contains * / ? / [, Python uses
                            # fnmatch to expand it against the candidate set in all.cmd.
break:         <time>        # debug stop point: `start` or 0 stops immediately; otherwise +kdb_stop=<time>
precomp:       <shell cmd>   # pre-compile hook (cwd=proj_root, bash, multiple lines = multiple cmds)
                            # failure → abort, do not proceed to compile
presim:        <shell cmd>   # pre-sim hook (cwd=case run dir, bash, multiple lines = multiple cmds)
                            # failure → abort, do not invoke simv; --build-only skips it
postsim:       <shell cmd>   # post-sim hook (cwd=case run dir, bash, multiple lines = multiple cmds)
                            # failure → log a warning but use simv's rc; --build-only skips it
seed:         <int|random>  # UVM random seed; omit or write "random" → random (1..2^31-1).
                            # When debugging a bug, fix it with seed: 12345 for reproducibility.
                            # Maps to simv plusarg: +UVM_SEED=<int>
inc:          <path>        # include another .cmd; path is relative to project root.
                            # Included lines are inserted at this position; nested includes
                            # are supported and include cycles are errors.
```

General `.cmd` rules:

- The format is line-oriented: `directive: payload`. Leading/trailing
  whitespace is ignored, empty payloads are skipped, and there is no
  continuation-line syntax. Unknown lines are ignored as comments.
- `#` and `//` start whole-line or trailing comments outside double-quoted
  strings. Directives from `inc:` files behave as if written at the include
  location.
- Repeat `vlogan:`, `vcs:`, `simv:`, `ssv_cfg:`, or hook directives to append
  values in order. For `binary:` and `seed:`, the last value wins.
- `simv:` payloads are split on whitespace (there is no shell-style quote
  parser); environment variables are expanded before launch. Hook payloads
  are instead executed verbatim by `/bin/bash`.
- `ssv_cfg:` uses the first `=` as the path/value separator. The optional
  `ssv_root_cfg.` prefix is removed. An exact path is emitted directly;
  `*`, `?`, and `[...]` patterns are expanded case-sensitively against
  `cfg/all.cmd`. Numeric array indices such as `[0]` are not treated as glob
  syntax. An unmatched glob is retained so the SV side reports an unknown
  field warning.

**Glob syntax** (in the path of a `ssv_cfg:` line, expanded by Python `fnmatch`):

```
ssv_cfg: agent_*.NAME        = "x"     # agent_a.NAME / agent_b.NAME
ssv_cfg: *.ADDR_WIDTH        = 64      # everything ending in .ADDR_WIDTH
ssv_cfg: agent_?.AD?R_WIDT?  = ...     # ? matches a single character
```

**`@` include syntax** (in `.cfg` files, cpp-style independent cfg loading):

```
@<path>            # Load the .cfg at the given path; its top-level class is registered globally.
                   # The current cfg does NOT auto-merge fields from the included file (independent cfg semantics).
                   # @ can only appear OUTSIDE top-level class blocks.
                   # Nested @ is also allowed; cyclic includes error out.
                   # Classes from included files can be instantiated normally via "class_name inst_name { ... }".

Path resolution:
    - Leading / → absolute path
    - Otherwise → relative to the current .cfg file's directory
    - ${VAR} and $VAR env var expansion is supported (via os.path.expandvars);
      if a '$' remains after expansion, the env var is undefined → error.

Example:
    # cfg/shared/sub_agent.cfg
    sub_agent_cfg { int :: AGENT_ID = 0; bit :: IS_ACTIVE = 1'b1; ... }

    # cfg/top.cfg
    @./shared/sub_agent.cfg                # registers the sub_agent_cfg class

    ssv_root_cfg {
      ...
      sub_agent_cfg agent_a { int :: AGENT_ID = 7; }   # normal instantiation
    }
```

**Dynamic arrays / queues** (declared in `.cfg` with `int[]` / `int[$]`):

```
# Dynamic array: in .cmd use FIELD.size to change length, FIELD[N] to write the Nth element
ssv_cfg: MY_DYN_ARR.size = 4    # change length to 4 (old elements dropped)
ssv_cfg: MY_DYN_ARR[0]   = 10   # write element 0; auto-grows if too short
ssv_cfg: MY_DYN_ARR[3]   = 40   # write element 3

# Queue: each `=` line in .cmd does one push_back (appended to .cfg default values)
ssv_cfg: MY_QUEUE        = 100  # push_back(100)
ssv_cfg: MY_QUEUE        = 200  # push_back(200)

# string dynamic arrays / queues work the same way
ssv_cfg: NAMES.size      = 2
ssv_cfg: NAMES[0]        = "alice"
ssv_cfg: NAMES_Q         = "carol"
```

See `cases/arrays_demo.cmd` + the 5 demo fields in `cfg/top.cfg` for details.

**Simplest 4-step usage** (run `sexe` from the project root; it works from any directory — `sexe` uses `__file__` to locate the project root internally):

```bash
sexe build                                       # build sim/output/baseline/simv (precomp runs cfg2sv.py to generate cfg/*.sv + cfg/all.cmd)
sexe run --case smoke                            # run smoke (default: baseline binary)
sexe run --case smoke --variant kdb              # run smoke with the kdb binary (auto-runs `sexe build --variant kdb` on first use)
sexe regress --cases smoke override_demo glob_demo hooks_demo
sexe list-builds                                 # show all build variants available under sim/build/
sexe --help                                      # all sub-commands + descriptions
```

**After editing cfg/**: run `sexe build` to regenerate + recompile simv. `precomp: python3 tools/cfg2sv.py` is embedded in the build cmd, so every build re-compiles `cfg/*.cfg` into `cfg/*.sv` (paired, same directory) and `cfg/all.cmd` — no need to run cfg2sv.py manually.

**Adding a new build variant** (no Python changes): drop a `.cmd` under `sim/build/` (with `vlogan:` / `vcs:` / `precomp:` etc. lines); the filename is the variant name. Then run `sexe build --variant <new_name>`. Both baseline.cmd and kdb.cmd already include `precomp: python3 tools/cfg2sv.py`, so reuse them as a template.

**Hook usage example** (`cases/hooks_demo.cmd`):

```bash
precomp: echo "[precomp] regen some code" && python3 tools/regen.py
presim:  echo "[presim] setup marker" > presim_marker.txt
postsim: cat presim_marker.txt && rm presim_marker.txt
postsim: echo "[postsim] fatal=$(grep -c UVM_FATAL sim.log)"
```

---

**Copyable to other projects**:

```bash
# 1. Copy the core
cp -r <ssv>/tb/utiles/ssv/  <new>/tb/utiles/ssv/

# 2. Copy the scripts
cp <ssv>/tools/{cfg2sv,run_case}.py  <new>/tools/

# 3. Add to your filelist:
#      +incdir+tb/utiles/ssv
#      tb/utiles/ssv/ssv_pkg.sv
#      +incdir+cfg
#      cfg/ssv_cfg_pkg.sv

# 4. Copy a build cmd (with precomp: python3 tools/cfg2sv.py):
cp <ssv>/sim/build/baseline.cmd  <new>/sim/build/baseline.cmd

# 5. Run:
sexe build                 # precomp runs cfg2sv.py to generate cfg/<name>.sv, then compiles simv
sexe run --case <yourcase> # run any case, reusing the same simv

# Note: cfg/*.cfg and the generated cfg/*.sv are paired (cfg+sv together); copy the whole tree.
# Subdirectories pulled in via @ (e.g. cfg/lib/) are also paired.
```

---

**Known constraints / notes**:

- EDA toolchain: `VCS_HOME=/workspace/eda/synopsys/vcs/W-2024.09`, `UVM_HOME=$VCS_HOME/etc/uvm-1.2`, `LM_LICENSE_FILE=/workspace/eda/synopsys/scl2025.03-sp2/Synopsys.lic`
- VCS W-2024 + UVM 1.2 runtime scheduler hangs at `uvm.uvm_sched.pre_reset` without `-kdb`, so both baseline.cmd / kdb.cmd include `-kdb`
- The simv process's cwd is set to the case run dir by run_case.py; VCS uses argv[0] (absolute path) to find simv.daidir, so cwd does not affect daidir lookup
- `vcs` is invoked with cwd = `sim/<variant>/` (not proj_root) so the variant cmd's `vcs: -l vcs.log` lands next to the simv binary. All paths in `tb/filelist.f` use `$PROJ_ROOT` to be cwd-agnostic.
- SV `substr(start, end)` is inclusive on both indices; to compare a prefix you must use `substr(0, prefix.len()-1)`
- Numeric field overrides: decimal numbers / `0` / `1` / `1'b0` / `1'b1`; other literals are written as cfg defaults
- Packed vector array/scalar assignment goes through `ssv_ato_packed` (`tools/cfg2sv.py` + `ssv_object.sv`), not relying on UVM `*_hext` macros (UVM 1.2 has no such macros)
- Interface & virtual interface: placeholders are in `tb/tb_top.sv`, replace them yourself
- **Entry point is `sexe` (in `tools/bin/sexe`)** — after `source sourceme` you can run it from any directory, no Makefile required
- **Do NOT add `-debug_access+all`** — VCS W-2024's cbug stack annotator calls `cbug-gdb-64/bin/gdb`; in our environment gdb returns status=127 and stalls simv. `-kdb` alone is enough to prevent UVM 1.2's pre_reset hang, and also supports `+kdb_stop=<time>` debug breakpoints.
