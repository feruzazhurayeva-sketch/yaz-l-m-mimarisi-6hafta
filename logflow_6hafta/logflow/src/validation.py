import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from interfaces import Stage, Emitter, StageException, ConfigurationError
from record import LogRecord

_UTC = timezone.utc
_NOW_TOLERANCE = timedelta(days=1)  # saat farkı/saat dilimi toleransı


def _parse_bound(value: Any, label: str) -> Union[datetime, str]:
    """Zaman sınırı: ISO-8601 metni ya da 'now'. Saat dilimi yoksa UTC varsayılır."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip().lower() == "now":
        return "now"
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ConfigurationError(f"Doğrulama: '{label}' geçerli bir ISO tarih ya da 'now' olmalıdır: {value!r}")
    else:
        # YAML, 2000-01-01 gibi değerleri date olarak okuyabilir
        try:
            dt = datetime(value.year, value.month, value.day)
        except AttributeError:
            raise ConfigurationError(f"Doğrulama: '{label}' geçerli bir tarih olmalıdır: {value!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=_UTC)


class ValidationStage(Stage[LogRecord, LogRecord]):
    """
    Bildirimsel kurallarla LogRecord doğrulayan aşama (yapılandırmadan sürülür).

    Kurallar (hepsi isteğe bağlı):
      required_fields : [alan, ...]            boş/None olmamalı
      ranges          : {alan: {min:, max:}}   sayısal aralık
      timestamp       : {min:, max:}           ISO tarih ya da 'now' (zaman damgası tutarlılığı)
      ip_format       : true                   client_ip geçerli IPv4/IPv6 olmalı
      allowed_methods : [GET, POST, ...]

    Tüm ihlaller tek bir StageException'da toplanır; kaydın akıbetini aşamanın
    hata politikası belirler (varsayılan: yapılandırmada seçilen on_error).
    """

    KNOWN_RULES = {"required_fields", "ranges", "timestamp", "ip_format", "allowed_methods"}

    def __init__(self, required_fields: Optional[List[str]] = None,
                 ranges: Optional[Dict[str, Dict[str, float]]] = None,
                 timestamp: Optional[Dict[str, Any]] = None,
                 ip_format: bool = False,
                 allowed_methods: Optional[List[str]] = None):
        self.required_fields = list(required_fields or [])
        self.ranges = dict(ranges or {})
        ts = timestamp or {}
        self.ts_min = _parse_bound(ts["min"], "timestamp.min") if "min" in ts else None
        self.ts_max = _parse_bound(ts["max"], "timestamp.max") if "max" in ts else None
        self.ip_format = ip_format
        self.allowed_methods = [m.upper() for m in (allowed_methods or [])]

    @classmethod
    def from_config(cls, params: Dict[str, Any]) -> "ValidationStage":
        """Parametreleri doğrular (hatalıysa ConfigurationError) ve aşamayı üretir."""
        unknown = set(params) - cls.KNOWN_RULES
        if unknown:
            raise ConfigurationError(
                f"Doğrulama aşamasında bilinmeyen kural(lar): {sorted(unknown)}. Geçerli: {sorted(cls.KNOWN_RULES)}"
            )
        rf = params.get("required_fields", [])
        if not isinstance(rf, list) or not all(isinstance(x, str) for x in rf):
            raise ConfigurationError("Doğrulama 'required_fields' metin listesi olmalıdır.")
        ranges = params.get("ranges", {})
        if not isinstance(ranges, dict):
            raise ConfigurationError("Doğrulama 'ranges' bir sözlük olmalıdır.")
        for fld, bounds in ranges.items():
            if not isinstance(bounds, dict) or not (set(bounds) <= {"min", "max"}) or not bounds:
                raise ConfigurationError(f"'ranges.{fld}' yalnızca 'min' ve/veya 'max' içermelidir.")
            for k, v in bounds.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ConfigurationError(f"'ranges.{fld}.{k}' sayı olmalıdır.")
        ts = params.get("timestamp", {})
        if not isinstance(ts, dict) or not (set(ts) <= {"min", "max"}):
            raise ConfigurationError("Doğrulama 'timestamp' yalnızca 'min' ve/veya 'max' içeren sözlük olmalıdır.")
        ipf = params.get("ip_format", False)
        if not isinstance(ipf, bool):
            raise ConfigurationError("Doğrulama 'ip_format' true/false olmalıdır.")
        am = params.get("allowed_methods", [])
        if not isinstance(am, list) or not all(isinstance(x, str) for x in am):
            raise ConfigurationError("Doğrulama 'allowed_methods' metin listesi olmalıdır.")
        return cls(rf, ranges, ts, ipf, am)

    def _value(self, record: LogRecord, name: str) -> Any:
        if hasattr(record, name):
            return getattr(record, name)
        return record.attributes.get(name)

    def _violations(self, r: LogRecord) -> List[str]:
        v: List[str] = []
        for name in self.required_fields:
            val = self._value(r, name)
            if val is None or (isinstance(val, str) and not val.strip()):
                v.append(f"zorunlu alan eksik: {name}")
        for name, b in self.ranges.items():
            val = self._value(r, name)
            if val is None:
                continue  # yokluğu required_fields'in işi
            try:
                num = float(val)
            except (TypeError, ValueError):
                v.append(f"{name} sayısal değil: {val!r}")
                continue
            if "min" in b and num < b["min"]:
                v.append(f"{name}={val} alt sınırın ({b['min']}) altında")
            if "max" in b and num > b["max"]:
                v.append(f"{name}={val} üst sınırın ({b['max']}) üstünde")
        if self.ts_min is not None or self.ts_max is not None:
            ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=_UTC)
            lo = self.ts_min
            hi = datetime.now(_UTC) + _NOW_TOLERANCE if self.ts_max == "now" else self.ts_max
            if lo is not None and ts < lo:
                v.append(f"zaman damgası çok eski: {ts.isoformat()} < {lo.isoformat()}")
            if hi is not None and ts > hi:
                v.append(f"zaman damgası gelecekte/aralık dışı: {ts.isoformat()} > {hi.isoformat()}")
        if self.ip_format:
            try:
                ipaddress.ip_address(r.client_ip)
            except ValueError:
                v.append(f"geçersiz IP biçimi: {r.client_ip!r}")
        if self.allowed_methods and r.method.upper() not in self.allowed_methods:
            v.append(f"izin verilmeyen HTTP metodu: {r.method}")
        return v

    def process(self, input_item: LogRecord, out: Emitter[LogRecord]) -> None:
        violations = self._violations(input_item)
        if violations:
            raise StageException("Doğrulama başarısız: " + "; ".join(violations))
        out.emit(input_item)
