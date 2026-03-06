class GhostLogger:
    """A no-op logger that silently discards all log messages."""

    @staticmethod
    def info(*args, **kwargs) -> None:
        pass

    @staticmethod
    def error(*args, **kwargs) -> None:
        pass
