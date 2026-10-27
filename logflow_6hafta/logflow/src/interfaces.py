from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

I = TypeVar('I')
O = TypeVar('O')
T = TypeVar('T')

class StageException(Exception):
    """
    Bir aşamada TEK BİR kayıt işlenirken oluşan, KURTARILABİLİR hata.

    İşlem hattı sağlıklıdır; yalnızca o kayıt işlenemedi. Kaydın akıbetini aşamanın
    hata politikası (FAIL_FAST / SKIP / DEAD_LETTER / RETRY) belirler.
    """

    def __init__(self, message: str, raw_input: Optional[str] = None):
        super().__init__(message)
        self.raw_input = raw_input  # Hatayı üreten aşama biliyorsa ham girdi


class PipelineException(Exception):
    """
    İşlem hattının DEVAM EDEMEYECEĞİ hata (yapılandırma hatası, okunamayan dosya,
    diskin dolması, dead-letter hedefine yazılamaması...).

    Kayıt düzeyinde değil, çalıştırma düzeyindedir; hiçbir hata politikası tarafından
    yutulmaz, çalıştırmayı durdurur.
    """
    pass


class ConfigurationError(PipelineException):
    """Yapılandırma dosyasındaki sözdizimi, eksik alan, geçersiz aşama veya tip hatalarında fırlatılır."""
    pass

class Emitter(ABC, Generic[T]):
    """Veriyi bir sonraki aşamaya ileten arayüz."""
    @abstractmethod
    def emit(self, item: T) -> None:
        pass

class Stage(ABC, Generic[I, O]):
    """Veriyi işleyen aşama / filtre arayüzü."""
    @abstractmethod
    def process(self, input_item: I, out: Emitter[O]) -> None:
        pass

    def open(self) -> None:
        """Yaşam döngüsü kancası (gerekli kaynakları açmak için)."""
        pass

    def close(self) -> None:
        """Yaşam döngüsü kancası (kaynakları kapatmak için)."""
        pass

class Source(ABC, Generic[O]):
    """Boru hattına veri üreten kaynak arayüzü."""
    @abstractmethod
    def produce(self, out: Emitter[O]) -> None:
        pass

class Sink(ABC, Generic[I]):
    """Boru hattından gelen veriyi tüketen hedef arayüzü."""
    @abstractmethod
    def consume(self, item: I) -> None:
        pass