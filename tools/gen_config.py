"""Generate .env.example and docs/03-CONFIGURATION.md from the ONE settings schema (brain/settings.py).

Run after adding or changing a setting:   python tools/gen_config.py
tests/test_static.py fails if the generated files are out of date, so nothing can go undocumented.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brain import settings as cfg  # noqa: E402

REQUIRED = {"BRAIN_UI_PASSWORD", "BRAIN_LLM_BASE_URL", "BRAIN_LLM_API_KEY", "BRAIN_LLM_MODEL", "BRAIN_EMBEDDING_MODEL",
            "BRAIN_EMBEDDING_DIM"}
EXAMPLES = {"BRAIN_LLM_BASE_URL": "https://llm-gateway.corp.local/v1", "BRAIN_LLM_MODEL": "corporate-chat-model",
            "BRAIN_EMBEDDING_MODEL": "bge-m3"}


def groups():
    out: dict[str, list] = {}
    for s in cfg.SCHEMA:
        out.setdefault(s.group, []).append(s)
    return out


def env_example() -> str:
    lines = ["# ==========================================================================================",
             "#  AI-BRAIN configuration. Copy to .env (setup does this) and fill in the REQUIRED values.",
             "#  Every value can also be changed later in the web UI (Settings), which edits this same file.",
             "#  Generated from brain/settings.py by tools/gen_config.py - all settings are listed here.",
             "#  Raw code-engine variables: CBM__<NAME>=value is passed to codebase-memory-mcp as <NAME>=value.",
             "# =========================================================================================="]
    for group, items in groups().items():
        lines += ["", f"# ---- {group} " + "-" * (86 - len(group))]
        for s in items:
            extra = f" One of: {', '.join(s.choices)}." if s.choices else ""
            need = "REQUIRED. " if s.key in REQUIRED else ""
            example = f" Example: {EXAMPLES[s.key]}" if s.key in EXAMPLES else ""
            lines.append(f"# {need}{s.help}{extra}{example}")
            lines.append(f"{s.key}={s.default}")
    return "\n".join(lines) + "\n"


def config_md() -> str:
    out = ["# 03 - Configuration reference", "",
           "> Generated from `brain/settings.py` by `python tools/gen_config.py`. Do not edit by hand.", "",
           "## Where values come from", "",
           "1. **The configuration file** `.env` in the install folder (another file: set the environment variable "
           "`BRAIN_CONFIG_FILE=/path/brain.env`). The web UI *Settings* page edits this same file in place.",
           "2. **Process environment variables** - used only for keys that are *not* in the file.",
           "3. **Defaults** listed below.", "",
           "Repositories and repository sets live in `repos.json` (another file: `BRAIN_REPOS_FILE`). "
           "See [04-REPOSITORIES-AND-SETS.md](04-REPOSITORIES-AND-SETS.md).", "",
           "**Restart column:** *live* = applied on the next request; *docs*/*code* = that engine restarts "
           "automatically when you save in the UI (from the CLI: restart the server); *server* = restart "
           "`brain serve` yourself.", "",
           "**Pass-through:** any `CBM__NAME=value` line is passed to codebase-memory-mcp as `NAME=value`, so every "
           "code-engine variable is adjustable without code changes. The document engine is part of this server; "
           "its settings are in the Document graph group.", ""]
    for group, items in groups().items():
        out += [f"## {group}", "", "| Key | Default | Restart | Meaning |", "|---|---|---|---|"]
        for s in items:
            d = f"`{s.default}`" if s.default else "(empty)"
            req = "**required** " if s.key in REQUIRED else ""
            ch = f" One of: {', '.join(f'`{c}`' for c in s.choices)}." if s.choices else ""
            sec = " Secret: never shown by the UI." if s.kind == "secret" else ""
            out.append(f"| `{s.key}` | {d} | {s.restart or 'live'} | {req}{s.help}{ch}{sec} |")
        out.append("")
    return "\n".join(out)


def main(check: bool = False) -> int:
    targets = {ROOT / ".env.example": env_example(), ROOT / "docs" / "03-CONFIGURATION.md": config_md()}
    stale = [p for p, text in targets.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)} (run python tools/gen_config.py)")
        return len(stale)
    for p, text in targets.items():
        p.parent.mkdir(exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
