#!/usr/bin/env python3
"""Package a source allowlist; never include challenge data, predictions or caches."""
import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "START_HERE.md", "WRITEUP.md", "INTERVIEW_NOTES.md", ".gitignore", ".env.example",
              "INTERVIEW_PREP.md", "EVALUATION.md", "MODEL_SELECTION.md", "SUBMISSION.md", "PROGRESS.md",
              "requirements.txt", "run.sh", "solution.py", "llm.py", "schema.json", "check.py"}
REPORT_FILES = {"dev-offline.json", "dev-model.json", "model-status.json", "VALIDATION.md", "recovery-verification.json", "starter-baseline.json",
                "free-model-research.json", "free-model-probe.json", "final-verification.json"}


def selected_files():
    selected = [ROOT / name for name in sorted(ROOT_FILES)]
    for directory in ("coldstart", "tests", "scripts"):
        selected.extend(sorted(p for p in (ROOT / directory).rglob("*.py") if "__pycache__" not in p.parts))
    selected.extend(sorted((ROOT / "ai-logs").glob("*.md")))
    selected.extend(sorted((ROOT / "ai-logs").glob("*.txt")))
    for name in sorted(REPORT_FILES):
        path = ROOT / "reports" / name
        if path.exists():
            if name.startswith("dev-"):
                data = json.loads(path.read_text())
                if "score_points" not in data or "loop_diagnostics" not in data or "open_loops" in data or "people" in data:
                    raise ValueError("Refusing a report that does not look like aggregate evaluation metrics")
            selected.append(path)
    for path in selected:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or unsafe source file: " + str(path.relative_to(ROOT)))
    return selected


def package(destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = selected_files()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = "xpert-cold-start/" + path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            if path.name == "run.sh":
                info.external_attr = (0o100755 << 16)
            archive.writestr(info, path.read_bytes())
    print("Created %s (%d source/documentation files)" % (destination.name, len(files)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", default="xpert-cold-start-submission.zip")
    package(parser.parse_args().destination)
