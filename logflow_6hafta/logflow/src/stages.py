from typing import Any, Optional
from interfaces import Source, Sink, Emitter, PipelineException

class FileLineSource(Source[str]):
    """Dosyayı satır satır okuyup boru hattına aktaran kaynak bileşen."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def produce(self, out: Emitter[str]) -> None:
        # errors="surrogateescape": UTF-8 olmayan baytlar okuma sırasında çökmez; satırda
        # kurtarılabilir biçimde (\udcXX) taşınır ve ParserStage bunu StageException'a çevirir.
        # Dosyanın hiç açılamaması/okunamaması ise çalıştırma düzeyinde bir hatadır.
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="surrogateescape", newline="") as file:
                for line in file:
                    out.emit(line.rstrip("\r\n"))
        except OSError as e:
            raise PipelineException(f"Dosya okuma hatası ({self.file_path}): {e}") from e


class ConsoleSink(Sink[Any]):
    """Gelen veriyi konsola yazdıran hedef bileşen."""

    def consume(self, item: Any) -> None:
        print(item)


class FileSink(Sink[Any]):
    """
    Çıktıyı hedef dosyaya yazan bileşen.
    open() ve close() yaşam döngüsü kancaları sayesinde kaynak sızıntısını ve
    arabellek kaybını (buffer loss) önler.
    """

    def __init__(self, output_path: str):
        self.output_path = output_path
        self._file: Optional[Any] = None

    def open(self) -> None:
        try:
            self._file = open(self.output_path, "w", encoding="utf-8")
        except OSError as e:
            raise PipelineException(f"Çıktı dosyası açılamadı ({self.output_path}): {e}")

    def consume(self, item: Any) -> None:
        if self._file is None:
            raise PipelineException("FileSink açık değil! open() çağrılmadı.")
        try:
            self._file.write(f"{item}\n")
        except OSError as e:  # disk dolu vb.
            raise PipelineException(f"Çıktı dosyasına yazılamadı ({self.output_path}): {e}") from e

    def close(self) -> None:
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None