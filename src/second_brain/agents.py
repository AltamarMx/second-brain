"""``sb agents sync``: copy the agent rules, skills and Claude Code settings into a library.

- ``AGENTS.md``: only the block between the ``sb:begin``/``sb:end`` markers is
  replaced; anything the user writes outside it is kept.
- ``CLAUDE.md``: created if missing (it imports ``AGENTS.md``).
- ``.claude/skills/sb-*``: overwritten; the user's own skills are not touched.
- ``.claude/settings.json``: our permissions and hook are merged in.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

BEGIN = "<!-- sb:begin (generado por sb agents sync; no editar dentro de este bloque) -->"
END = "<!-- sb:end -->"
SKILLS = ("sb-ingerir", "sb-consultar", "sb-proyectos", "sb-bibtex")


def _template(name: str) -> str:
    return files("second_brain.templates").joinpath("agents", name).read_text(encoding="utf-8")


def _write_if_changed(path: Path, text: str, changed: list[Path]) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    changed.append(path)


def _agents_md(existing: str | None) -> str:
    block = f"{BEGIN}\n{_template('AGENTS.md').strip()}\n{END}\n"
    if not existing:
        return block
    if BEGIN in existing and END in existing:
        before, rest = existing.split(BEGIN, 1)
        after = rest.split(END, 1)[1]
        return before + block.rstrip("\n") + after
    return block + "\n" + existing  # user content without markers goes after our block


def _merge_settings(existing: dict) -> dict:
    ours = json.loads(_template("settings.json"))
    merged = dict(existing)
    permissions = dict(merged.get("permissions", {}))
    for key in ("allow", "deny"):
        current = list(permissions.get(key, []))
        current += [rule for rule in ours["permissions"][key] if rule not in current]
        permissions[key] = current
    merged["permissions"] = permissions
    hooks = dict(merged.get("hooks", {}))
    session = list(hooks.get("SessionStart", []))
    our_hook = ours["hooks"]["SessionStart"][0]
    commands = {h.get("command") for group in session for h in group.get("hooks", [])}
    if our_hook["hooks"][0]["command"] not in commands:
        session.append(our_hook)
    hooks["SessionStart"] = session
    merged["hooks"] = hooks
    return merged


def sync_agents(home: Path) -> list[Path]:
    changed: list[Path] = []
    agents = home / "AGENTS.md"
    existing = agents.read_text(encoding="utf-8") if agents.exists() else None
    _write_if_changed(agents, _agents_md(existing), changed)
    claude = home / "CLAUDE.md"
    if not claude.exists():
        _write_if_changed(claude, _template("CLAUDE.md"), changed)
    for skill in SKILLS:
        _write_if_changed(
            home / ".claude" / "skills" / skill / "SKILL.md",
            _template(f"skills/{skill}/SKILL.md"),
            changed,
        )
    opencode = home / "opencode.json"
    current_oc = json.loads(opencode.read_text(encoding="utf-8")) if opencode.exists() else {}
    ours_oc = json.loads(_template("opencode/opencode.json"))
    merged_oc = {**ours_oc, **current_oc}
    for key in ("provider", "mcp"):  # keep the user's entries, refresh ours
        merged_oc[key] = {**current_oc.get(key, {}), **ours_oc[key]}
    _write_if_changed(opencode, json.dumps(merged_oc, indent=2, ensure_ascii=False) + "\n", changed)
    _write_if_changed(
        home / ".opencode" / "agents" / "bibliotecario.md",
        _template("opencode/bibliotecario.md"),
        changed,
    )
    settings = home / ".claude" / "settings.json"
    current = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    _write_if_changed(
        settings, json.dumps(_merge_settings(current), indent=2, ensure_ascii=False) + "\n", changed
    )
    return changed
