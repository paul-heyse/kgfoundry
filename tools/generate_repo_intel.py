#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
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


def run(cmd, cwd=REPO, check=True, shell=False, capture=False):
    print(f"→ {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}")
    if capture:
        out = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return out.stdout
    subprocess.run(cmd, cwd=cwd, check=check, shell=shell)


def ensure_dirs():
    for p in DIRS.values():
        p.mkdir(parents=True, exist_ok=True)


def list_tracked_py_files():
    out = run(["git", "ls-files", "*.py"], capture=True)
    return [REPO / line.strip() for line in out.splitlines() if line.strip()]


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_ast(files):
    import ast

    for fp in files:
        try:
            src = fp.read_text(encoding="utf-8", errors="replace")
            node = ast.parse(src, filename=str(fp))
            # JSON-serializable AST dump with positions
            s = ast.dump(node, annotate_fields=True, include_attributes=True)
            write_text(DIRS["ast"] / (fp.name + ".json"), s)
        except Exception as e:
            print(f"[AST] skip {fp}: {e}")


def dump_cst(files):
    import libcst as cst
    from libcst.metadata import MetadataWrapper, PositionProvider, ScopeProvider

    def cst_to_json(n):
        # minimal structural JSON for LibCST nodes
        if isinstance(n, cst.CSTNode):
            data = {"type": n.__class__.__name__}
            for field in n._fields:
                v = getattr(n, field)
                data[field] = cst_to_json(v)
            return data
        if isinstance(n, (list, tuple)):
            return [cst_to_json(x) for x in n]
        if n is None or isinstance(n, (str, int, float, bool)):
            return n
        # Tokens / whitespace etc → string form
        return str(n)

    for fp in files:
        try:
            src = fp.read_text(encoding="utf-8", errors="replace")
            mod = cst.parse_module(src)
            wrapper = MetadataWrapper(mod)
            wrapper.resolve(ScopeProvider)
            wrapper.resolve(PositionProvider)
            j = cst_to_json(mod)
            write_json(DIRS["cst"] / (fp.name + ".json"), j)
        except Exception as e:
            print(f"[CST] skip {fp}: {e}")


def process_scip(scip_json: Path):
    # normalize a copy for provenance
    if scip_json and scip_json.exists():
        dst = DIRS["scip"] / "index.json"
        dst.write_bytes(scip_json.read_bytes())

    # Build symbol table & xrefs from SCIP JSON (occurrences + roles)
    try:
        data = json.loads(scip_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[SCIP] failed to read: {e}")
        return

    docs = data.get("documents", [])
    defs = []  # one row per definition
    xrefs = {}  # symbol -> {defs:[], refs:[]}

    for d in docs:
        path = d.get("relative_path")
        occs = d.get("occurrences", [])
        lang = None
        # symbol docs (if present)
        symdocs = {s.get("symbol"): s.get("documentation", []) for s in d.get("symbols", [])}

        for occ in occs:
            sym = occ.get("symbol")
            roles = occ.get("symbol_roles") or occ.get("roles") or 0
            rng = occ.get("range") or occ.get("enclosing_range")
            if rng is None:
                continue
            entry = {"symbol": sym, "path": path, "range": rng, "doc": symdocs.get(sym)}

            rec = xrefs.setdefault(sym, {"defs": [], "refs": []})
            if roles & 1:  # LSB = definition (per SCIP/LSIF convention)
                rec["defs"].append(entry)
                defs.append({"symbol": sym, "path": path, "range": rng, "doc": symdocs.get(sym)})
            else:
                rec["refs"].append(entry)

    # Write NDJSON for easy streaming
    with (DIRS["symbols"] / "scip.symbols.ndjson").open("w", encoding="utf-8") as f:
        for row in defs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (DIRS["symbols"] / "scip.xrefs.ndjson").open("w", encoding="utf-8") as f:
        for sym, rows in xrefs.items():
            f.write(json.dumps({"symbol": sym, **rows}, ensure_ascii=False) + "\n")


def run_pipdeptree():
    write_text(DIRS["deps"] / "pipdeptree.flat.json", run(["pipdeptree", "--json"], capture=True))
    write_text(
        DIRS["deps"] / "pipdeptree.tree.json", run(["pipdeptree", "--json-tree"], capture=True)
    )


def run_ctags():
    try:
        run(
            [
                "ctags",
                "-R",
                "--languages=Python",
                "--kinds-Python=+c-f-m-v",
                "--fields=+n+K+S",
                "--extras=+q",
                "--output-format=json",
                "-f",
                str(DIRS["symbols"] / "ctags.json"),
                ".",
            ]
        )
    except Exception as e:
        print(f"[ctags] skip: {e}")


def run_pydeps():
    try:
        run(
            [
                "pydeps",
                ".",
                "--noshow",
                "--show-dot",
                "--dot-output",
                str(DIRS["imports"] / "pydeps.dot"),
            ]
        )
        # Render to svg if dot exists
        try:
            run(
                [
                    "dot",
                    "-Tsvg",
                    str(DIRS["imports"] / "pydeps.dot"),
                    "-o",
                    str(DIRS["imports"] / "pydeps.svg"),
                ]
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[pydeps] skip: {e}")


def run_callgraphs(py_files):
    try:
        dot = run(
            ["pyan3", *[str(p) for p in py_files], "--uses", "--no-defines", "--dot"], capture=True
        )
        write_text(DIRS["calls"] / "pyan3.dot", dot)
    except Exception as e:
        print(f"[pyan3] skip: {e}")
    try:
        run(
            [
                "pycg",
                "--package",
                ".",
                *[str(p) for p in py_files],
                "-o",
                str(DIRS["calls"] / "pycg.simple.json"),
            ]
        )
    except Exception as e:
        print(f"[PyCG] skip: {e}")


def run_pyright():
    # Prefer basedpyright if present
    exe = shutil.which("basedpyright") or shutil.which("pyright")
    if not exe:
        print("[pyright] not installed")
        return
    try:
        out = run([exe, "--outputjson", "--dependencies", "-p", "."], capture=True)
        write_text(DIRS["deps"] / "pyright.report.json", out)
    except Exception as e:
        print(f"[pyright] skip: {e}")


def run_runtime(entry_cmd: str | None):
    if not entry_cmd:
        return
    try:
        run(
            shlex.split(f"viztracer -o {DIRS['runtime'] / 'viztracer.json'} {entry_cmd}"),
            shell=False,
        )
    except Exception as e:
        print(f"[viztracer] skip: {e}")
    try:
        run(
            shlex.split(
                f"pyinstrument -r speedscope -o {DIRS['runtime'] / 'pyinstrument.speedscope.json'} {entry_cmd}"
            ),
            shell=False,
        )
    except Exception as e:
        print(f"[pyinstrument] skip: {e}")


def collect_openapi():
    try:
        candidates = run(
            [
                "git",
                "ls-files",
                "*openapi*.yml",
                "*openapi*.yaml",
                "*swagger*.yml",
                "*openapi*.json",
            ],
            capture=True,
        )
        for f in [x for x in candidates.splitlines() if x.strip()]:
            base = Path(f).name.rsplit(".", 1)[0] + ".json"
            try:
                run(
                    [
                        "redocly",
                        "bundle",
                        f,
                        "--output",
                        str(DIRS["openapi"] / base),
                        "--ext",
                        "json",
                    ]
                )
            except Exception as e:
                print(f"[openapi bundle] skip {f}: {e}")
        # validate all produced JSON
        try:
            # If no files, this will fail; ignore
            run(
                ["openapi-cli", "validate", str(DIRS["openapi"]) + "/*.json", "--format", "json"],
                shell=True,
            )
        except Exception:
            pass
    except Exception:
        pass


def collect_jsonschema():
    try:
        out = run(["git", "ls-files", "*.schema.json"], capture=True)
        for f in [x for x in out.splitlines() if x.strip()]:
            src = REPO / f
            dst = DIRS["jsonschema"] / Path(f).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    except Exception:
        pass


def derive_pydantic_schemas(py_files):
    # best effort: import modules in a temp process to call model_json_schema
    code = r"""
import importlib, inspect, json, pkgutil, sys, pathlib
from pydantic import BaseModel
try:
    from pydantic_settings import BaseSettings
except Exception:
    class BaseSettings(BaseModel): pass

root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
seen = set()
outdir = pathlib.Path(sys.argv[2]).resolve()
outdir.mkdir(parents=True, exist_ok=True)

def iter_modules(start):
    pkg = str(start)
    for m in pkgutil.walk_packages([pkg], prefix=""):
        yield m.name

def try_dump(modname):
    try:
        mod = importlib.import_module(modname)
    except Exception:
        return
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, BaseModel) or issubclass(obj, BaseSettings):
            try:
                schema = obj.model_json_schema()
                (outdir / f"{modname}.{name}.schema.json").write_text(json.dumps(schema, indent=2))
            except Exception:
                pass

for m in iter_modules(root):
    if m not in seen:
        seen.add(m)
        try_dump(m)
"""
    try:
        run([sys.executable, "-c", code, str(REPO), str(DIRS["pydantic"])])
    except Exception as e:
        print(f"[pydantic] skip: {e}")


def write_manifest(extra: dict):
    manifest = {
        "repo_root": str(REPO),
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "artifacts": {k: str(v) for k, v in DIRS.items()},
    }
    manifest.update(extra)
    write_json(ART / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scip", type=Path, help="Path to SCIP JSON export", required=True)
    parser.add_argument(
        "--entry",
        type=str,
        default=None,
        help='Runtime entry command, e.g. "python -m pkg.cli --help"',
    )
    args = parser.parse_args()

    ensure_dirs()

    # Project view & configs
    write_text(DIRS["project"] / "files.txt", run(["git", "ls-files"], capture=True))
    try:
        write_text(
            DIRS["project"] / "tree.txt",
            run("tree -a -I '.git|.venv|__pycache__'", shell=True, capture=True),
        )
    except Exception:
        pass
    for f in ("pyproject.toml", "setup.cfg", "setup.py"):
        p = REPO / f
        if p.exists():
            (DIRS["project"] / "config").mkdir(parents=True, exist_ok=True)
            (DIRS["project"] / "config" / p.name).write_bytes(p.read_bytes())

    # Deps
    run_pipdeptree()

    # Files
    py_files = list_tracked_py_files()

    # AST & CST
    dump_ast(py_files)
    dump_cst(py_files)

    # SCIP
    process_scip(args.scip)

    # Symbols via ctags
    run_ctags()

    # Imports/calls
    run_pydeps()
    run_callgraphs(py_files)

    # Static diagnostics + deps
    try:
        run_pyright()
    except Exception:
        pass

    # Runtime (optional)
    run_runtime(args.entry)

    # Contracts
    collect_openapi()
    collect_jsonschema()
    derive_pydantic_schemas(py_files)

    # Manifest
    write_manifest({"scip_json": str(args.scip)})


if __name__ == "__main__":
    main()
