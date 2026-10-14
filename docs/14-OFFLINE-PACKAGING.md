# 14 - Offline packaging

The folder is complete: nothing is downloaded during setup or at run time. Copy it to the server and run
`setup.ps1` or `setup.sh`.

## 1. What the folder contains

| Part | Shipped as |
|---|---|
| Every Python package for **Python 3.13** on **Windows x64 and Linux x86-64** | `wheels/` (41 wheel files, about 80 MB): 11 direct packages and their dependencies |
| Code engine: codebase-memory-mcp 0.11.0, including its code-embedding model | `bin/codebase-memory-mcp-windows-amd64.zip`, `bin/codebase-memory-mcp-linux-amd64-portable.tar.gz`, `bin/SHA256SUMS` |
| Graph library for the UI | `brain/ui/vendor/force-graph.min.js` (MIT, v1.52.0) |
| Not included: Python 3.13 and git | install them from the organisation's software distribution |

## 2. How the installation stays offline
- `wheels/` holds the Windows and Linux wheels side by side; pip picks the files that match the system.
- Setup runs `python -m pip install --no-index --find-links wheels -r requirements.txt`. `--no-index` makes pip
  use only the folder.
- Setup checks the SHA-256 of the code engine archive against `bin/SHA256SUMS` before unpacking it to
  `bin/windows/` or `bin/linux/`.
- At run time nothing is downloaded: no tokenizer or model files, no remote images from documents, and the UI loads
  no files from the internet.

## 3. Why only Python 3.13
One interpreter version means one tested set of packages, an 80 MB bundle (wheels for five versions would be five
times as much) and no preparation step on an internet machine. Setup looks for Python 3.13 (`-Python` / `--python`, then
`py -3.13`, `python3.13`, `python`, `python3`), stops with a clear message if it is missing, and recreates `.venv` if
it was built with another version. `brain.py` refuses to run on any other version. See
[ADR-011](decisions/ADR-011-python-version.md).

## 4. Making the folder smaller
For a single operating system, delete the other system's binary wheels: on Linux-only installations
`wheels/*win_amd64.whl`, on Windows-only installations `wheels/*manylinux*.whl`. Keep every `*-none-any.whl`. The
other system's code engine archive in `bin/` can go as well.

## 5. For maintainers: refreshing the bundle
Needed only when `requirements.txt` changes. On a machine with internet access:
```
pip download -r requirements.txt -d wheels --only-binary=:all: --python-version 3.13 --platform win_amd64
pip download -r requirements.txt -d wheels --only-binary=:all: --python-version 3.13 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64
```
Then run `tests/test_static.py`; it checks that the bundle contains only Python 3.13 wheels.

## 6. Updating the code engine
Download the new codebase-memory-mcp release archives on an internet machine, replace the two archives in `bin/`,
put the official checksums into `bin/SHA256SUMS`, delete `bin/windows/` and `bin/linux/`, and run setup.
