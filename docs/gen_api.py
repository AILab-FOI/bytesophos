# docs/gen_api.py

from pathlib import Path
import sys
import importlib.util
import mkdocs_gen_files

PKG_DIR = Path("backend/pipeline/app")
IMPORT_PREFIX = "backend.pipeline.app"

if "." not in sys.path:
    sys.path.insert(0, ".")

def importable(dotted: str) -> bool:
    return importlib.util.find_spec(dotted) is not None

nav = mkdocs_gen_files.Nav()

for path in sorted(PKG_DIR.rglob("*.py")):
    if path.name == "__init__.py":
        continue

    import_path = IMPORT_PREFIX + "." + path.with_suffix("").relative_to(PKG_DIR).as_posix().replace("/", ".")
    if not importable(import_path):
        continue

    doc_path = Path("reference", *path.relative_to(PKG_DIR).with_suffix(".md").parts)
    nav_path = doc_path.with_suffix("").parts

    with mkdocs_gen_files.open(doc_path, "w") as f:
        print(f"# `{import_path}`\n", file=f)
        print(f"::: {import_path}", file=f)
        print("    options:", file=f)
        print("      members: true", file=f)
        print("      show_source: true", file=f)
        print("      show_if_no_docstring: true", file=f)
        print("      members_order: source", file=f)
        print('      filters:', file=f)
        print('        - \"!^_\"', file=f)

    mkdocs_gen_files.set_edit_path(doc_path, path)

    nav[nav_path[1:]] = doc_path

lines = list(nav.build_literate_nav())
relative = [line.replace("](reference/", "](") for line in lines]
with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as f:
    f.writelines(relative)