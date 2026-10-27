import re
from datetime import datetime
from interfaces import Stage, Emitter, StageException
from record import LogRecord


class ParserStage(Stage[str, LogRecord]):
    """
    Ham log satırlarını LogRecord'a dönüştüren aşama.

    Artık hatalı satırı sessizce atlamaz: her ayrıştırma hatası bir StageException
    olarak yükseltilir; kaydın akıbetini aşamanın hata politikası (on_error) belirler.
    """

    # Common Log Format (CLF) + opsiyonel User Agent deseni.
    # bytes alanı '-', sayı veya (doğrulama aşamasında yakalanmak üzere) negatif sayı olabilir.
    CLF_REGEX = re.compile(
        r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"([A-Z]+)\s+(\S+)\s+HTTP/[^"]+"\s+(\d{3})\s+(-?\d+|-)(?:\s+"([^"]*)")?'
    )
    DEFAULT_MAX_LINE_LENGTH = 8192

    def __init__(self, max_line_length: int = DEFAULT_MAX_LINE_LENGTH):
        self.max_line_length = max_line_length

    def process(self, input_item: str, out: Emitter[LogRecord]) -> None:
        if len(input_item) > self.max_line_length:
            raise StageException(
                f"Satır çok uzun: {len(input_item)} karakter (sınır {self.max_line_length})"
            )

        try:
            input_item.encode("utf-8")
        except UnicodeEncodeError:
            raise StageException("Satır geçerli UTF-8 değil (çözülemeyen bayt içeriyor)")

        line = input_item.strip()
        if not line:
            raise StageException("Boş satır")

        match = self.CLF_REGEX.match(line)
        if not match:
            raise StageException("Satır Common Log Format desenine uymuyor (eksik/kesik alan)")

        client_ip, raw_time, method, path, raw_status, raw_bytes, user_agent = match.groups()

        try:
            timestamp = datetime.strptime(raw_time, "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            raise StageException(f"Geçersiz zaman damgası: '{raw_time}'")

        out.emit(LogRecord(
            timestamp=timestamp,
            client_ip=client_ip,
            method=method,
            path=path,
            status=int(raw_status),
            bytes=0 if raw_bytes == "-" else int(raw_bytes),
            user_agent=user_agent if user_agent else "-",
            raw=input_item,
        ))
