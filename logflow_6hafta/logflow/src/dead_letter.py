import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from interfaces import Sink, PipelineException


@dataclass(frozen=True)
class FailedRecord:
    """
    Dead-letter kanalının taşıdığı birim.

    raw_input  : hatalı kaydın ham girdisi (rawInput)
    stage_name : hatanın oluştuğu aşama (stageName)
    exception  : fırlatılan istisna
    timestamp  : hatanın oluştuğu an (UTC)
    context    : tanılama bağlamı (satır numarası, deneme sayısı, istisna türü...)
    """
    raw_input: str
    stage_name: str
    exception: Exception
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)


class DeadLetterFileSink(Sink[FailedRecord]):
    """
    FailedRecord'ları JSON Lines (bir satır = bir JSON nesnesi) olarak yazan hedef.
    Çok uzun ham girdiler `max_raw_length` karakterde kesilir (tam uzunluk `raw_length` alanındadır).
    UTF-8 olmayan baytlar dosyayı bozmadan okunabilir "\\udcXX" metni olarak kaydedilir.
    """

    def __init__(self, path: str, max_raw_length: int = 500):
        self.path = path
        self.max_raw_length = max_raw_length
        self._file: Optional[Any] = None

    def open(self) -> None:
        try:
            self._file = open(self.path, "w", encoding="utf-8")
        except OSError as e:
            raise PipelineException(f"Dead-letter dosyası açılamadı ({self.path}): {e}")

    def consume(self, item: FailedRecord) -> None:
        if self._file is None:
            raise PipelineException("DeadLetterFileSink açık değil! open() çağrılmadı.")
        raw = item.raw_input
        entry = {
            "timestamp": item.timestamp.isoformat(),
            "stage": item.stage_name,
            "exception_type": type(item.exception).__name__,
            "message": str(item.exception),
            "raw_length": len(raw),
            "raw_truncated": len(raw) > self.max_raw_length,
            "raw": raw[: self.max_raw_length],
        }
        entry.update(item.context)
        try:
            text = json.dumps(entry, ensure_ascii=False)
            # UTF-8 olmayan baytlar (surrogate) okunabilir "\\udcXX" metnine çevrilir; dosya geçerli UTF-8 kalır.
            text = text.encode("utf-8", "backslashreplace").decode("utf-8")
            self._file.write(text + "\n")
        except OSError as e:
            raise PipelineException(f"Dead-letter dosyasına yazılamadı ({self.path}): {e}")

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
            finally:
                self._file.close()
                self._file = None


class DeadLetterChannel:
    """
    Ana akıştan BAĞIMSIZ ikincil çıktı yolu (ayrı bir boru hattı):

        [hatalı kayıt] -> DeadLetterChannel -> DeadLetterSink

    Ana hattın aşamalarını/hedefini bilmez; yalnızca FailedRecord alır. Kendi yaşam
    döngüsü ve sayacı vardır. Yazma hatası PipelineException'dır (kanal güvenilmezse
    kayıt kaybı sessizce olmasın diye çalıştırma durur).
    """

    def __init__(self, sink: Sink[FailedRecord]):
        self.sink = sink
        self.count = 0

    def open(self) -> None:
        if hasattr(self.sink, "open"):
            self.sink.open()

    def send(self, failed: FailedRecord) -> None:
        self.sink.consume(failed)
        self.count += 1

    def close(self) -> None:
        if hasattr(self.sink, "close"):
            self.sink.close()
