#!/usr/bin/env python3
"""
generate_repo_intel.py

A robust, batteries-included collector that emits AI-ready artifacts:

- Project layout + config copies
- pipdeptree (flat + nested JSON)
- AST dumps (per file)
- CST dumps via LibCST (lossless + positions; no `_fields` usage)  (LibCST helpers/PositionProvider)  # :contentReference[oaicite:0]{index=0}
- Symbols & xrefs from SCIP (JSONL), with automatic SCIP generation if needed  # scip-python & scip print --json  :contentReference[oaicite:1]{index=1}
- Fallback symbol list via universal-ctags JSON                          # :contentReference[oaicite:2]{index=2}
- Import graph via Grimp → DOT (no pydeps flakiness)                     # :contentReference[oaicite:3]{index=3}
- Static call graph via PyCG (adjacency JSON)                            # :contentReference[oaicite:4]{index=4}
- Type diagnostics (basedpyright JSON) + dependency tree (text)          # :contentReference[oaicite:5]{index=5}
- Optional runtime profile via Pyinstrument → speedscope JSON            # :contentReference[oaicite:6]{index=6}
- Contracts: OpenAPI bundle/validate (if tools available), JSON Schemas, Pydantic model schemas (v2+)

It fails soft (logs & continues) when a tool is missing, and writes a manifest.

Tested on Linux/macOS with Python ≥3.10.

"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# ---------- Utilities ----------

REPO = Path.cwd()
ART = REPO / "artifacts"

DIRS = {
    "project": ART / "project",
    "deps": ART / "deps",
    "ast": ART / "ast",
    "cst": ART / "cst",
    "symbols": ART / "symbols",
    "imports": ART / "imports",
    "calls": ART / "calls",
    "runtime": ART / "runtime",
    "contracts": ART / "contracts",
    "openapi": ART / "contracts" / "openapi",
    "jsonschema": ART / "contracts" / "jsonschema" / "discovered",
    "pydantic": ART / "contracts" / "pydantic",
    "scip": ART / "scip",
}


def _resolve_tool(name: str) -> str | None:
    """Return the best-effort path to a CLI inside the active environment."""
    path = shutil.which(name)
    if path:
        return path
    exe_path = Path(sys.executable).resolve()
    for suffix in ("", ".exe"):
        candidate = exe_path.with_name(f"{name}{suffix}")
        if candidate.exists():
            return str(candidate)
    return None


def log(msg: str) -> None:
    print(f"[generate] {msg}")


def run(
    cmd: list[str] | str, *, cwd: Path | None = None, capture=False, check=True, env=None
) -> str | None:
    """Run a command safely; return stdout if capture=True. Logs failures and continues."""
    if isinstance(cmd, list):
        shown = " ".join(shlex.quote(str(x)) for x in cmd)
    else:
        shown = cmd
    log(f"→ {shown}")
    try:
        if capture:
            out = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                check=check,
                shell=isinstance(cmd, str),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            return out.stdout
        subprocess.run(cmd, cwd=cwd, env=env, check=check, shell=isinstance(cmd, str))
        return None
    except Exception as e:
        log(f"✖ command failed: {e}")
        return None


def ensure_dirs() -> None:
    for p in DIRS.values():
        p.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def git_ls_files(glob: str | None = None) -> list[Path]:
    args = ["git", "ls-files"]
    if glob:
        args.append(glob)
    out = run(args, capture=True)
    if out is None:
        # fallback: walk filesystem, skipping common junk
        pattern = glob or "**/*"
        if "*" not in pattern:
            pattern = f"**/{pattern}"
        ex = re.compile(r"(\.git/|\.venv/|__pycache__/|artifacts/)")
        return [
            p
            for p in REPO.glob(pattern)
            if p.is_file() and not ex.search(str(p.relative_to(REPO)).replace("\\", "/"))
        ]
    if not out.strip():
        return []
    return [REPO / line.strip() for line in out.splitlines() if line.strip()]


def filter_paths(paths: Iterable[Path], excludes: set[str]) -> list[Path]:
    if not excludes:
        return list(paths)
    ret = []
    for p in paths:
        sp = str(p)
        if any(x and x in sp for x in excludes):
            continue
        ret.append(p)
    return ret


# ---------- Core collectors ----------


def collect_project_layout():
    log("Collecting project files & tree…")
    files = run(["git", "ls-files"], capture=True) or ""
    write_text(DIRS["project"] / "files.txt", files)
    # 'tree' is optional
    tree_txt = run("tree -a -I '.git|.venv|__pycache__|node_modules' 2>/dev/null", capture=True)
    if tree_txt:
        write_text(DIRS["project"] / "tree.txt", tree_txt)
    # configs
    (DIRS["project"] / "config").mkdir(parents=True, exist_ok=True)
    for fname in ("pyproject.toml", "setup.cfg", "setup.py"):
        f = REPO / fname
        if f.exists():
            shutil.copy2(f, DIRS["project"] / "config" / f.name)
    # CI configs
    for pattern in (".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml"):
        for f in REPO.glob(pattern):
            try:
                shutil.copy2(f, DIRS["project"] / "config" / f.name)
            except Exception:
                pass


def collect_deps():
    exe = shutil.which("pipdeptree")
    if not exe:
        log("pipdeptree not found; skipping dependency trees.")
        return
    log("Collecting dependency trees via pipdeptree…")
    DIRS["deps"].mkdir(parents=True, exist_ok=True)
    flat = run([exe, "--json"], capture=True)
    if flat:
        write_text(DIRS["deps"] / "pipdeptree.flat.json", flat)
    nested = run([exe, "--json-tree"], capture=True)
    if nested:
        write_text(DIRS["deps"] / "pipdeptree.tree.json", nested)


def collect_ast(py_files: list[Path]):
    log(
        "Exporting AST (CPython ast.dump include_attributes=True)…"
    )  # :contentReference[oaicite:7]{index=7}
    import ast

    for fp in py_files:
        try:
            src = fp.read_text(encoding="utf-8", errors="replace")
            node = ast.parse(src, filename=str(fp))
            dump = ast.dump(node, annotate_fields=True, include_attributes=True)
            rel = fp.relative_to(REPO)
            out_path = (DIRS["ast"] / rel).with_suffix(rel.suffix + ".ast.json")
            write_json(
                out_path,
                {
                    "file": str(rel),
                    "ast": dump,
                },
            )
        except Exception as e:
            log(f"[AST] skip {fp}: {e}")


def collect_cst(py_files: list[Path]):
    log(
        "Exporting CST via LibCST (helpers.get_node_fields + PositionProvider)…"
    )  # :contentReference[oaicite:8]{index=8}
    import libcst as cst
    from libcst.helpers import get_node_fields
    from libcst.metadata import MetadataWrapper, PositionProvider

    def to_obj(node, posmap):
        if isinstance(node, cst.CSTNode):
            out = {"type": node.__class__.__name__}
            rng = posmap.get(node)
            if rng:
                out["range"] = {
                    "start": [rng.start.line, rng.start.column],
                    "end": [rng.end.line, rng.end.column],
                }
            for fld in get_node_fields(node):
                out[fld.name] = to_obj(getattr(node, fld.name), posmap)
            return out
        if isinstance(node, list):
            return [to_obj(x, posmap) for x in node]
        return str(node)

    for fp in py_files:
        try:
            src = fp.read_text(encoding="utf-8", errors="replace")
            mod = cst.parse_module(src)
            pos = MetadataWrapper(mod).resolve(PositionProvider)
            obj = to_obj(mod, pos)
            rel = fp.relative_to(REPO)
            out_path = (DIRS["cst"] / rel).with_suffix(rel.suffix + ".cst.json")
            write_json(out_path, obj)
        except Exception as e:
            log(f"[CST] skip {fp}: {e}")


# ----- SCIP (symbols & xrefs) -----


def ensure_scip_json(user_path: Path | None) -> Path | None:
    """
    Return a path to SCIP JSON:
    - if user provided, use it
    - else if index.scip exists, scip print --json to artifacts/scip/index.json
    - else try `scip-python index .` then print to JSON
    """
    out_json = DIRS["scip"] / "index.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    if user_path:
        p = Path(user_path)
        if p.exists():
            log(f"Using provided SCIP JSON: {p}")
            return p
        log(f"Provided --scip path not found: {p}")

    idx = REPO / "index.scip"
    if idx.exists() and shutil.which("scip"):
        s = run(
            ["scip", "print", "--json", str(idx)], capture=True
        )  # :contentReference[oaicite:9]{index=9}
        if s:
            write_text(out_json, s)
            return out_json

    # Try to generate index.scip
    if shutil.which("scip-python"):
        # project name/version are optional niceties  # :contentReference[oaicite:10]{index=10}
        proj = os.environ.get("SCIP_PROJECT_NAME", REPO.name)
        ver = os.environ.get("SCIP_PROJECT_VERSION", "")
        args = ["scip-python", "index", ".", "--project-name", proj]
        if ver:
            args += ["--project-version", ver]
        run(args)
        if (REPO / "index.scip").exists() and shutil.which("scip"):
            s = run(
                ["scip", "print", "--json", "index.scip"], capture=True
            )  # :contentReference[oaicite:11]{index=11}
            if s:
                write_text(out_json, s)
                return out_json
        else:
            log("scip-python ran but index.scip not found or `scip` CLI missing.")
    else:
        log("scip-python not found on PATH; skipping SCIP generation.")
    return None


def scip_to_symbol_xrefs(scip_json_path: Path):
    try:
        data = json.loads(scip_json_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"[SCIP] failed to read JSON: {e}")
        return

    docs = data.get("documents", [])
    defs = []
    xrefs = {}
    for d in docs:
        path = d.get("relative_path")
        occs = d.get("occurrences", [])
        # optional symbol-level documentation array (per SCIP JSON print output)
        symdocs = (
            {s.get("symbol"): s.get("documentation", []) for s in d.get("symbols", [])}
            if d.get("symbols")
            else {}
        )
        for occ in occs:
            sym = occ.get("symbol")
            roles = occ.get("symbol_roles") or occ.get("roles") or 0  # LSB=definition
            rng = occ.get("range") or occ.get("enclosing_range")
            if not sym or rng is None:
                continue
            row = {"symbol": sym, "path": path, "range": rng, "doc": symdocs.get(sym)}
            rec = xrefs.setdefault(sym, {"defs": [], "refs": []})
            if roles & 1:
                defs.append(row)
                rec["defs"].append(row)
            else:
                rec["refs"].append(row)

    with (DIRS["symbols"] / "scip.symbols.ndjson").open("w", encoding="utf-8") as f:
        for row in defs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (DIRS["symbols"] / "scip.xrefs.ndjson").open("w", encoding="utf-8") as f:
        for sym, rows in xrefs.items():
            f.write(json.dumps({"symbol": sym, **rows}, ensure_ascii=False) + "\n")


def collect_ctags_symbols():
    if not shutil.which("ctags"):
        log("ctags not found; skipping ctags symbol export.")
        return
    # universal-ctags JSON (JSON lines)  # :contentReference[oaicite:12]{index=12}
    output = DIRS["symbols"] / "ctags.json"
    with contextlib.suppress(FileNotFoundError):
        output.unlink()
    run(
        [
            "ctags",
            "-R",
            "--languages=Python",
            "--kinds-Python=+c-f-m-v",
            "--fields=+n+K+S",
            "--output-format=json",
            "-f",
            str(output),
            ".",
        ]
    )


# ----- Import graph via Grimp → DOT -----


def collect_import_graph(packages: list[str], excludes: set[str]):
    """
    Build import graph(s) for the given top-level package(s) using Grimp,
    then write a DOT. Works without Graphviz installed; DOT is plain text.
    """
    try:
        import grimp  # :contentReference[oaicite:13]{index=13}

        edges: set[tuple[str, str]] = set()
        for pkg in packages:
            log(f"Building import graph for package '{pkg}' via Grimp…")
            g = grimp.build_graph(
                pkg
            )  # returns ImportGraph  # :contentReference[oaicite:14]{index=14}
            for m in g.modules:
                for n in g.find_modules_directly_imported_by(m):
                    if any(x in n for x in excludes):
                        continue
                    edges.add((m, n))
        dot_lines = ["digraph G {"]
        for a, b in sorted(edges):
            dot_lines.append(f'  "{a}" -> "{b}";')
        dot_lines.append("}")
        write_text(DIRS["imports"] / "imports.dot", "\n".join(dot_lines))
        # render to svg if dot is available
        if shutil.which("dot"):
            run(
                [
                    "dot",
                    "-Tsvg",
                    str(DIRS["imports"] / "imports.dot"),
                    "-o",
                    str(DIRS["imports"] / "imports.svg"),
                ]
            )
    except Exception as e:
        log(f"[imports] Grimp failed: {e}")
        # Fallback: very rough static scan of 'import' lines
        try:
            py_files = filter_paths(git_ls_files("*.py"), excludes)
            edges = set()
            for p in py_files:
                relpkg = ".".join(p.relative_to(REPO).with_suffix("").parts)
                for line in p.read_text("utf-8", "ignore").splitlines():
                    m1 = re.match(r"\s*import\s+([a-zA-Z_][\w\.]*)", line)
                    m2 = re.match(r"\s*from\s+([a-zA-Z_][\w\.]*)\s+import", line)
                    target = (m1 or m2).group(1) if (m1 or m2) else None
                    if target and not any(x in target for x in excludes):
                        edges.add((relpkg, target))
            dot_lines = ["digraph G {"] + [f'  "{a}" -> "{b}";' for a, b in sorted(edges)] + ["}"]
            write_text(DIRS["imports"] / "imports.dot", "\n".join(dot_lines))
        except Exception as e2:
            log(f"[imports] fallback scan failed: {e2}")


# ----- Static call graph via PyCG -----


def collect_call_graph_pycg(packages: list[str], excludes: set[str]):
    pycg_module = importlib.util.find_spec("pycg")
    pycg_cli = _resolve_tool("pycg")
    if pycg_module is None and pycg_cli is None:
        log("pycg not found; skipping static call graph.")
        return
    # Pass explicit file list to avoid pycg recursively hitting odd paths
    files = filter_paths(git_ls_files("*.py"), excludes)
    if not files:
        log("No Python files found for call graph.")
        return
    # PyCG CLI produces JSON adjacency (and has an ICSE'21 paper)  # :contentReference[oaicite:15]{index=15}
    out = DIRS["calls"] / "pycg.simple.json"
    if pycg_module is not None:
        args = [sys.executable, "-m", "pycg"]
    else:
        args = [pycg_cli or "pycg"]
    if packages:
        args += ["--package", packages[0]]
    args += [str(p) for p in files] + ["-o", str(out)]
    run(args)


# ----- Type diagnostics & dependency tree via basedpyright -----


def collect_pyright():
    exe = shutil.which("basedpyright") or shutil.which("pyright")
    if not exe:
        log("basedpyright/pyright not found; skipping type diagnostics.")
        return
    # Two runs by design: JSON diagnostics vs dependency tree  # :contentReference[oaicite:16]{index=16}
    diag = run([exe, "-p", ".", "--outputjson"], capture=True)
    if diag:
        write_text(DIRS["deps"] / "pyright.diagnostics.json", diag)
    deps = run([exe, "-p", ".", "--dependencies"], capture=True)
    if deps:
        write_text(DIRS["deps"] / "pyright.dependencies.txt", deps)


# ----- Runtime profile via Pyinstrument → speedscope -----


def collect_runtime_profile(entry_cmd: str | None):
    if not entry_cmd:
        return
    if importlib.util.find_spec("pyinstrument") is None and shutil.which("pyinstrument") is None:
        log("pyinstrument not found; skipping runtime profile.")
        return
    out = DIRS["runtime"] / "profile.speedscope.json"
    cmd = [
        sys.executable,
        "-m",
        "pyinstrument",
        "-r",
        "speedscope",
        "-o",
        str(out),
    ]
    cmd.extend(shlex.split(entry_cmd))
    run(cmd)


# ----- Contracts: OpenAPI, JSON Schemas, Pydantic model schemas -----


def collect_openapi():
    produced = 0
    if shutil.which("redocly"):
        # bundle everything into JSON and validate (if openapi-cli is present)
        for f in git_ls_files("*.yml") + git_ls_files("*.yaml") + git_ls_files("*.json"):
            name = f.name.lower()
            if any(k in name for k in ("openapi", "swagger")):
                base = f.with_suffix("").name + ".json"
                out = DIRS["openapi"] / base
                res = run(
                    ["redocly", "bundle", str(f), "--output", str(out), "--ext", "json"],
                    capture=True,
                )
                if out.exists():
                    produced += 1
        # optional validation with redocly "openapi-cli validate"
        json_files = sorted(DIRS["openapi"].glob("*.json"))
        if json_files and shutil.which("openapi-cli"):
            run(
                ["openapi-cli", "validate", *map(str, json_files), "--format", "json"],
                capture=False,
            )
    else:
        log("redocly CLI not found; skipping OpenAPI bundle/validate.")


def collect_jsonschemas():
    for f in git_ls_files("*.schema.json"):
        try:
            shutil.copy2(f, DIRS["jsonschema"] / f.name)
        except Exception:
            pass


def collect_pydantic_schemas(src_root: Path, packages: list[str]):
    # Emit Pydantic v2 model schemas via model_json_schema()
    code = r"""
import importlib, inspect, json, pathlib, pkgutil, sys

outdir = pathlib.Path(sys.argv[1]); outdir.mkdir(parents=True, exist_ok=True)
src_root = pathlib.Path(sys.argv[2]).resolve()
targets = json.loads(sys.argv[3])
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))
try:
    from pydantic import BaseModel
except Exception:
    raise SystemExit(0)

try:
    from pydantic_settings import BaseSettings
except Exception:
    class BaseSettings(BaseModel):
        pass

SKIP_DIRS = {".git", "artifacts", ".venv", "node_modules"}

def iter_top_level_packages(root: pathlib.Path):
    if targets:
        for name in targets:
            path = (root / name).resolve()
            if path.exists():
                yield name, path
        return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        if path.name.startswith(".") or path.name in SKIP_DIRS:
            continue
        if (path / "__init__.py").exists() or any(path.glob("*.py")):
            yield path.name, path

def walk_modules(pkgname: str, pkgpath: pathlib.Path):
    yield pkgname
    for _finder, name, _ispkg in pkgutil.walk_packages([str(pkgpath)], prefix=f"{pkgname}."):
        yield name

seen=set()
for pkgname, pkgpath in iter_top_level_packages(src_root):
    for mname in walk_modules(pkgname, pkgpath):
        if mname in seen: continue
        seen.add(mname)
        try:
            mod = importlib.import_module(mname)
        except Exception:
            continue
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            try:
                if issubclass(obj, BaseModel) or issubclass(obj, BaseSettings):
                    schema = obj.model_json_schema()
                    target = outdir / f"{mname}.{name}.schema.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(schema, indent=2))
            except Exception:
                pass
"""
    run(
        [
            sys.executable,
            "-c",
            code,
            str(DIRS["pydantic"]),
            str(src_root),
            json.dumps(packages),
        ],
        capture=True,
    )


# ---------- Manifest ----------


def write_manifest(extra: dict):
    manifest = {
        "repo_root": str(REPO),
        "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds")
        + "Z",
        "artifacts": {k: str(v) for k, v in DIRS.items()},
        "tools": {
            "basedpyright": shutil.which("basedpyright"),
            "pyright": shutil.which("pyright"),
            "pyinstrument": shutil.which("pyinstrument"),
            "pipdeptree": shutil.which("pipdeptree"),
            "ctags": shutil.which("ctags"),
            "grimp": bool(importlib.util.find_spec("grimp")),
            "pycg": shutil.which("pycg"),
            "scip": shutil.which("scip"),
            "scip-python": shutil.which("scip-python"),
            "dot": shutil.which("dot"),
        },
    }
    manifest.update(extra)
    write_json(ART / "manifest.json", manifest)


# ---------- Main ----------


def main():
    ap = argparse.ArgumentParser(description="Generate AI-ready repository intelligence.")
    ap.add_argument(
        "--package",
        action="append",
        default=[],
        help="Top-level package name(s). Repeat for multiple.",
    )
    ap.add_argument("--src", default=".", help="Source root (default: .)")
    ap.add_argument(
        "--entry",
        default=None,
        help='Runtime entry command to profile (e.g. "python -m pkg.cli --help")',
    )
    ap.add_argument(
        "--exclude",
        default="",
        help="Comma-separated substrings to exclude (e.g. 'xtr-warp,site-mkdocs-suite')",
    )
    ap.add_argument(
        "--scip", type=Path, default=None, help="Optional path to an existing SCIP JSON export"
    )
    args = ap.parse_args()

    # Normalize & ensure output dirs
    ensure_dirs()

    # Make source root importable (important for Grimp/Pydantic discovery)
    src_root = (REPO / args.src).resolve()
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    excludes = {s.strip() for s in args.exclude.split(",") if s.strip()}
    packages = args.package or []  # allow empty; Grimp fallback will rough-scan imports

    # 1) Project files & configs
    collect_project_layout()

    # 2) Dependencies
    collect_deps()

    # 3) File list (tracked .py)
    py_files = filter_paths(git_ls_files("*.py"), excludes)

    # 4) AST / 5) CST
    collect_ast(py_files)
    collect_cst(py_files)

    # 6) SCIP symbols/xrefs
    scip_json = ensure_scip_json(args.scip)
    if scip_json:
        # keep a provenance copy
        try:
            shutil.copy2(scip_json, DIRS["scip"] / "index.json")
        except Exception:
            pass
        scip_to_symbol_xrefs(DIRS["scip"] / "index.json")
    else:
        log("[SCIP] not available; will rely on ctags symbols only.")

    # 7) ctags symbols (fallback / supplemental)
    collect_ctags_symbols()

    # 8) Import graph (Grimp)
    if not packages:
        # Try to infer likely package names from top-level dirs with .py files
        tops = {p.parts[0] for p in [f.relative_to(REPO) for f in py_files] if len(p.parts) > 0}
        # filter obvious junk
        packages = sorted(
            [
                t
                for t in tops
                if re.match(r"^[a-zA-Z_]\w*$", t) and t not in ("tests", "scripts", "tools")
            ]
        )
    collect_import_graph(packages, excludes)

    # 9) Static call graph (PyCG)
    collect_call_graph_pycg(packages, excludes)

    # 10) Type diagnostics & dep tree
    collect_pyright()

    # 11) Runtime (optional)
    collect_runtime_profile(args.entry)

    # 12) Contracts
    collect_openapi()
    collect_jsonschemas()
    collect_pydantic_schemas(src_root, packages)

    # 13) Manifest
    write_manifest(
        {
            "packages": packages,
            "excludes": sorted(excludes),
            "src_root": str(src_root),
            "scip_json": str(DIRS["scip"] / "index.json")
            if (DIRS["scip"] / "index.json").exists()
            else None,
        }
    )

    log("✅ Done. See artifacts/manifest.json for a map of everything.")


if __name__ == "__main__":
    main()
