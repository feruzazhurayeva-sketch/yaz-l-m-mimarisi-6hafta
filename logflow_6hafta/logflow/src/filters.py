from typing import Callable, List, Dict, Any
from interfaces import Stage, Emitter
from record import LogRecord

class PredicateFilterStage(Stage[LogRecord, LogRecord]):
    """Bir kaydı yalnızca verilen predicate koşulunu sağlıyorsa ileten filtre aşaması."""

    def __init__(self, predicate: Callable[[LogRecord], bool]):
        self.predicate = predicate

    def process(self, input_item: LogRecord, out: Emitter[LogRecord]) -> None:
        if self.predicate(input_item):
            out.emit(input_item)

    @classmethod
    def from_config(cls, field: str, op: str, value: Any) -> 'PredicateFilterStage':
        """Yapılandırma parametrelerinden dinamik bir koşullu filtre aşaması üretir."""
        operators = {
            ">=": lambda val, target: val >= target,
            "<=": lambda val, target: val <= target,
            ">": lambda val, target: val > target,
            "<": lambda val, target: val < target,
            "==": lambda val, target: val == target,
            "!=": lambda val, target: val != target,
            "startswith": lambda val, target: str(val).startswith(str(target)),
            "contains": lambda val, target: str(target) in str(val),
        }

        if op not in operators:
            raise ValueError(f"Desteklenmeyen operatör: '{op}'. Desteklenenler: {list(operators.keys())}")

        comp_fn = operators[op]

        def predicate(record: LogRecord) -> bool:
            # Önce LogRecord nesnesinin temel alanlarına bak
            if hasattr(record, field):
                record_val = getattr(record, field)
            elif field in record.attributes:
                record_val = record.attributes[field]
            else:
                return False
            
            try:
                # Tipleri eşitlemeye çalış (örnek: sayısal karşılaştırmalar)
                if isinstance(value, (int, float)) and not isinstance(record_val, (int, float)):
                    record_val = type(value)(record_val)
                return comp_fn(record_val, value)
            except (ValueError, TypeError):
                return False

        return cls(predicate)


class ProjectionStage(Stage[LogRecord, Dict[str, Any]]):
    """
    Her kaydı yalnızca seçilen alanların bir alt kümesine indirger.
    Veri minimizasyonu (Data Minimization) sağlar.
    """

    def __init__(self, fields: List[str]):
        self.fields = [f.strip() for f in fields]

    def process(self, input_item: LogRecord, out: Emitter[Dict[str, Any]]) -> None:
        projected = {}
        for field in self.fields:
            if hasattr(input_item, field):
                projected[field] = getattr(input_item, field)
            elif field in input_item.attributes:
                projected[field] = input_item.attributes[field]
        out.emit(projected)