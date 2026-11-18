"""Parsing of GAMMA's definition files (modpack_maker_list.txt and the MO2 modlist.txt)."""

import re
from dataclasses import dataclass, field


@dataclass
class MakerEntry:
    line: int
    url: str
    directives: list      # sub-folders of the archive to install; empty = auto
    author: str
    title: str
    info_url: str
    extras: list = field(default_factory=list)   # [filename, md5] for some GitHub entries
    name: str = ""        # mod folder name, resolved against modlist.txt

    @property
    def guess(self) -> str:
        return f" {self.title} - {self.author}"

    @property
    def md5(self):
        return next((x.lower() for x in self.extras if re.fullmatch(r"[0-9a-fA-F]{32}", x)), None)


def parse_maker_list(text: str) -> list:
    """Each line: url <TAB> directives <TAB> ' - author' <TAB> ' title' [<TAB> info url [<TAB> extras]].
    Lines with a single field are separators and are skipped here."""
    entries = []
    for i, raw in enumerate(text.splitlines(), 1):
        f = raw.rstrip("\r\n").split("\t")
        if len(f) < 4 or not f[0].strip():
            continue
        directives = [] if f[1].strip() == "0" else [
            d.replace("\\", "/").strip("/") for d in f[1].split(":") if d.strip()
        ]
        extras = [x for chunk in f[5:] for x in chunk.split()]
        entries.append(MakerEntry(
            line=i, url=f[0].strip(), directives=directives,
            author=f[2].strip().lstrip("-").strip(), title=f[3].strip(),
            info_url=f[4].strip() if len(f) > 4 else "", extras=extras,
        ))
    return entries


def parse_modlist(text: str) -> list:
    """[(state, name)] in file order ('+' enabled, '-' disabled). First line = highest priority."""
    result = []
    for raw in text.splitlines():
        if raw[:1] in "+-" and raw[1:].strip():
            result.append((raw[0], raw[1:].strip()))
    return result


def match_entries(modlist_names: list, entries: list) -> dict:
    """Map modlist folder names to maker entries.

    GAMMA names folders '<line>- <title> - <author>' but the modlist does not always
    follow that exactly, so first match on ' title - author', then on title only
    (same approach as the long-standing community launcher)."""
    pending = list(entries)
    matched = {}
    for key in ("guess", "title"):
        for name in modlist_names:
            if name in matched:
                continue
            for e in pending:
                if getattr(e, key) in name:
                    e.name = name
                    matched[name] = e
                    pending.remove(e)
                    break
    return matched, pending
