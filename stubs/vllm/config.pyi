class PoolerConfig:
    pooling_type: str | None
    normalize: bool

    def __init__(
        self,
        *,
        pooling_type: str | None = ...,
        normalize: bool = ...,
    ) -> None: ...

__all__ = ["PoolerConfig"]
