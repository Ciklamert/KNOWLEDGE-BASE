# ADR-011 - Python 3.13 only

**Status:** accepted · **Requirements:** R2, R1

## Decision
AI-BRAIN runs on **CPython 3.13** and nothing else. `wheels/` contains every package for 3.13 on Windows and Linux,
setup accepts only a 3.13 interpreter (and rebuilds `.venv` if it was made with another version), and `brain.py`
refuses to start on any other version with a clear message.

## Why
The installation must work without internet. Supporting every version from 3.10 up would mean shipping five times the
wheels (one set per version), or a separate preparation step on an internet machine before each installation. One version
gives one tested package set, an 80 MB bundle and no preparation step. 3.13 is a current, stable release for which
every dependency publishes wheels.

## Alternatives
| Option | Why not |
|---|---|
| any version from 3.10, all wheels bundled | five times the wheels, five versions to test |
| any version from 3.10, wheels prepared per site | needs an internet machine and an extra step before every installation |

## Consequences
Servers need Python 3.13 (the python.org installer on Windows, `python3.13` and `python3.13-venv` on Linux). Moving to
a newer Python means refreshing `wheels/` once ([14-OFFLINE-PACKAGING.md](../14-OFFLINE-PACKAGING.md)) and changing
the version check in `brain/settings.py` (`PYTHON`), `brain.py`, `setup.ps1` and `setup.sh`.
