# 14 - Offline packaging

The folder is complete: nothing is downloaded during setup or at run time. Copy it to the server and run
`setup.ps1` or `setup.sh`.

## 1. What the folder contains

| Part | Shipped as |
|---|---|
| Every Python package for **Python 3.13** on **Windows x64 and Linux x86-64** | `wheels/` (42 wheel files, about 80 MB): 12 direct packages and their dependencies |
| Code engine: codebase-memory-mcp 0.11.0, including its code-embedding model | `bin/codebase-memory-mcp-windows-amd64.zip`, `bin/codebase-memory-mcp-linux-amd64-portable.tar.gz`, `bin/SHA256SUMS` |
| Graph library for the UI | `brain/ui/vendor/force-graph.min.js` (MIT, v1.52.0) |
| *Optional:* local OCR for pictures and scanned pages, the fallback when the vision model is missing, slow or failing | `wheels/ocr/` (16 wheel files, about 150 MB; RapidOCR 1.2.3 with its models inside, ONNX Runtime, OpenCV headless) and `requirements-ocr.txt` |
| Not included: Python 3.13 and git | install them from the organisation's software distribution |

## 2. How the installation stays offline
- `wheels/` holds the Windows and Linux wheels side by side; pip picks the files that match the system.
- Setup runs `python -m pip install --no-index --find-links wheels -r requirements.txt`. `--no-index` makes pip
  use only the folder.
- When `wheels/ocr/` exists, setup also runs `pip install --no-index --no-deps --find-links wheels/ocr -r
  requirements-ocr.txt`. `--no-deps` keeps the main bundle's NumPy and Pillow; every OCR dependency is pinned in
  the file. If it fails, setup says so and continues: pictures are then described by the vision model only.
- Setup checks the SHA-256 of the code engine archive against `bin/SHA256SUMS` before unpacking it to
  `bin/windows/` or `bin/linux/`.
- At run time nothing is downloaded: no tokenizer or model files (the OCR models ship inside the RapidOCR wheel), no
  remote images from documents, and the UI loads no files from the internet.

## 3. Why only Python 3.13
One interpreter version means one tested set of packages, an 80 MB bundle (wheels for five versions would be five
times as much) and no preparation step on an internet machine. Setup looks for Python 3.13 (`-Python` / `--python`, then
`py -3.13`, `python3.13`, `python`, `python3`), stops with a clear message if it is missing, and recreates `.venv` if
it was built with another version. `brain.py` refuses to run on any other version. See
[ADR-011](decisions/ADR-011-python-version.md).

## 4. Making the folder smaller
For a single operating system, delete the other system's binary wheels: on Linux-only installations
`wheels/*win_amd64.whl`, on Windows-only installations `wheels/*manylinux*.whl`. Keep every `*-none-any.whl`. The
other system's code engine archive in `bin/` can go as well. Without OCR, delete `wheels/ocr/` (about 150 MB); the
system then works exactly as before, with the vision model as the only reader of pictures.

## 5. For maintainers: refreshing the bundle
Needed only when `requirements.txt` changes. On a machine with internet access:
```
pip download -r requirements.txt -d wheels --only-binary=:all: --python-version 3.13 --platform win_amd64
pip download -r requirements.txt -d wheels --only-binary=:all: --python-version 3.13 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64
```
For the OCR pack (when `requirements-ocr.txt` changes), the same two commands with `-r requirements-ocr.txt -d
wheels/ocr --no-deps`. RapidOCR stays at 1.2.3: later 1.x versions do not install on Python 3.13, and 3.x downloads
its models at run time.

Then run `tests/test_static.py`; it checks that the bundle contains only Python 3.13 wheels and that the OCR pack
has a wheel for every pin.

## 6. Updating the code engine
Download the new codebase-memory-mcp release archives on an internet machine, replace the two archives in `bin/`,
put the official checksums into `bin/SHA256SUMS`, delete `bin/windows/` and `bin/linux/`, and run setup.
