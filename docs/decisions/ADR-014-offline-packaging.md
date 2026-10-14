# ADR-014 - Offline packaging: everything inside the folder

**Status:** accepted · **Requirements:** R1, R2, R26

## Decision
- **Python packages**: all wheels for Python 3.13 on Windows x64 and Linux x86-64 ship in `wheels/` (41 files,
  about 80 MB). Setup always installs with `pip --no-index --find-links wheels`, so it never uses a network. There is
  no preparation step.
- **Code engine**: the Windows and Linux archives ship in `bin/` with `SHA256SUMS`; setup verifies and unpacks them.
- **No downloads at run time**: no tokenizer or model files are fetched, remote images in documents are never
  downloaded, and the UI has no CDN
  dependencies.
- **Executable scripts** do every step: `setup.ps1`, `setup.sh`, `brain.cmd`, `brain.sh`, `brain.py`.

## Alternatives
| Option | Why not |
|---|---|
| a per-site preparation step on an internet machine | an extra step and an internet machine for every installation |
| wheels for every Python version | five times the size (see ADR-011) |
| a pre-built virtual environment | tied to one operating system, one Python build and one install path |
| Docker images | often not available on corporate Windows servers |

## Consequences
Copy the folder, run setup, done. Refreshing the bundle is a maintainer task, needed only when `requirements.txt`
changes ([14-OFFLINE-PACKAGING.md](../14-OFFLINE-PACKAGING.md)).
