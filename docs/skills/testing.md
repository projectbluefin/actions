# Testing guidance

## Testing script entrypoints

When a Python module exposes a `__main__` guard, exercise it from pytest by
running the file with `runpy.run_path(..., run_name="__main__")`.

Prefer a small helper that temporarily swaps `sys.argv` and `cwd`:

```python
import os
import runpy
import sys
from pathlib import Path

import pytest


def run_as_main(script_path: Path, *args: str) -> int | None:
    original_argv = sys.argv[:]
    original_cwd = Path.cwd()
    try:
        sys.argv = [str(script_path), *args]
        os.chdir(script_path.parent)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(script_path), run_name="__main__")
        return excinfo.value.code
    finally:
        sys.argv = original_argv
        os.chdir(original_cwd)
```

This covers the real CLI entrypoint path without needing a full subprocess.
