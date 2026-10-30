"""Local HTTPS cert helper: script is runnable, artifacts stay untracked."""
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "generate_https_certs.sh"


def test_cert_script_is_executable_and_parses():
    assert SCRIPT.is_file()
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, f"{SCRIPT} is not executable"
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_gitignore_covers_generated_certs():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "cert.pem" in text
    assert "key.pem" in text
    assert "*.pem" in text
