from typing import Callable, Dict, Any
from interfaces import Stage, Source, Sink, ConfigurationError
from stages import FileLineSource, ConsoleSink, FileSink
from parser import ParserStage
from validation import ValidationStage
from dead_letter import DeadLetterFileSink
from filters import PredicateFilterStage, ProjectionStage


class StageRegistry:
    """
    Aşama, kaynak ve hedef bileşenlerinin fabrika fonksiyonlarını
    isimleriyle eşleyen veri odaklı kayıt defteri (Registry).
    """
    _stages: Dict[str, Callable[[Dict[str, Any]], Stage]] = {}
    _sources: Dict[str, Callable[[Dict[str, Any]], Source]] = {}
    _sinks: Dict[str, Callable[[Dict[str, Any]], Sink]] = {}

    @classmethod
    def register_stage(cls, name: str, factory: Callable[[Dict[str, Any]], Stage]) -> None:
        cls._stages[name] = factory

    @classmethod
    def register_source(cls, name: str, factory: Callable[[Dict[str, Any]], Source]) -> None:
        cls._sources[name] = factory

    @classmethod
    def register_sink(cls, name: str, factory: Callable[[Dict[str, Any]], Sink]) -> None:
        cls._sinks[name] = factory

    @classmethod
    def create_stage(cls, name: str, params: Dict[str, Any]) -> Stage:
        if name not in cls._stages:
            raise ConfigurationError(
                f"Bilinmeyen aşama türü: '{name}'. Desteklenen aşamalar: {list(cls._stages.keys())}"
            )
        return cls._stages[name](params)

    @classmethod
    def create_source(cls, name: str, params: Dict[str, Any]) -> Source:
        if name not in cls._sources:
            raise ConfigurationError(
                f"Bilinmeyen kaynak türü: '{name}'. Desteklenen kaynaklar: {list(cls._sources.keys())}"
            )
        return cls._sources[name](params)

    @classmethod
    def create_sink(cls, name: str, params: Dict[str, Any]) -> Sink:
        if name not in cls._sinks:
            raise ConfigurationError(
                f"Bilinmeyen hedef (sink) türü: '{name}'. Desteklenen hedefler: {list(cls._sinks.keys())}"
            )
        return cls._sinks[name](params)


# --- Fabrika Fonksiyonları ve Doğrulama Kuralları ---

def _create_file_source(params: Dict[str, Any]) -> Source:
    if "path" not in params:
        raise ConfigurationError("Kaynak 'file' için zorunlu 'path' parametresi eksik.")
    if not isinstance(params["path"], str):
        raise ConfigurationError("Kaynak 'path' parametresi metin (str) olmalıdır.")
    return FileLineSource(params["path"])


def _create_file_sink(params: Dict[str, Any]) -> Sink:
    if "path" not in params:
        raise ConfigurationError("Hedef 'file' için zorunlu 'path' parametresi eksik.")
    if not isinstance(params["path"], str):
        raise ConfigurationError("Hedef 'path' parametresi metin (str) olmalıdır.")
    return FileSink(params["path"])


def _create_console_sink(params: Dict[str, Any]) -> Sink:
    return ConsoleSink()


def _create_parser_stage(params: Dict[str, Any]) -> Stage:
    fmt = params.get("format", "clf")
    if fmt != "clf":
        raise ConfigurationError(f"Desteklenmeyen log biçimi: '{fmt}'. Yalnızca 'clf' desteklenir.")
    max_len = params.get("max_line_length", ParserStage.DEFAULT_MAX_LINE_LENGTH)
    if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len < 1:
        raise ConfigurationError("Ayrıştırıcı 'max_line_length' pozitif bir tam sayı olmalıdır.")
    return ParserStage(max_len)


def _create_validation_stage(params: Dict[str, Any]) -> Stage:
    return ValidationStage.from_config(params)


def _create_dead_letter_file_sink(params: Dict[str, Any]) -> Sink:
    if "path" not in params or not isinstance(params["path"], str):
        raise ConfigurationError("Dead-letter hedefi 'dead_letter_file' için metin türünde 'path' zorunludur.")
    max_raw = params.get("max_raw_length", 500)
    if isinstance(max_raw, bool) or not isinstance(max_raw, int) or max_raw < 1:
        raise ConfigurationError("Dead-letter 'max_raw_length' pozitif bir tam sayı olmalıdır.")
    return DeadLetterFileSink(params["path"], max_raw)


def _create_filter_stage(params: Dict[str, Any]) -> Stage:
    for required in ["field", "op", "value"]:
        if required not in params:
            raise ConfigurationError(f"Filtre aşaması için zorunlu '{required}' parametresi eksik.")
    
    if not isinstance(params["field"], str) or not isinstance(params["op"], str):
        raise ConfigurationError("Filtre parametrelerinden 'field' ve 'op' metin (str) olmalıdır.")

    try:
        return PredicateFilterStage.from_config(
            field=params["field"],
            op=params["op"],
            value=params["value"]
        )
    except ValueError as e:
        raise ConfigurationError(str(e))


def _create_projection_stage(params: Dict[str, Any]) -> Stage:
    if "fields" not in params:
        raise ConfigurationError("Projeksiyon aşaması için zorunlu 'fields' parametresi eksik.")
    fields = params["fields"]
    if not isinstance(fields, list) or len(fields) == 0:
        raise ConfigurationError("Projeksiyon 'fields' parametresi boş olmayan bir liste olmalıdır.")
    return ProjectionStage(fields)


# Bileşenlerin Kayıt Defterine Eklenmesi
StageRegistry.register_source("file", _create_file_source)
StageRegistry.register_sink("file", _create_file_sink)
StageRegistry.register_sink("console", _create_console_sink)
StageRegistry.register_sink("dead_letter_file", _create_dead_letter_file_sink)

StageRegistry.register_stage("parse", _create_parser_stage)
StageRegistry.register_stage("validate", _create_validation_stage)
StageRegistry.register_stage("filter", _create_filter_stage)
StageRegistry.register_stage("project", _create_projection_stage)