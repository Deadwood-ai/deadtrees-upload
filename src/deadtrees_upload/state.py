"""Private atomic writes shared by credentials and upload receipts."""
import json
import os
import tempfile
from pathlib import Path


def atomic_json(path: Path, payload: dict):
    """Write privately before publishing; failures must stop uploads."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

