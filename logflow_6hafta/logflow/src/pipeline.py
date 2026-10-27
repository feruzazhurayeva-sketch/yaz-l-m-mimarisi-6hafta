import time
from typing import Any, Callable, List, Optional

from interfaces import (Source, Sink, Stage, Emitter, StageException,
                        PipelineException, ConfigurationError)
from policy import ErrorPolicy, PolicyKind
from dead_letter import DeadLetterChannel, FailedRecord
from summary import RunSummary, StageStats
from record import LogRecord


class _CallbackEmitter(Emitter[Any]):
    """Bir sonraki aşamaya geçiş fonksiyonunu sarmalayan yardımcı Emitter."""
    def __init__(self, callback: Callable[[Any], None]):
        self.callback = callback

    def emit(self, item: Any) -> None:
        self.callback(item)


def _raw_of(item: Any) -> str:
    """Hatalı kaydın ham girdisini döndürür (aşama dizisinde nerede olursa olsun)."""
    if isinstance(item, LogRecord):
        return item.raw or str(item)
    if isinstance(item, str):
        return item
    return repr(item)


class Pipeline:
    """
    Aşamaları sıralı tutan ve veriyi kaynaktan hedefe ileten motor.

    Topoloji:   Source -> Stage -> Stage -> ... -> Sink            (ana akış)
                            \\__ hata + politika ___/
                                     v
                             DeadLetterChannel -> DeadLetterSink   (ikincil akış)

    Hata yönlendirmesi motorun topolojik kararıdır: aşamalar yalnızca StageException
    fırlatır; kaydın nereye gideceğini aşamanın politikası ve motor belirler.
    """

    def __init__(self, source: Source[Any], sink: Sink[Any],
                 dead_letter: Optional[DeadLetterChannel] = None):
        self.source = source
        self.sink = sink
        self.dead_letter = dead_letter
        self.stages: List[Stage[Any, Any]] = []
        self.policies: List[ErrorPolicy] = []
        self.stage_names: List[str] = []
        self.summary: RunSummary = RunSummary()
        self._seq = 0  # kaynaktan okunan kaydın sıra numarası (tanılama bağlamı)

    # ---- kurulum ---------------------------------------------------------
    def add_stage(self, stage: Stage[Any, Any], on_error: Optional[ErrorPolicy] = None,
                  name: Optional[str] = None) -> 'Pipeline':
        base = name or type(stage).__name__
        unique, n = base, 1
        while unique in self.stage_names:
            n += 1
            unique = f"{base}#{n}"
        self.stages.append(stage)
        self.policies.append(on_error or ErrorPolicy.fail_fast())
        self.stage_names.append(unique)
        return self

    def validate(self) -> None:
        """Çalıştırmadan önce (hiç I/O yapılmadan) topoloji tutarlılığını denetler."""
        if self.dead_letter is None:
            for name, pol in zip(self.stage_names, self.policies):
                if pol.uses_dead_letter:
                    raise ConfigurationError(
                        f"'{name}' aşaması {pol} politikası kullanıyor ancak bir 'dead_letter' hedefi tanımlı değil."
                    )

    # ---- çalıştırma ------------------------------------------------------
    def run(self, print_summary: bool = False) -> RunSummary:
        self.validate()
        self.summary = RunSummary(stages=[
            StageStats(name=n, policy=str(p)) for n, p in zip(self.stage_names, self.policies)
        ])
        self._seq = 0
        started = time.perf_counter()

        # Açılış sırası: dead-letter -> sink -> aşamalar -> kaynak. Kapanış tersi.
        components: List[Any] = []
        if self.dead_letter is not None:
            components.append(self.dead_letter)
        components.append(self.sink)
        components.extend(self.stages)
        components.append(self.source)

        opened: List[Any] = []
        error: Optional[PipelineException] = None
        close_errors: List[str] = []
        try:
            try:
                for comp in components:
                    if hasattr(comp, 'open'):
                        comp.open()
                    opened.append(comp)
                emitter = _CallbackEmitter(self._on_source_item)
                self.source.produce(emitter)
            except PipelineException as e:
                error = e
            except Exception as e:  # beklenmeyen: çalıştırma düzeyinde hata sayılır
                error = PipelineException(f"Beklenmeyen çalıştırma hatası: {type(e).__name__}: {e}")
                error.__cause__ = e
        finally:
            for comp in reversed(opened):
                if hasattr(comp, 'close'):
                    try:
                        comp.close()
                    except Exception as ce:
                        close_errors.append(f"{type(comp).__name__}: {ce}")

        if error is None and close_errors:
            error = PipelineException("Kaynaklar kapatılırken hata: " + "; ".join(close_errors))

        s = self.summary
        s.elapsed_seconds = time.perf_counter() - started
        s.dead_letter_count = self.dead_letter.count if self.dead_letter is not None else 0
        if error is not None:
            s.status = "FAILED"
            s.failure_reason = str(error)
        if print_summary:
            print(s.format())
        if error is not None:
            raise error
        return s

    def _on_source_item(self, item: Any) -> None:
        self.summary.records_in += 1
        self._seq = self.summary.records_in
        self._dispatch(item, 0)

    def _consume(self, item: Any) -> None:
        try:
            self.sink.consume(item)
        except PipelineException:
            raise
        except Exception as e:  # hedef yazılamıyorsa çalıştırma devam edemez
            raise PipelineException(f"Hedefe yazılamadı: {type(e).__name__}: {e}") from e
        self.summary.records_out += 1

    def _dispatch(self, current_item: Any, stage_index: int) -> None:
        if stage_index >= len(self.stages):
            self._consume(current_item)
            return

        stage = self.stages[stage_index]
        policy = self.policies[stage_index]
        name = self.stage_names[stage_index]
        stats = self.summary.stages[stage_index]
        stats.received += 1
        seq = self._seq

        attempts = 0
        while True:
            attempts += 1
            emitted = [0]

            def forward(nxt: Any, _e=emitted) -> None:
                _e[0] += 1
                stats.emitted += 1
                self._dispatch(nxt, stage_index + 1)

            try:
                stage.process(current_item, _CallbackEmitter(forward))
                if emitted[0] == 0:
                    stats.filtered += 1  # hata yok: kural gereği elendi (filtre)
                return
            except PipelineException:
                raise  # alt aşamalardan/hedeften gelen: hiçbir politika yutmaz
            except StageException as e:
                exc = e
            except Exception as e:  # aşamadaki beklenmeyen hata: kayıt düzeyinde ele alınır
                exc = StageException(f"Beklenmeyen hata: {type(e).__name__}: {e}")
                exc.__cause__ = e

            # --- hata politikası ---
            if policy.kind == PolicyKind.RETRY:
                if attempts <= policy.retries:
                    stats.retried += 1
                    if policy.retry_delay_s > 0:
                        time.sleep(policy.retry_delay_s)
                    continue
                effective = policy.fallback
            else:
                effective = policy.kind

            if effective == PolicyKind.FAIL_FAST:
                stats.failed += 1
                raise PipelineException(
                    f"[{name}] FAIL_FAST - {seq}. kayıt işlenemedi: {exc}"
                ) from exc
            if effective == PolicyKind.SKIP:
                stats.skipped += 1
                return
            if effective == PolicyKind.DEAD_LETTER:
                if self.dead_letter is None:
                    raise ConfigurationError(f"'{name}' için dead_letter hedefi tanımlı değil.")
                self.dead_letter.send(FailedRecord(
                    raw_input=exc.raw_input if exc.raw_input is not None else _raw_of(current_item),
                    stage_name=name,
                    exception=exc,
                    context={"line_number": seq, "stage_index": stage_index,
                             "attempts": attempts, "policy": str(policy)},
                ))
                stats.dead_lettered += 1
                return


class PipelineBuilder:
    """
    Akıcı (Fluent) Pipeline kurucu sınıfı.
    Pipeline bileşenlerinin zincirleme metotlarla kurulmasını sağlar.
    """
    def __init__(self, source: Source[Any]):
        self._source = source
        self._stages: List[tuple] = []
        self._dead_letter: Optional[DeadLetterChannel] = None

    @classmethod
    def from_source(cls, source: Source[Any]) -> 'PipelineBuilder':
        return cls(source)

    def via(self, stage: Stage[Any, Any], on_error: Optional[ErrorPolicy] = None,
            name: Optional[str] = None) -> 'PipelineBuilder':
        self._stages.append((stage, on_error, name))
        return self

    def dead_letter(self, sink: Sink[Any]) -> 'PipelineBuilder':
        """Dead-letter (ikincil) hedefini tanımlar."""
        self._dead_letter = DeadLetterChannel(sink)
        return self

    def to(self, sink: Sink[Any]) -> Pipeline:
        pipeline = Pipeline(self._source, sink, self._dead_letter)
        for stage, on_error, name in self._stages:
            pipeline.add_stage(stage, on_error, name)
        return pipeline
