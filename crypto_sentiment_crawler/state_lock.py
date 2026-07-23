"""Advisory lock for the orchestrator state file."""

import fcntl
from pathlib import Path


class StateFileLock:
    """Keep legacy state writers from racing the running orchestrator."""

    def __init__(self, state_path: Path):
        self.path = state_path.with_name(f".{state_path.name}.lock")
        self._handle = None

    @property
    def is_held(self) -> bool:
        """Whether this instance currently owns the advisory lock."""
        return self._handle is not None

    def acquire(self, *, blocking: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(self._handle.fileno(), flags)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(
                f"State is owned by a running orchestrator: {self.path}"
            ) from exc

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
