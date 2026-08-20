from __future__ import annotations

from importlib.resources import files


def index_html() -> str:
    return files(__package__).joinpath("static/index.html").read_text(encoding="utf-8")
