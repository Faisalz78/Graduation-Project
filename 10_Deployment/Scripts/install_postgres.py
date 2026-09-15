"""Install pinned, portable PostgreSQL binaries inside this project only."""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".local" / "tools"
URL = "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260491"
SHA256 = "4b8db0930c38f6ef845db919551dedda3b6b845aeb0927b3d79a6e8e9e4537cf"


def main():
    if (TOOLS / "pgsql/bin/pg_ctl.exe").is_file():
        print("Project PostgreSQL binaries are already installed.")
        return
    TOOLS.mkdir(parents=True, exist_ok=True)
    archive = TOOLS / "postgresql.zip"
    if not archive.exists():
        print("Downloading PostgreSQL 17.11 from EDB. This may take a few minutes.", flush=True)
        partial = TOOLS / "postgresql.zip.part"
        with urllib.request.urlopen(URL, timeout=120) as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target)
        partial.replace(archive)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != SHA256:
        raise RuntimeError("PostgreSQL archive checksum mismatch. No binaries were extracted.")
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            if not entry.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                continue
            target = (TOOLS / entry.filename).resolve()
            if not target.is_relative_to(TOOLS.resolve()):
                raise RuntimeError("Invalid archive path.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    print("Portable PostgreSQL 17.11 installed in .local/tools/pgsql.")


if __name__ == "__main__":
    main()
