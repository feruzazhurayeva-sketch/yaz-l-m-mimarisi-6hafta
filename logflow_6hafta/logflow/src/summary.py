from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class StageStats:
    """Aşama başına sayaçlar (8-9. haftalardaki ölçümlerin ham maddesi)."""
    name: str
    policy: str = "FAIL_FAST"
    received: int = 0       # aşamaya giren kayıt
    emitted: int = 0        # aşamadan çıkan kayıt
    filtered: int = 0       # hata olmadan, kural gereği elenen (filtre)
    skipped: int = 0        # SKIP politikasıyla atılan
    dead_lettered: int = 0  # DEAD_LETTER ile ikincil kanala giden
    retried: int = 0        # yapılan yeniden deneme sayısı (kayıt sayısı değil, deneme)
    failed: int = 0         # FAIL_FAST ile çalıştırmayı durduran

    @property
    def dropped(self) -> int:
        """Bu aşamada ana akıştan düşen toplam kayıt."""
        return self.filtered + self.skipped + self.dead_lettered + self.failed


@dataclass
class RunSummary:
    """
    Bir çalıştırmanın özeti. Sayaçlar yalnızca engine tarafından güncellenir;
    `to_dict()` makine tarafından okunabilir (ölçüm/benchmark) çıktı verir.
    """
    records_in: int = 0
    records_out: int = 0
    dead_letter_count: int = 0
    elapsed_seconds: float = 0.0
    status: str = "COMPLETED"        # COMPLETED | FAILED
    failure_reason: str = ""
    stages: List[StageStats] = field(default_factory=list)

    @property
    def total_dropped(self) -> int:
        return sum(s.dropped for s in self.stages)

    @property
    def is_balanced(self) -> bool:
        """giren = çıkan + (her aşamada düşen). Her aşama kayıt başına en fazla 1 çıktı verdiğinde geçerlidir."""
        return self.records_in == self.records_out + self.total_dropped

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["total_dropped"] = self.total_dropped
        d["balanced"] = self.is_balanced
        return d

    def format(self) -> str:
        w = max([len(s.name) for s in self.stages] + [5])
        lines = [
            "",
            "=" * 66,
            f" RUN SUMMARY  [{self.status}]",
            "=" * 66,
            f" Gelen kayıt          : {self.records_in}",
            f" Çıkan kayıt          : {self.records_out}",
            f" Dead-letter kanalı   : {self.dead_letter_count}",
            f" Gerçek geçen süre    : {self.elapsed_seconds:.3f} sn",
            "-" * 66,
            f" {'Aşama'.ljust(w)}  {'politika':<12}{'giren':>7}{'çıkan':>7}{'elenen':>7}{'skip':>6}{'DLQ':>6}",
        ]
        for s in self.stages:
            lines.append(
                f" {s.name.ljust(w)}  {s.policy:<12}{s.received:>7}{s.emitted:>7}"
                f"{s.filtered:>7}{s.skipped:>6}{s.dead_lettered:>6}"
            )
        lines.append("-" * 66)
        lines.append(
            f" Muhasebe: {self.records_in} = {self.records_out} (çıkan) + {self.total_dropped} (düşen)"
            f"  -> {'DENGELİ ✓' if self.is_balanced else 'DENGESİZ ✗'}"
        )
        if self.failure_reason:
            lines.append(f" Durma nedeni: {self.failure_reason}")
        lines.append("=" * 66)
        return "\n".join(lines)
