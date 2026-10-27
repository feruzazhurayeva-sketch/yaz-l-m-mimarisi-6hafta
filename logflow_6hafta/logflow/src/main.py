import argparse
import json
import sys
from stages import FileLineSource, ConsoleSink, FileSink
from parser import ParserStage
from filters import PredicateFilterStage, ProjectionStage
from pipeline import PipelineBuilder
from loader import PipelineLoader
from interfaces import ConfigurationError, PipelineException
from policy import ErrorPolicy
from dead_letter import DeadLetterFileSink

def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LogFlow Pipeline - Bildirimsel Yapılandırma ve Log Filtreleme Aracı"
    )
    parser.add_argument("-c", "--config", help="YAML yapılandırma dosyası yolu (örn: configs/error-report.yaml)")
    parser.add_argument("input_file", nargs="?", help="İşlenecek log dosyası yolu (yalnızca manuel modda)")
    parser.add_argument("-o", "--output", help="Çıktının yazılacağı dosya yolu")
    parser.add_argument("--min-status", type=int, help="Yalnızca belirtilen HTTP durum kodu ve üzerini filtreler")
    parser.add_argument("--path-prefix", help="Yalnızca belirtilen yol öneki ile başlayanları filtreler")
    parser.add_argument("--dead-letter", help="Hatalı kayıtların yazılacağı dead-letter dosyası (manuel mod; yoksa hatalı satırlar SKIP ile atlanır ve sayılır)")
    parser.add_argument("--summary-json", help="Çalıştırma özetini JSON olarak yazar")
    parser.add_argument("--fields", help="Virgülle ayrılmış projeksiyon alanları")
    return parser

def main():
    cli_parser = build_cli_parser()
    args = cli_parser.parse_args()

    # 1. Bildirimsel (Declarative) Yapılandırma Modu
    if args.config:
        try:
            pipeline = PipelineLoader.load_from_file(args.config)
        except ConfigurationError as err:
            print(f"[YAPILANDIRMA HATASI] {err}", file=sys.stderr)
            sys.exit(1)
        sys.exit(_run(pipeline, args, label=f"'{args.config}'"))

    # 2. Manuel CLI Modu (Increment 3 Geriye Dönük Uyumluluk)
    if not args.input_file:
        cli_parser.print_help()
        sys.exit(1)

    source = FileLineSource(args.input_file)
    builder = PipelineBuilder.from_source(source)
    if args.dead_letter:
        builder.dead_letter(DeadLetterFileSink(args.dead_letter))
        builder.via(ParserStage(), on_error=ErrorPolicy.dead_letter(), name="parse")
    else:
        builder.via(ParserStage(), on_error=ErrorPolicy.skip(), name="parse")

    if args.min_status is not None:
        builder.via(PredicateFilterStage(lambda r: r.status >= args.min_status), name="filter-status")

    if args.path_prefix is not None:
        builder.via(PredicateFilterStage(lambda r: r.path.startswith(args.path_prefix)), name="filter-path")

    if args.fields is not None:
        field_list = [f.strip() for f in args.fields.split(",")]
        builder.via(ProjectionStage(field_list), name="project")

    sink = FileSink(args.output) if args.output else ConsoleSink()
    sys.exit(_run(builder.to(sink), args, label=args.input_file))


def _run(pipeline, args, label: str) -> int:
    """Çalıştırır; başarıyla da hatayla da RunSummary yazdırır. Çıkış kodu: 0 ok, 2 PipelineException."""
    code = 0
    try:
        pipeline.run(print_summary=True)
        print(f"[LogFlow] {label} başarıyla çalıştırıldı.")
    except PipelineException as err:
        print(f"[PIPELINE HATASI] {err}", file=sys.stderr)
        code = 2
    if args.summary_json:
        with open(args.summary_json, "w", encoding="utf-8") as f:
            json.dump(pipeline.summary.to_dict(), f, indent=2, ensure_ascii=False)
    return code


if __name__ == "__main__":
    main()