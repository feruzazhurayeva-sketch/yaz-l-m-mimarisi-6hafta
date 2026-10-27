import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from interfaces import (Stage, Source, Sink, Emitter, StageException, PipelineException,
                        ConfigurationError)
from policy import ErrorPolicy, PolicyKind
from dead_letter import DeadLetterFileSink, FailedRecord
from pipeline import PipelineBuilder


class ListSource(Source):
    def __init__(self, items):
        self.items = items

    def produce(self, out):
        for i in self.items:
            out.emit(i)


class ListSink(Sink):
    def __init__(self):
        self.items = []

    def consume(self, item):
        self.items.append(item)


class ListDeadLetterSink(Sink):
    def __init__(self):
        self.items = []

    def consume(self, item):
        self.items.append(item)


class FailOn(Stage):
    """'bad' içeren girdide StageException fırlatır."""
    def process(self, item, out):
        if "bad" in item:
            raise StageException(f"kötü kayıt: {item}")
        out.emit(item.upper())


class Flaky(Stage):
    """İlk `fail_times` çağrıda hata verir, sonra başarılı olur (geçici I/O hatası benzetimi)."""
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def process(self, item, out):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise StageException("geçici hata")
        out.emit(item)


class Buggy(Stage):
    def process(self, item, out):
        raise ZeroDivisionError("beklenmeyen")


class TestErrorPolicyParsing(unittest.TestCase):
    def test_parse_all_forms(self):
        self.assertEqual(ErrorPolicy.parse("FAIL_FAST").kind, PolicyKind.FAIL_FAST)
        self.assertEqual(ErrorPolicy.parse("skip").kind, PolicyKind.SKIP)
        self.assertEqual(ErrorPolicy.parse("DEAD_LETTER").kind, PolicyKind.DEAD_LETTER)
        p = ErrorPolicy.parse("RETRY(3)")
        self.assertEqual((p.kind, p.retries), (PolicyKind.RETRY, 3))

    def test_invalid_policies(self):
        for bad in ["IGNORE", "RETRY", "RETRY(0)", "RETRY(x)", 5]:
            with self.assertRaises(ConfigurationError, msg=str(bad)):
                ErrorPolicy.parse(bad)


class TestPolicies(unittest.TestCase):
    def build(self, items, stage, policy, dead=True):
        b = PipelineBuilder.from_source(ListSource(items)).via(stage, on_error=policy, name="s")
        self.dl = ListDeadLetterSink()
        if dead:
            b.dead_letter(self.dl)
        self.sink = ListSink()
        return b.to(self.sink)

    def test_fail_fast_stops_run(self):
        p = self.build(["a", "bad", "c"], FailOn(), ErrorPolicy.fail_fast())
        with self.assertRaises(PipelineException):
            p.run()
        self.assertEqual(self.sink.items, ["A"])           # 'c' hiç işlenmedi
        self.assertEqual(p.summary.status, "FAILED")
        self.assertEqual(p.summary.stages[0].failed, 1)
        self.assertTrue(p.summary.is_balanced)

    def test_skip_counts_and_continues(self):
        p = self.build(["a", "bad", "c"], FailOn(), ErrorPolicy.skip(), dead=False)
        s = p.run()
        self.assertEqual(self.sink.items, ["A", "C"])
        self.assertEqual(s.stages[0].skipped, 1)
        self.assertEqual(s.dead_letter_count, 0)
        self.assertTrue(s.is_balanced)

    def test_dead_letter_routes_with_context(self):
        p = self.build(["a", "bad", "c"], FailOn(), ErrorPolicy.dead_letter())
        s = p.run()
        self.assertEqual(self.sink.items, ["A", "C"])
        self.assertEqual(len(self.dl.items), 1)
        fr = self.dl.items[0]
        self.assertIsInstance(fr, FailedRecord)
        self.assertEqual((fr.raw_input, fr.stage_name), ("bad", "s"))
        self.assertIsInstance(fr.exception, StageException)
        self.assertEqual(fr.context["line_number"], 2)
        self.assertIsNotNone(fr.timestamp)
        self.assertEqual(s.dead_letter_count, 1)
        self.assertTrue(s.is_balanced)

    def test_retry_succeeds_after_transient_failures(self):
        flaky = Flaky(fail_times=2)
        p = self.build(["x"], flaky, ErrorPolicy.retry(3))
        s = p.run()
        self.assertEqual(self.sink.items, ["x"])
        self.assertEqual(flaky.calls, 3)
        self.assertEqual(s.stages[0].retried, 2)
        self.assertEqual(s.dead_letter_count, 0)

    def test_retry_exhausted_falls_back_to_dead_letter(self):
        flaky = Flaky(fail_times=99)
        p = self.build(["x"], flaky, ErrorPolicy.retry(2))
        s = p.run()
        self.assertEqual(flaky.calls, 3)  # 1 deneme + 2 yeniden deneme
        self.assertEqual(s.dead_letter_count, 1)
        self.assertEqual(self.dl.items[0].context["attempts"], 3)
        self.assertTrue(s.is_balanced)

    def test_retry_exhausted_fail_fast_fallback(self):
        p = self.build(["x"], Flaky(99), ErrorPolicy.retry(1, fallback=PolicyKind.FAIL_FAST))
        with self.assertRaises(PipelineException):
            p.run()

    def test_unexpected_exception_follows_policy(self):
        p = self.build(["x", "y"], Buggy(), ErrorPolicy.dead_letter())
        s = p.run()
        self.assertEqual(s.dead_letter_count, 2)
        self.assertIn("ZeroDivisionError", str(self.dl.items[0].exception))

    def test_dead_letter_policy_without_channel_is_config_error(self):
        p = self.build(["a"], FailOn(), ErrorPolicy.dead_letter(), dead=False)
        with self.assertRaises(ConfigurationError):
            p.run()

    def test_filter_drops_are_counted_separately(self):
        class Drop(Stage):
            def process(self, item, out):
                if item != "keep":
                    return
                out.emit(item)
        p = self.build(["keep", "x", "y"], Drop(), ErrorPolicy.fail_fast(), dead=False)
        s = p.run()
        self.assertEqual((s.records_in, s.records_out, s.stages[0].filtered), (3, 1, 2))
        self.assertTrue(s.is_balanced)

    def test_sink_failure_is_pipeline_exception(self):
        class BrokenSink(Sink):
            def consume(self, item):
                raise OSError("disk dolu")
        p = PipelineBuilder.from_source(ListSource(["a"])).via(FailOn(), name="s").to(BrokenSink())
        with self.assertRaises(PipelineException) as ctx:
            p.run()
        self.assertIn("disk dolu", str(ctx.exception))

    def test_unreadable_source_is_pipeline_exception_and_summary_kept(self):
        from stages import FileLineSource
        p = PipelineBuilder.from_source(FileLineSource("/nonexistent/x.log")).via(FailOn()).to(ListSink())
        with self.assertRaises(PipelineException):
            p.run()
        self.assertEqual(p.summary.status, "FAILED")

    def test_stage_exception_is_not_pipeline_exception(self):
        self.assertFalse(issubclass(StageException, PipelineException))
        self.assertTrue(issubclass(ConfigurationError, PipelineException))

    def test_dead_letter_file_sink_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dl.jsonl")
            p = (PipelineBuilder.from_source(ListSource(["bad" + "z" * 50, "ok"]))
                 .via(FailOn(), on_error=ErrorPolicy.dead_letter(), name="s")
                 .dead_letter(DeadLetterFileSink(path, max_raw_length=10))
                 .to(ListSink()))
            p.run()
            with open(path, encoding="utf-8") as f:
                rows = [json.loads(l) for l in f]
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["stage"], r["raw_truncated"], r["raw_length"]), ("s", True, 53))
            self.assertEqual(len(r["raw"]), 10)
            self.assertEqual(r["exception_type"], "StageException")


if __name__ == '__main__':
    unittest.main()
