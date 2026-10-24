"""Owns the chat bot for the Desktop app: its settings and database on disk, and an engine that
is started when a companion radio connects and stopped when it goes."""
import asyncio
import json
import time
from pathlib import Path

from . import config as C
from . import texts as T
from .db import Db
from .engine import Engine


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


class Runtime:
    def __init__(self, base_dir, now=time.time):
        self.dir = Path(base_dir) / "omit"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.now = now
        self.db = Db(str(self.dir / "omit.sqlite"))
        self.cfg = C.merge(C.DEFAULTS, _read(self.dir / "config.json", {}))
        self.texts = {k: list(v) for k, v in T.DEFAULT_TEXTS.items()}
        for k, v in _read(self.dir / "texts.json", {}).items():
            if k in self.texts and isinstance(v, list) and v:
                self.texts[k] = [str(x) for x in v]
        self.engine = None
        self.backend = None

    # ---- the radio comes and goes
    def attach(self, backend):
        self.detach()
        self.backend = backend
        self.engine = Engine(backend, self.cfg, self.db, self.texts, now=self.now)
        self.engine.preload(self.db.recent_messages(200))
        self.engine.tasks.append(asyncio.ensure_future(self.engine.start()))

    def detach(self):
        if self.engine is not None:
            self.engine.stop()
        self.engine, self.backend = None, None

    # ---- settings
    def settings(self):
        return {"config": self.cfg, "texts": self.texts, "defaults": {"config": C.DEFAULTS, "texts": T.DEFAULT_TEXTS}}

    def save_settings(self, config=None, texts=None):
        """Check, write and apply new settings. Returns a list of problems; empty means saved."""
        new_cfg = C.merge(self.cfg, config or {})
        problems = C.check(new_cfg)
        new_texts = dict(self.texts)
        for k, v in (texts or {}).items():
            if k not in new_texts:
                problems.append(f"texts.{k} is not a list the bot uses")
            elif not isinstance(v, list) or not [x for x in v if str(x).strip()]:
                problems.append(f"texts.{k} needs at least one line")
            else:
                new_texts[k] = [str(x).strip() for x in v if str(x).strip()]
        if problems:
            return problems
        self.cfg, self.texts = new_cfg, new_texts
        (self.dir / "config.json").write_text(json.dumps(self.cfg, indent=1), encoding="utf-8")
        (self.dir / "texts.json").write_text(json.dumps(self.texts, indent=1, ensure_ascii=False), encoding="utf-8")
        if self.backend is not None:                       # apply at once: a new engine with the same radio
            self.attach(self.backend)
        return []
