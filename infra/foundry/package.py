"""Create an allowlisted source bundle for Foundry; never copy credentials."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".artifacts/foundry-source"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    source = TARGET / "src"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    project = (
        (ROOT / "pyproject.toml")
        .read_text()
        .replace(
            'packages = ["src/retail_insight", "evaluation"]', 'packages = ["src/retail_insight"]'
        )
    )
    (TARGET / "pyproject.toml").write_text(project)
    (TARGET / "requirements.txt").write_text(
        ".\nlangchain-azure-ai[hosting]==1.4.1\nazure-identity>=1.25,<2\nazure-ai-contentsafety>=1.1.0b1\n"
    )
    print(f"Prepared {TARGET}; no credentials or evaluation references copied.")


if __name__ == "__main__":
    main()
