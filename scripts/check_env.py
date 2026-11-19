"""Environment verification and metadata helper for RakuTrans AI scripts."""

import ast
import hashlib
import importlib
import pathlib
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
REQUIRED_MODULES = (
    "customtkinter",
    "tkinterdnd2",
    "PIL",
    "openpyxl",
    "docx",
    "pptx",
    "pymupdf",
    "pypdf",
    "pdf2docx",
    "reportlab",
    "charset_normalizer",
)


def _req_sha256() -> str:
    req = ROOT_DIR / "requirements.txt"
    if not req.exists():
        return ""
    return hashlib.sha256(req.read_bytes()).hexdigest()


def check_venv() -> int:
    """Verify Python >= 3.10, core dependencies, and requirements.txt stamp."""
    if sys.version_info < (3, 10):
        return 1
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:
            return 1
    req = ROOT_DIR / "requirements.txt"
    stamp = ROOT_DIR / ".venv" / ".req_stamp"
    if req.exists():
        if not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != _req_sha256():
            return 1
    return 0


def write_stamp() -> int:
    """Record current requirements.txt SHA-256 hash into .venv/.req_stamp."""
    digest = _req_sha256()
    if digest:
        stamp = ROOT_DIR / ".venv" / ".req_stamp"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(digest, encoding="utf-8")
    return 0


def read_config_constant(name: str) -> str:
    """Read a top-level constant from rakutrans/core/config.py without importing third-party deps."""
    tree = ast.parse((ROOT_DIR / "rakutrans" / "core" / "config.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == name
                    and isinstance(node.value, ast.Constant)
                ):
                    return str(node.value.value)
    return ""


def main() -> int:
    args = sys.argv[1:]
    if args == ["--check-py"]:
        return 0 if sys.version_info >= (3, 10) else 1
    if args == ["--py-version"]:
        print(".".join(str(part) for part in sys.version_info[:3]))
        return 0
    if args == ["--write-stamp"]:
        return write_stamp()
    if len(args) == 2 and args[0] == "--meta":
        val = read_config_constant(args[1])
        if not val:
            return 1
        print(val)
        return 0
    return check_venv()


if __name__ == "__main__":
    sys.exit(main())
