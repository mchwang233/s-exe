#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_case.py - ssv regression script: compile once, reuse N times.

Core ideas:
  1. Compilation is expensive; regressions are high-frequency. simv is built
     once and reused across all cases.
  2. One directory per simv variant (e.g. baseline / kdb):
        sim/<variant>/
          simv           <-- binary
          build/         <-- VCS -Mdir / -Mlib
          logs/vcs.log   <-- build log
          run/<case>/
            cfg.info     <-- case runtime cfg overrides (Python-flattened)
            sim.log      <-- case simulation log
  3. cfg.info: in the case run dir, Python extracts the ssv_cfg: lines from
     cases/<case>.cmd (with all inc:'d files), expands globs in Python via
     fnmatch, and writes cfg.info.
  4. The simv process is launched with cwd = case run dir (the same dir as
     cfg.info). The test's build_phase calls
     ssv_object::apply_overrides_in_cwd(root), which opens the relative path
     "cfg.info".
  5. The SV side does NOT read cases/*.cmd, plusargs, or env vars, and does
     NOT do glob expansion -- Python does all of that.

.cmd file prefixes:
  vlogan:        <args>           build-time args (build only)
  vcs:           <args>           build-time args (build only; runtime
                                 plusargs starting with '+' are also passed
                                 through to simv for backward compat)
  binary:        <path>           runtime: pick which simv binary
                                 (path is resolved relative to sim/ then
                                 project root)
  simv:          <arg>           runtime: append <arg> to the simv command
                                 line (one per line). This is the ONLY way
                                 to select a testclass (no default):
                                 e.g. simv: +UVM_TESTNAME=my_long_test
  ssv_cfg:       <path> = <val>   cfg override: Python extracts this and
                                 writes it into cfg.info. If <path> contains
                                 *, ?, or [, Python expands the glob via
                                 fnmatch against the candidate set from
                                 cfg/all.cmd.
  break:         <time>          debug breakpoint: 'start' or '0' -> stop
                                 immediately; otherwise +kdb_stop=<time>.
  precomp:       <shell cmd>     pre-build hook (cwd=proj_root, bash exec,
                                 multiple lines = multiple cmds). Failure
                                 -> abort, do not enter build.
  presim:        <shell cmd>     pre-simulation hook (cwd=case run dir, bash
                                 exec). Failure -> abort, do not enter
                                 simv. Skipped under --build-only.
  postsim:       <shell cmd>     post-simulation hook (cwd=case run dir,
                                 bash exec). Failure -> log warning but
                                 keep simv's returncode. Skipped under
                                 --build-only.
  seed:         <int|random>     UVM random seed. Absent or "random" -> a
                                 random seed in [1, 2^31-1]. Pin a literal
                                 seed (seed: 12345) to reproduce a bug.
                                 Becomes +UVM_SEED=<int> on the simv line.
  inc:           <path>          include another .cmd file (resolved
                                 relative to proj_root). Multiple inc:
                                 directives may be chained; circular inc:
                                 raises.
  <other>                          treated as a comment line.

Usage:
  python3 tools/run_case.py cases/_baseline.cmd --build-only
  python3 tools/run_case.py cases/smoke.cmd

Optional env vars:
  PROJ_ROOT              project root (default: cwd)
  VCS_HOME               VCS install path
  UVM_HOME               UVM src (default: $VCS_HOME/etc/uvm-1.2)
  LM_LICENSE_FILE        license path
  SSV_ROOT_NAME          root cfg class name (default: ssv_root_cfg)
"""
import argparse
import dataclasses
import fnmatch
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List


# ----------------------------- .cmd file reader (recursive inc:) -----------------------------

@dataclasses.dataclass
class CmdLine:
    """One line of a .cmd file, with source location info so error
    messages can point to the right file + line."""
    text: str       # the line text (newline stripped)
    src_path: Path  # the .cmd file this line came from
    src_line: int   # 1-indexed line number in src_path (0 for inc: markers)

def read_cmd_with_includes(cmd_path: Path, proj_root: Path, _seen: set = None) -> List[CmdLine]:
    """Read a .cmd file and recursively follow inc: directives.

    inc: <path> paths are resolved relative to proj_root.
    The included file's lines are spliced in at the inc: location, with
    src_path / src_line set accordingly.
    Circular inc: raises RuntimeError.

    Returns a flat list of CmdLine. Each inc: directive itself becomes a
    pair of marker lines ('# >>> inc:' / '# <<< end inc:') wrapping the
    spliced content; all other directive lines are kept as-is (stripped).
    """
    if _seen is None:
        _seen = set()
    abs_p = cmd_path.resolve()
    if abs_p in _seen:
        raise RuntimeError(f"circular inc: detected at {cmd_path}")
    _seen.add(abs_p)

    out: List[CmdLine] = []
    for line_no, raw in enumerate(cmd_path.read_text(encoding='utf-8').splitlines(), 1):
        s = raw.strip()
        if s.startswith("inc:"):
            inc_path_str = s[len("inc:"):].strip()
            if not inc_path_str:
                raise ValueError(f"{cmd_path}:{line_no}: inc: path is empty")
            inc_path = (proj_root / inc_path_str).resolve()
            if not inc_path.exists():
                raise FileNotFoundError(
                    f"{cmd_path}:{line_no}: inc: file not found: {inc_path}")
            out.append(CmdLine(
                f"# >>> inc: {inc_path_str}  (from {cmd_path.name}:{line_no})",
                cmd_path, line_no))
            out.extend(read_cmd_with_includes(inc_path, proj_root, _seen))
            out.append(CmdLine(
                f"# <<< end inc: {inc_path_str}",
                inc_path, 0))
        else:
            out.append(CmdLine(raw, cmd_path, line_no))
    return out

def collect_prefixed(lines: List[CmdLine], prefix: str) -> List[str]:
    """Collect every line in `lines` that starts with `prefix` and return
    the (prefix-stripped, whitespace-stripped) payload.

    Every line must start at column 0 with the prefix (no indentation-based
    continuation -- the parser stays simple and .cmd stays readable).
    The function is agnostic to whether a line came from the main .cmd or
    from an inc:'d .cmd.
    """
    out: List[str] = []
    for cl in lines:
        s = cl.text.strip()
        if s.startswith(prefix):
            out.append(s[len(prefix):].strip())
    return out


# ----------------------------- Hook execution -----------------------------

def run_hook(cmd: str, cwd: Path, label: str) -> int:
    """Run a single shell hook (precomp: / presim: / postsim:) with `cwd`
    as the working directory. Returns the subprocess returncode."""
    print(f"[run_case] {label}: (cwd={cwd}) {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), executable="/bin/bash")
    if r.returncode != 0:
        print(f"[run_case] {label} FAILED rc={r.returncode}", file=sys.stderr)
    return r.returncode


def run_hooks(commands: List[str], cwd: Path, label: str, abort_on_fail: bool) -> int:
    """Run multiple hooks in order. If any returns non-zero and
    abort_on_fail is True, return that rc immediately so the caller can
    exit."""
    for c in commands:
        rc = run_hook(c, cwd, label)
        if rc != 0 and abort_on_fail:
            return rc
    return 0


# ----------------------------- cfg.info generation -----------------------------

def _load_all_cmd_paths(all_cmd_path: Path, root_name: str) -> List[str]:
    """Read cfg/all.cmd and extract every known cfg path (with the
    <root_name>. prefix stripped) as the candidate set for glob expansion.

    Example: all_cmd_path = ~/prj/ssv/cfg/all.cmd, root_name = "ssv_root_cfg"
        -> ["NUM_AGENTS", "ENV_NAME", ..., "agent_a.AGENT_ID", ...]"""
    candidates: List[str] = []
    if not all_cmd_path.exists():
        return candidates
    prefix_with_dot = root_name + "."
    for raw in all_cmd_path.read_text(encoding='utf-8').splitlines():
        s = raw.strip()
        if not s.startswith("ssv_cfg:"):
            continue
        body = s[len("ssv_cfg:"):].strip()
        eq = body.find("=")
        if eq < 0:
            continue
        path = body[:eq].strip()
        if path.startswith(prefix_with_dot):
            path = path[len(prefix_with_dot):]
        if path:
            candidates.append(path)
    return candidates


def _has_glob(s: str) -> bool:
    return any(c in s for c in "*?[")


def _strip_root_prefix(path: str, root_name: str) -> str:
    p = root_name + "."
    if path.startswith(p):
        return path[len(p):]
    return path


def build_cfg_info(sources: List[CmdLine], all_cmd: Path, root_name: str,
                   case_cmd_name: str,
                   out_path: Path, dry_run: bool = False) -> int:
    """Extract ssv_cfg: lines from `sources` (the main .cmd + every
    inc:'d file), expand globs via fnmatch against the candidate set in
    all_cmd, and write <PWD>/cfg.info.

    Returns the number of lines in cfg.info (including the comment header)."""
    candidates = _load_all_cmd_paths(all_cmd, root_name)

    out_lines: List[str] = []
    out_lines.append(f"# Auto-generated by run_case.py from {case_cmd_name} (+inc:)")
    out_lines.append(f"# root_name = {root_name}; {len(candidates)} candidate paths from all.cmd")
    out_lines.append("# Do not edit by hand.")
    out_lines.append("")

    n_glob = 0
    n_exact = 0
    for cl in sources:
        s = cl.text.strip()
        if not s.startswith("ssv_cfg:"):
            continue
        body = s[len("ssv_cfg:"):].strip()
        eq = body.find("=")
        if eq < 0:
            continue
        path = body[:eq].strip()
        val  = body[eq+1:].strip()
        if not path:
            continue

        # Strip the root-name prefix (cfg.info paths are always root-relative
        # internally).
        path_stripped = _strip_root_prefix(path, root_name)

        if _has_glob(path_stripped):
            n_glob += 1
            matched = 0
            for c in candidates:
                if fnmatch.fnmatchcase(c, path_stripped):
                    out_lines.append(f"ssv_cfg: {c} = {val}")
                    matched += 1
            if matched == 0:
                # No match: keep the original line as a warning entry so
                # the SV side will surface a uvm_warning for unknown field.
                out_lines.append(f"ssv_cfg: {path_stripped} = {val}")
                print(f"[run_case] warn: glob '{path_stripped}' "
                      f"(from {cl.src_path.name}:{cl.src_line}) matched 0 candidates",
                      file=sys.stderr)
        else:
            n_exact += 1
            out_lines.append(f"ssv_cfg: {path_stripped} = {val}")

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(out_lines) + "\n", encoding='utf-8')
    print(f"[run_case] cfg.info: {len(out_lines)} lines "
          f"({n_exact} exact + {n_glob} glob-resolved) -> {out_path}")
    return len(out_lines)


# ----------------------------- simv path resolution -----------------------------

def resolve_simv_arg(simv_arg: str, proj_root: Path) -> Path:
    """Resolve the path given in a 'binary:' line.

    Absolute path: return as-is (or <path>/simv if it's an existing dir).
    Relative path: try <proj_root>/sim/<simv_arg> first; if that's a file,
    use it directly, otherwise treat it as a variant directory and append
    /simv."""
    p = Path(simv_arg)
    if p.is_absolute():
        return (p / "simv") if p.is_dir() else p
    # Try sim/-relative first.
    cand = (proj_root / "sim" / simv_arg).resolve()
    if cand.is_file():
        return cand
    if cand.is_dir() and (cand / "simv").is_file():
        return (cand / "simv").resolve()
    return (cand / "simv") if cand.suffix == "" else cand


def setup_sim_env() -> dict:
    env = os.environ.copy()
    env.setdefault("VCS_HOME", "/workspace/eda/synopsys/vcs/W-2024.09")
    env.setdefault("UVM_HOME", f"{env['VCS_HOME']}/etc/uvm-1.2")
    env.setdefault("LM_LICENSE_FILE",
                   "/workspace/eda/synopsys/scl2025.03-sp2/Synopsys.lic")
    env["PATH"] = f"{env['VCS_HOME']}/bin:{env.get('PATH','')}"
    return env


# ----------------------------- Build -----------------------------

def build_simv(simv_path: Path, vlogan_args, vcs_args, proj_root: Path, dry_run=False) -> int:
    """Build simv into simv_path, creating the surrounding directories:
        simv_path.parent          = sim/<variant>/        (created)
        simv_path.parent/build/   = VCS -Mdir / -Mlib
        simv_path.parent/logs/    = build log directory
    """
    sim_env = setup_sim_env()
    vcs = Path(sim_env["VCS_HOME"]) / "bin" / "vcs"

    simv_dir = simv_path.parent           # e.g. sim/output/baseline/
    simv_dir.mkdir(parents=True, exist_ok=True)
    build_dir = simv_dir / "build"
    logs_dir  = simv_dir / "logs"
    build_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    cmd_log = logs_dir / "vcs.log"

    # PROJ_ROOT is consumed by .cmd files via $PROJ_ROOT; the root Makefile
    # (or this script's invoker) is expected to export it.
    sim_env.setdefault("PROJ_ROOT", str(proj_root))

    # The Python side only provides output paths (-Mdir / -Mlib / -o / -l).
    # All other compile args (flags, filelist, +incdir, uvm_dpi.cc) live in
    # the build/<variant>.cmd under vlogan: / vcs: lines.
    output_args = [
        f"-Mdir={build_dir}", f"-Mlib={build_dir}",
        "-o", str(simv_path),
        "-l", str(cmd_log),
    ]

    # Split the .cmd-sourced vcs: / vlogan: lines by whitespace and expand
    # env vars ($UVM_HOME / $PROJ_ROOT etc.). We do NOT rely on VCS
    # implicit tokenization (which previously worked only by accident).
    def _flat_args(raw_lines: List[str]) -> List[str]:
        out: List[str] = []
        for line in raw_lines:
            for tok in line.split():
                out.append(os.path.expandvars(tok))
        return out
    vcs_flat    = _flat_args(vcs_args)
    vlogan_flat = _flat_args(vlogan_args)

    cmd = [str(vcs)] + output_args + vlogan_flat + vcs_flat
    print(f"[run_case] build: {' '.join(cmd[:8])} ... (+{len(cmd)-8} args)")
    if dry_run:
        print("  full:", " ".join(cmd))
        return 0
    with open(cmd_log, "w") as flog:
        r = subprocess.run(cmd, env=sim_env, cwd=str(proj_root),
                           stdout=flog, stderr=subprocess.STDOUT)
    return r.returncode


# ----------------------------- Main entry -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", help="cases/<name>.cmd")
    ap.add_argument("--baseline", default="sim/output/baseline/simv",
                    help="Default simv path (sim/output/baseline/simv).")
    ap.add_argument("--out", default=None,
                    help="Override --baseline (build the simv to this path).")
    ap.add_argument("--case-name", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true",
                    help="Do not compile when simv is missing; just exit.")
    ap.add_argument("--force-build", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--clean-simv", action="store_true")
    args = ap.parse_args()

    # proj_root resolution: prefer $PROJ_ROOT, then this script's location,
    # then cwd. This way run_case.py can be invoked from any directory
    # (e.g. from inside sim/Makefile without an explicit cd) and still
    # find the project root.
    if "PROJ_ROOT" in os.environ:
        proj_root = Path(os.environ["PROJ_ROOT"]).resolve()
    else:
        script_proj = Path(__file__).resolve().parent.parent  # parent of tools/
        if (script_proj / "cases").is_dir() and (script_proj / "tools").is_dir():
            proj_root = script_proj
        else:
            proj_root = Path.cwd()
    os.chdir(proj_root)

    cmd_path = Path(args.cmd).resolve()
    if not cmd_path.exists():
        print(f"[run_case] case file not found: {cmd_path}", file=sys.stderr)
        sys.exit(1)
    # case_name defaults to the path relative to cases/ (preserving
    # sub-directory structure) so that cases in different sub-dirs do not
    # collide on run dir names.
    # e.g. cases/sub/foo.cmd  -> case_name="sub/foo" -> sim/<v>/run/sub/foo/
    # e.g. cases/smoke.cmd    -> case_name="smoke"   -> sim/<v>/run/smoke/
    if args.case_name:
        case_name = args.case_name
    else:
        try:
            case_name = str(cmd_path.relative_to(proj_root / "cases").with_suffix(""))
        except ValueError:
            case_name = cmd_path.stem

    # === Parse the .cmd (recursively following inc:)
    # read_cmd_with_includes merges the main .cmd and every inc:'d file
    # into a single CmdLine list (each line carrying its src_path /
    # src_line so errors can be traced).
    cmd_sources = read_cmd_with_includes(cmd_path, proj_root)
    inc_count = sum(1 for cl in cmd_sources if cl.text.startswith("# >>> inc:"))
    if inc_count > 0:
        print(f"[run_case] resolved {inc_count} inc: directive(s) from {cmd_path.name}")

    # Collect every prefix-keyed directive from the merged sources.
    vlogan_args    = collect_prefixed(cmd_sources, "vlogan:")
    vcs_args       = collect_prefixed(cmd_sources, "vcs:")
    binary_arg_list = collect_prefixed(cmd_sources, "binary:")  # which simv binary to use
    simv_arg_list  = collect_prefixed(cmd_sources, "simv:")      # appended to the simv cmdline
    break_raw      = collect_prefixed(cmd_sources, "break:")
    # ssv_cfg: lines also feed cfg.info generation (inc:'d .cmds can
    # contribute overrides too).
    ssv_cfg_raw    = collect_prefixed(cmd_sources, "ssv_cfg:")
    # Hook lines: pre-build / pre-simulation / post-simulation.
    precomp_lines  = collect_prefixed(cmd_sources, "precomp:")
    presim_lines   = collect_prefixed(cmd_sources, "presim:")
    postsim_lines  = collect_prefixed(cmd_sources, "postsim:")
    # seed: -- controls the UVM random seed (random by default).
    seed_lines     = collect_prefixed(cmd_sources, "seed:")

    # === Resolve the simv path
    # Priority: --out > binary: <path> > --baseline (default sim/output/baseline/simv).
    if args.build_only:
        simv_path = Path(args.out).resolve() if args.out \
                    else (proj_root / args.baseline).resolve()
    elif binary_arg_list:
        simv_path = resolve_simv_arg(binary_arg_list[-1], proj_root)
    else:
        simv_path = (proj_root / args.baseline).resolve()

    # === Pre-build hook (cwd=proj_root; runs even when not rebuilding)
    if precomp_lines:
        rc = run_hooks(precomp_lines, proj_root, "precomp", abort_on_fail=True)
        if rc != 0:
            sys.exit(rc)

    # === Decide whether a build is needed.
    needs_build = (
        args.force_build or args.clean_simv or args.build_only
        or not simv_path.exists()
    )
    if args.no_build and needs_build:
        print(f"[run_case] simv {simv_path} is missing and --no-build was set: exiting",
              file=sys.stderr)
        sys.exit(1)

    if needs_build:
        if args.clean_simv and simv_path.exists():
            simv_path.unlink()
        rc = build_simv(simv_path, vlogan_args, vcs_args,
                         proj_root, dry_run=args.dry_run)
        if rc != 0:
            sys.exit(rc)
        print(f"[run_case] simv built: {simv_path}")
    else:
        print(f"[run_case] using existing simv: {simv_path}")

    if args.build_only or args.dry_run:
        return

    # === Prepare the case run dir: sim/<variant>/run/<case>/
    case_run_dir = simv_path.parent / "run" / case_name
    case_run_dir.mkdir(parents=True, exist_ok=True)

    # === Generate cfg.info (Python flattens ssv_cfg: + globs)
    # Written into case_run_dir, and the simv subprocess runs with cwd =
    # case_run_dir; the SV side's ssv_object::apply_overrides_in_cwd
    # opens the relative "cfg.info" path.
    root_name = os.environ.get("SSV_ROOT_NAME", "ssv_root_cfg")
    cfg_info = case_run_dir / "cfg.info"
    # all.cmd now lives under cfg/ (paired with the .cfg/.sv); not at the
    # project root.
    ssv_cfg_dir = proj_root / "cfg"
    try:
        build_cfg_info(
            sources=cmd_sources,
            all_cmd=(ssv_cfg_dir / "all.cmd").resolve(),
            root_name=root_name,
            case_cmd_name=cmd_path.name,
            out_path=cfg_info,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as e:
        print(f"[run_case] {e}", file=sys.stderr)
        sys.exit(1)

    # === Pre-simulation hook (cwd=case run dir)
    if presim_lines:
        rc = run_hooks(presim_lines, case_run_dir, "presim", abort_on_fail=True)
        if rc != 0:
            sys.exit(rc)

    # === Run simv. Pass the absolute simv path (no symlink; symlinks would
    # confuse VCS's daidir lookup). cwd=case_run_dir is set by
    # subprocess.run below; the SV side's ssv_object::apply_overrides_in_cwd
    # then opens the relative path "cfg.info". Do NOT pass +SSV_PWD=.
    run_cmd = [
        str(simv_path),
        "-no_save",
        "+UVM_VERBOSITY=UVM_LOW",
    ]

    # Append all simv: lines to the simv cmdline; these include
    # +UVM_TESTNAME=... (the only way to select a testclass).
    uvm_test_in_cmd = False
    for sa in simv_arg_list:
        run_cmd.append(sa)
        if sa.startswith("+UVM_TESTNAME="):
            uvm_test_in_cmd = 1
        print(f"[run_case] simv arg: {sa}")
    if not uvm_test_in_cmd:
        print(f"[run_case] WARNING: cases/{case_name}.cmd did not specify"
              f" `simv: +UVM_TESTNAME=<x>`; simv will not find a test.")

    # Pass through any vcs: lines starting with '+' as runtime plusargs
    # (legacy syntax; vcs: is normally a build-time directive).
    for va in vcs_args:
        if va.startswith("+"):
            run_cmd.append(va)

    # break: -> +kdb_stop=<time>
    for ba in break_raw:
        if ba == "start" or ba == "0":
            run_cmd.append("+kdb_stop=0")
            print("[run_case] break: start (kdb_stop=0)")
        else:
            run_cmd.append(f"+kdb_stop={ba}")
            print(f"[run_case] break: +{ba}")

    # seed: -> +UVM_SEED=<int>. Absent or "random" -> random in
    # [1, 2^31-1]. The seed is always appended (unlike ssv_cfg:) so
    # bugs can be reproduced by pinning a literal seed.
    if seed_lines:
        seed_spec = seed_lines[-1].strip()
        if seed_spec.lower() == "random":
            seed_val = random.randint(1, 2**31 - 1)
        else:
            try:
                seed_val = int(seed_spec)
            except ValueError:
                print(f"[run_case] WARN: invalid seed '{seed_spec}', falling back to random",
                      file=sys.stderr)
                seed_val = random.randint(1, 2**31 - 1)
    else:
        seed_val = random.randint(1, 2**31 - 1)
    run_cmd.append(f"+UVM_SEED={seed_val}")
    print(f"[run_case] seed: {seed_val} (UVM_SEED={seed_val})")

    run_log = case_run_dir / "sim.log"
    print(f"[run_case] run: {simv_path}")
    print(f"[run_case] run args: {' '.join(run_cmd[1:])}")
    if args.dry_run:
        return

    # Write the command itself at the top of sim.log; simv stdout follows.
    cmd_str = " ".join(run_cmd)
    # cwd=case_run_dir, simv uses argv[0] (absolute) to find simv.daidir,
    # so cwd does not affect that lookup. The SV side's
    # ssv_object::apply_overrides_in_cwd opens the relative path "cfg.info"
    # inside case_run_dir.
    run_cwd = case_run_dir
    run_env = setup_sim_env()
    # Stream-read simv's stdout and write it directly to sim.log rather
    # than letting PIPE buffer fill up; a full PIPE will block the child
    # process's writes, causing the dreaded "hang at 0% progress".
    import subprocess as _sp
    with open(run_log, "w") as flog:
        flog.write(f"Command: {cmd_str}\n\n")
        flog.flush()
        with _sp.Popen(run_cmd, env=run_env, cwd=str(run_cwd),
                       stdout=_sp.PIPE, stderr=_sp.STDOUT, bufsize=0) as proc:
            # Read+write in chunks to keep the pipe from filling up.
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                flog.write(chunk.decode("utf-8", errors="replace"))
                flog.flush()
            r = _sp.CompletedProcess(args=run_cmd, returncode=proc.wait())

    # === Post-simulation hook (cwd=case run dir; failure only logs,
    # does not change rc)
    if postsim_lines:
        for c in postsim_lines:
            run_hook(c, case_run_dir, "postsim")

    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
