# Document Generation Cleanup Report

This report identifies all remaining document generation related files outside `codeintel_rev/`, tests that reference deleted modules, and orphaned tests with missing dependencies.

## 1. Document Generation Files (Outside codeintel_rev/)

### Scripts & Build Tools
- **`tools/update_docs.sh`** - Main documentation build script that references many deleted tools:
  - Line 164: `tools/generate_docstrings.py` (deleted)
  - Line 198: `tools/mkdocs_suite/docs/openapi/` (directory likely deleted)
  - Line 205: `tools/validate_gallery.py` (deleted)
  - Line 211: `tools/gen_readmes.py` (deleted)
  - Line 228: `tools/update_navmaps.py` (deleted)
  - Line 231: `tools/navmap/build_navmap.py` (module deleted)
  - Line 234: `tools/navmap/check_navmap.py` (module deleted)
  - Line 246: `docs/_scripts/build_symbol_index.py` (docs/ deleted)
  - Line 252: `tools/docs/build_test_map.py` (module deleted)
  - Line 258: `tools/docs/scan_observability.py` (module deleted)
  - Line 264: `tools/docs/export_schemas.py` (module deleted)
  - Line 270: `docs/_scripts/validate_artifacts.py` (docs/ deleted)
  - Line 276: `tools/docs/build_graphs.py` (module deleted)
  - Line 304: `tools/mkdocs_suite/mkdocs.yml` (directory likely deleted)
  - Line 161: References `docs/_scripts` directory (deleted)

- **`tools/hooks/run_readme_generator.sh`** - Pre-commit hook:
  - Line 30: References `tools/gen_readmes.py` (deleted)

- **`tools/hooks/docformatter.py`** - ✅ KEEP (This is just a wrapper around docformatter, not doc generation)

### Python Modules with Broken Imports
- **`tools/cli/__init__.py`** - References deleted navmap module:
  - Line 33: `import_module("tools.navmap.build_navmap")` (module deleted)
  - Function `build_navmap()` will fail at runtime

- **`tools/__init__.py`** - References deleted modules in TYPE_CHECKING:
  - Lines 111-118: TYPE_CHECKING imports for `tools.docs`, `tools.docstring_builder`, `tools.gen_readmes`, `tools.generate_pr_summary`, `tools.navmap` (all deleted)
  - Lines 202-210: `MODULE_EXPORTS` dictionary includes:
    - `"docs": "tools.docs"` (deleted)
    - `"docstring_builder": "tools.docstring_builder"` (deleted)
    - `"gen_readmes": "tools.gen_readmes"` (deleted)
    - `"generate_pr_summary": "tools.generate_pr_summary"` (deleted)
    - `"navmap": "tools.navmap"` (deleted)
  - Lines 260-265: `__all__` includes `"docs"`, `"docstring_builder"`, `"gen_readmes"`, `"generate_pr_summary"`, `"navmap"`

### Configuration Files
- **`openapi/_augment_cli.yaml`** - OpenAPI spec with navmap operations:
  - Lines 220-245: Defines `navmap.build` and `navmap.check` operations that reference deleted modules
  - Line 227: `x-handler: "tools.navmap.build_navmap:main"` (deleted)
  - Line 240: `x-handler: "tools.navmap.check_navmap:main"` (deleted)

### Schema Files (Potentially Orphaned)
- **`schema/tools/docstring_builder_cli.json`** - Schema for deleted docstring builder
- **`schema/tools/docstring_cache.json`** - Schema for deleted docstring cache
- **`schema/tools/navmap_document.json`** - Schema for deleted navmap tooling

### Documentation Schema Files (Potentially Orphaned)
- **`schema/docs/symbol-reverse-lookup.schema.json`** - May be used by codeintel_rev
- **`schema/docs/symbol-delta.schema.json`** - May be used by codeintel_rev
- **`schema/docs/symbol-index.schema.json`** - May be used by codeintel_rev

## 2. Tests Related to Document Generation

### Tests with Broken Imports (Orphaned)
- **`tests/tools/navmap/test_cache_interfaces.py`** - Imports from deleted `tools.navmap`:
  - Line 9: `from tools.navmap.cache import NavmapCollectorCache, NavmapRepairCache`
  - Line 16: `from tools.navmap.build_navmap import ModuleInfo`
  - Line 17: `from tools.navmap.repair_navmaps import RepairResult`

- **`tests/tools/navmap/test_cli_api.py`** - Imports from deleted `tools.navmap`:
  - Line 10: `from tools.navmap.api import repair_all_with_config, repair_module_with_config`
  - Line 11: `from tools.navmap.config import NavmapRepairOptions`
  - Line 12: `from tools.navmap.repair_navmaps import RepairResult`
  - Line 18: `from tools.navmap.build_navmap import ModuleInfo`

- **`tests/tools/navmap/test_config_models.py`** - Imports from deleted `tools.navmap`:
  - Line 12: `from tools.navmap.config import NavmapRepairOptions, NavmapStripOptions`

- **`tests/test_cli_context_modules.py`** - Imports from deleted modules:
  - Line 7: `from docs import cli_context as docs_cli_context` (docs/ deleted)
  - Line 11: `from tools.docstring_builder import cli_context as docstrings_context` (deleted)
  - Line 12: `from tools.navmap import cli_context as navmap_context` (deleted)

### Tests That May Reference Deleted Modules (Need Verification)
- **`tests/tools/test_cli_standardization.py`** - May import from deleted modules
- **`tests/tools/test_typing_imports.py`** - May import from deleted modules
- **`tests/test_logging_contexts.py`** - May import from deleted modules
- **`tests/test_regression_public_api_hardening.py`** - May import from deleted modules
- **`tests/tools/codemods/test_transformers.py`** - May import from deleted modules

### Test Directory Structure
- **`tests/tools/navmap/`** - Entire directory is orphaned:
  - `tests/tools/navmap/__init__.py`
  - `tests/tools/navmap/test_cache_interfaces.py`
  - `tests/tools/navmap/test_cli_api.py`
  - `tests/tools/navmap/test_config_models.py`

## 3. Orphaned Tests (Missing Inputs/Dependencies)

### Definitely Orphaned (Will Fail on Import)
1. **`tests/tools/navmap/test_cache_interfaces.py`** - All imports from `tools.navmap.*` fail
2. **`tests/tools/navmap/test_cli_api.py`** - All imports from `tools.navmap.*` fail
3. **`tests/tools/navmap/test_config_models.py`** - All imports from `tools.navmap.*` fail
4. **`tests/test_cli_context_modules.py`** - Imports from `docs.*`, `tools.docstring_builder.*`, `tools.navmap.*` fail

### Potentially Orphaned (Need Manual Review)
- Tests that may have conditional imports or try/except blocks that mask failures
- Tests that reference deleted modules but may not execute those code paths

## 4. Files Referencing Deleted Paths

### Configuration/Reference Files
- **`pyproject.toml`** - May have references (check for doc generation dependencies)
- **`pyrightconfig.json`** - May exclude deleted paths
- **`pyrefly.toml`** - May exclude deleted paths
- **`AGENTS.md`** - ⚠️ Contains 5 references to deleted paths (verify and update)
- **`repo_metrics.json`** - May reference deleted paths
- **`tools/_shared/error_codes.py`** - May reference deleted error codes
- **`scripts/bootstrap.sh`** - ⚠️ Contains 5 references to deleted paths (verify and update)
- **`tools/lint/apply_postponed_annotations.py`** - May reference deleted paths

### Documentation/Planning Files
- **`openspec/AGENTS.md`** - May reference deleted tooling
- Various files in `openspec/changes/` that reference documentation toolchain

## Summary Statistics

- **Document generation scripts**: 2 files (`tools/update_docs.sh`, `tools/hooks/run_readme_generator.sh`)
- **Python modules with broken imports**: 2 files (`tools/cli/__init__.py`, `tools/__init__.py`)
- **Configuration files**: 1 file (`openapi/_augment_cli.yaml`)
- **Schema files (potentially orphaned)**: 3 files in `schema/tools/`
- **Test files (definitely orphaned)**: 4 files
- **Test directories (orphaned)**: 1 directory (`tests/tools/navmap/`)
- **Total files to review/clean**: ~15-20 files

## Recommended Cleanup Order

1. **Delete orphaned test directory**: `tests/tools/navmap/`
2. **Fix or delete broken imports** in:
   - `tools/cli/__init__.py` (remove `build_navmap` function)
   - `tools/__init__.py` (remove deleted modules from MODULE_EXPORTS and TYPE_CHECKING)
   - `tests/test_cli_context_modules.py` (remove or fix imports)
3. **Delete or update scripts**:
   - `tools/update_docs.sh` (delete or heavily refactor)
   - `tools/hooks/run_readme_generator.sh` (delete or update)
4. **Clean up configuration**:
   - `openapi/_augment_cli.yaml` (remove navmap operations)
5. **Review and potentially delete schema files**:
   - `schema/tools/docstring_builder_cli.json`
   - `schema/tools/docstring_cache.json`
   - `schema/tools/navmap_document.json`
6. **Review documentation/planning files** for references to deleted tooling

