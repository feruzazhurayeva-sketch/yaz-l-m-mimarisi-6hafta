import re
from dataclasses import dataclass
from enum import Enum
from typing import Union

from interfaces import ConfigurationError


class PolicyKind(Enum):
    FAIL_FAST = "FAIL_FAST"      # çalıştırmayı durdur
    SKIP = "SKIP"                # kaydı at, sayısını tut
    DEAD_LETTER = "DEAD_LETTER"  # kaydı tanılama bağlamıyla ikincil kanala yönlendir
    RETRY = "RETRY"              # n kez yeniden dene; tükenirse `fallback` uygulanır


@dataclass(frozen=True)
class ErrorPolicy:
    """
    Aşama başına hata politikası. Yapılandırmada `on_error:` ile seçilir:
        FAIL_FAST | SKIP | DEAD_LETTER | RETRY(3)
    RETRY için `fallback` (varsayılan DEAD_LETTER) deneme hakkı bitince uygulanır.
    """
    kind: PolicyKind
    retries: int = 0
    retry_delay_s: float = 0.0
    fallback: PolicyKind = PolicyKind.DEAD_LETTER

    _RETRY_RE = re.compile(r"^RETRY\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)

    @classmethod
    def fail_fast(cls) -> "ErrorPolicy":
        return cls(PolicyKind.FAIL_FAST)

    @classmethod
    def skip(cls) -> "ErrorPolicy":
        return cls(PolicyKind.SKIP)

    @classmethod
    def dead_letter(cls) -> "ErrorPolicy":
        return cls(PolicyKind.DEAD_LETTER)

    @classmethod
    def retry(cls, n: int, delay_s: float = 0.0,
              fallback: PolicyKind = PolicyKind.DEAD_LETTER) -> "ErrorPolicy":
        if n < 1:
            raise ConfigurationError("RETRY(n) için n en az 1 olmalıdır.")
        if fallback == PolicyKind.RETRY:
            raise ConfigurationError("RETRY için 'retry_fallback' RETRY olamaz.")
        return cls(PolicyKind.RETRY, retries=n, retry_delay_s=delay_s, fallback=fallback)

    @classmethod
    def parse(cls, text: Union[str, "ErrorPolicy"], delay_s: float = 0.0,
              fallback: str = "DEAD_LETTER") -> "ErrorPolicy":
        if isinstance(text, ErrorPolicy):
            return text
        if not isinstance(text, str):
            raise ConfigurationError(f"'on_error' metin olmalıdır, alınan: {text!r}")
        t = text.strip()
        m = cls._RETRY_RE.match(t)
        if m:
            try:
                fb = PolicyKind(str(fallback).upper())
            except ValueError:
                raise ConfigurationError(f"Geçersiz 'retry_fallback': '{fallback}'.")
            return cls.retry(int(m.group(1)), delay_s, fb)
        try:
            kind = PolicyKind(t.upper())
        except ValueError:
            raise ConfigurationError(
                f"Geçersiz hata politikası: '{text}'. Geçerli: FAIL_FAST, SKIP, DEAD_LETTER, RETRY(n)."
            )
        if kind == PolicyKind.RETRY:
            raise ConfigurationError("RETRY, deneme sayısıyla yazılmalıdır: RETRY(n).")
        return cls(kind)

    @property
    def uses_dead_letter(self) -> bool:
        return self.kind == PolicyKind.DEAD_LETTER or (
            self.kind == PolicyKind.RETRY and self.fallback == PolicyKind.DEAD_LETTER)

    def __str__(self) -> str:
        return f"RETRY({self.retries})" if self.kind == PolicyKind.RETRY else self.kind.value
