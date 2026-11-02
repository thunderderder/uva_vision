from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "D:\\\\AI\\\\",
    "D:\\\\code_project",
    "C:\\\\Users\\\\",
    "/Users/",
    "adhoc_jobs/uva",
    "adhoc_jobs/uva_pra",
    "adhoc_jobs/agent-qa",
    "op://",
    "cnsoft.cc",
    "zhjtcloud",
    "feiliu-tech.com",
    "context_deploy",
    "罗田",
    "sk-",
    "飞流茜坑",
    "thunderder",
)


def _scan_paths():
    patterns = [
        "*.md",
        "docs/**/*.md",
        "src/**/*.py",
        "src/**/*.html",
        "config/*.yaml",
        ".env.example",
        "run_pra.ps1",
        "run_uva.ps1",
        "pyproject.toml",
    ]
    out: list[Path] = []
    for pat in patterns:
        out.extend(ROOT.glob(pat))
    return sorted(set(out))


def test_publishable_tree_has_no_secrets_or_private_paths():
    hits = []
    for path in _scan_paths():
        if not path.is_file():
            continue
        if path.name == "pra_runtime.yaml":
            continue
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token}")
    assert hits == []
