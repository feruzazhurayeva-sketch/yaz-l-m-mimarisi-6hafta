from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

@dataclass(frozen=True)
class LogRecord:
    """Boru hattı boyunca taşınan değişmez (immutable) alan modeli."""
    timestamp: datetime
    client_ip: str
    method: str
    path: str
    status: int
    bytes: int
    user_agent: str
    attributes: Dict[str, str] = field(default_factory=dict)  # 5-7. haftalar için genişleme noktası
    raw: str = ""

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{time_str}] {self.client_ip} -> {self.method} {self.path} ({self.status}) - {self.bytes}B - UA: '{self.user_agent}'"