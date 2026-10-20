"""Role files that are appended to the analysis prompts."""

from pathlib import Path
import re

from . import config

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TITLE_RE = re.compile(r"^Позиция:\s*(.+)$", re.M)


class RoleRepository:
    """Role files prompts/roles/<name>.md added to the prompt as 'ИСХОДНАЯ РОЛЬ'."""

    def __init__(self, roles_dir: Path = config.ROLES_DIR):
        self.roles_dir = roles_dir

    def names(self) -> list[str]:
        if not self.roles_dir.is_dir():
            return []
        return sorted(f.stem for f in self.roles_dir.glob("*.md") if f.is_file())

    def _text(self, role: str) -> str:
        """HTML comments in the file are template help and are dropped."""
        return COMMENT_RE.sub("", (self.roles_dir / f"{role}.md").read_text(encoding="utf-8")).strip()

    def catalog(self) -> list[dict]:
        """Roles for the picker: id is the file name, title is the 'Позиция:' line, text is the full description."""
        items = []
        for name in self.names():
            text = self._text(name)
            match = TITLE_RE.search(text)
            items.append({"id": name, "title": match.group(1).strip() if match else name, "text": text})
        return items

    def prompt_block(self, role: str) -> str:
        if not role or role not in self.names():
            return ""
        text = self._text(role)
        return f"\n\n---\n\nИСХОДНАЯ РОЛЬ:\n\n{text}" if text else ""
