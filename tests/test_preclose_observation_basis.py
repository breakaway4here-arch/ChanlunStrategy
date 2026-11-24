"""Offline producer and consumer coverage for the full-window observation fallback."""
import copy
import importlib.util
import json
import math
import socket
import unittest
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
import tempfile
from unittest.mock import patch

from chanlun.identity import normalize_identity
from chanlun.intraday_observation_data import (
    _digest, _resample_30m, parse_eastmoney_daily, parse_eastmoney_minutes,
)
from chanlun.market_history_store import MarketHistoryStore
from chanlun.preclose_runtime import MARKET_INDICES, _append_intraday_quote, build_scheduled_preclose_input
from chanlun.preclose_pipeline import PreclosePipelineComponents, run_preclose_pipeline
from chanlun.price_basis import canonical_daily_reference, daily_intraday_factor, pending_minute_basis
from chanlun.universe_builder import _rows_to_kline
from preclose_run import main, run_scheduled_preclose
from tests.test_intraday_observation_data import CUTOFF, IDENTITY, calendar, fixture

DAY = "2026-10-13"
PREVIOUS = "2026-10-12"
FACT = DAY + "T14:47:02+08:00"
KNOWN = DAY + "T14:46:00+08:00"
MODULE = "chanlun.preclose_observation_basis"


def historical_fixture():
    rows, response = fixture()
    for row in rows:
        for price in ("open", "high", "low", "close"):
            row[price] *= 2
    reference = canonical_daily_reference(IDENTITY, rows)
    stock = dict(IDENTITY, name="合成样本", klines=_rows_to_kline(rows),
                 price_basis={"canonical_daily": reference})
    quote = dict(IDENTITY, quote_source="eastmoney", quote_status="valid", quote_asof=KNOWN,
                 name="合成样本", is_st=False, delisting_risk=False, listed_date="20000101",
                 open=10.0, high=10.2, low=9.9, current_price=10.1, prev_close=10.1,
                 volume=160000., amount=161600000., amount_available=True,
                 amount_unit="CNY", amount_source="eastmoney",
                 volume_unit="hands", volume_raw_unit="hands", volume_source="eastmoney")
    return rows, response, stock, quote


def prepare():
    rows, response, stock, quote = historical_fixture()
    stock = _append_intraday_quote(stock, quote, DAY, FACT)
    stock["price_basis"]["historical_known_at"] = DAY + "T14:45:00+08:00"
    daily = {"data":{"code":"600000", "market":1,
                     "klines":[row["ts"]+",10,10.1,10.2,9.9,160000,161600000,0,0,0,0"
                               for row in rows]}}
    pair = {}
    evidence = []
    for interval, flag, adjustment, key in (
            ("15","0","raw","raw"), ("15","1","qfq","qfq"),
            ("101","0","raw","raw_daily"), ("101","1","qfq","daily")):
        body = response if interval=="15" else daily
        pair[key] = (parse_eastmoney_minutes(body,IDENTITY,adjustment=adjustment,
                           cutoff=CUTOFF,fetched_at=KNOWN) if interval=="15" else
                     parse_eastmoney_daily(body,IDENTITY,adjustment=adjustment,previous_trade_date=PREVIOUS))
        evidence.append(dict(params={"secid":"1.600000","klt":interval,"fqt":flag,
                                     "end":(DAY if interval=="15" else PREVIOUS).replace("-","")},
                             fetched_at=KNOWN,response_sha256=_digest(body),response=copy.deepcopy(body)))
    pair["source_evidence"] = evidence
    capture = {"cutoff":CUTOFF,"identity":normalize_identity(IDENTITY).key,"result":{"pair":pair}}
    capture["sha256"] = _digest(capture["result"])
    original = _resample_30m(pair["raw"])
    original.update(source="sina", adjustment="unverified", volume_source="sina",
                    volume_raw_unit="shares", amount_source="sina")
    for key in ("dates","opens","highs","lows","closes","volumes","amounts","finals","amount_available"):
        original[key] = original[key][-239:]
    original["minute_to_daily"] = pending_minute_basis("preclose_basis_unverified",interval="30m",as_of=FACT)
    minute = {"status":"available","klines":original,"bars":239,"latest_date":DAY,
              "latest_ts":original["dates"][-1],"as_of":FACT,"is_final":False,"bar_state":"intraday"}
    ready = int(datetime.fromisoformat(KNOWN).timestamp()*1e9)
    return stock,minute,capture,ready


class PrecloseObservationBasisTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE), "strict preclose-only evidence path missing")
        return __import__(MODULE,fromlist=["apply_observation_fallback"])

    def produce(self, stock, minute, capture, ready):
        return self.api().build_observation_fallback(stock,minute,capture,ready_at_ns=ready,
                         as_of=FACT,previous=PREVIOUS,calendar_check=calendar,
                         clock=lambda: datetime.fromisoformat(DAY + "T14:48:00+08:00"))

    def test_exact_full_window_is_built_with_its_own_source_and_scale(self):
        stock,minute,capture,ready=prepare()
        replacement=self.produce(stock,minute,capture,ready)
        kline=replacement["klines"]
        self.assertEqual(kline["dates"],minute["klines"]["dates"])
        self.assertEqual(len(kline["closes"]),239)
        self.assertEqual(kline["source"],"eastmoney_cutoff")
        self.assertEqual(kline["adjustment"],"qfq")
        self.assertEqual(kline["closes"][-1],20.2)
        self.assertEqual(kline["volumes"][-1],20000.0)
        self.assertEqual(kline["amounts"][-1],20200000.0)
        self.assertIs(self.api().verified_fallback_kline(stock,minute,replacement,FACT),kline)

    def test_missing_historical_amount_survives_live_and_frozen_consumers(self):
        stock,minute,capture,ready=prepare()
        # This is the representation emitted by universe_builder._rows_to_kline.
        stock["klines"]["amounts"][0]=math.nan
        stock["klines"]["amount_available"][0]=False
        replacement=self.produce(stock,minute,capture,ready)
        self.assertIsNotNone(self.api().verified_fallback_kline(stock,minute,replacement,FACT))

        frozen=copy.deepcopy(stock)
        frozen["klines"]["amounts"][0]=None
        self.assertIsNotNone(self.api().verified_fallback_kline(frozen,minute,replacement,FACT))
        for changed in ("availability","restored_amount","price","volume"):
            with self.subTest(changed=changed):
                row=copy.deepcopy(frozen)
                if changed=="availability":
                    row["klines"]["amount_available"][0]=True
                elif changed=="restored_amount":
                    row["klines"]["amounts"][0]=1.0
                else:
                    field="closes" if changed=="price" else "volumes"
                    row["klines"][field][0]=math.nan
                self.assertIsNone(self.api().verified_fallback_kline(row,minute,replacement,FACT))

    def test_unavailable_amount_does_not_allow_infinity_or_available_nan(self):
        for value,available in ((math.inf,False),(math.nan,True),(None,True)):
            with self.subTest(value=value,available=available):
                stock,minute,capture,ready=prepare()
                stock["klines"]["amounts"][0]=value
                stock["klines"]["amount_available"][0]=available
                with self.assertRaises(ValueError):
                    self.produce(stock,minute,capture,ready)

    def test_consumer_rejects_quote_receipt_window_and_original_source_changes(self):
        stock,minute,capture,ready=prepare()
        valid=self.produce(stock,minute,capture,ready)
        for name in ("quote_time","close","volume","amount","final","source","history","original"):
            with self.subTest(value=name):
                row,old,new=copy.deepcopy((stock,minute,valid))
                if name=="quote_time":
                    new["proof"]["quote_event_at"]=DAY+"T15:00:00+08:00"
                elif name in ("close","volume","amount"):
                    new["klines"][name+"s"][-8]+=0.01
                elif name=="final":
                    new["klines"]["finals"][-1]=False
                elif name=="source":
                    new["klines"]["source"]="sina"
                elif name=="history":
                    row["klines"]["opens"][-2]+=0.01
                else:
                    old["klines"]["opens"][-2]+=0.01
                self.assertIsNone(self.api().verified_fallback_kline(row,old,new,FACT))

    def test_source_identity_response_date_capture_and_future_reference_are_strict(self):
        for name in ("identity","response","request_date","source_time","ready","repaired_history","final"):
            with self.subTest(name=name):
                stock,minute,doc,ready=prepare()
                source=doc["result"]["pair"]["source_evidence"]
                if name=="identity":
                    doc["identity"]="stock|SH|600001"
                elif name=="response":
                    source[0]["response"]["data"]["code"]="600001"
                    source[0]["response_sha256"]=_digest(source[0]["response"])
                elif name=="request_date":
                    source[-1]["params"]["end"]="20261013"
                elif name=="source_time":
                    source[-1]["fetched_at"]=DAY+"T14:47:03+08:00"
                elif name=="ready":
                    ready=int(datetime.fromisoformat(FACT).timestamp()*1e9)+1
                elif name=="repaired_history":
                    ref=stock["price_basis"]["canonical_daily"]
                    ref["by_date"][PREVIOUS]["source"]=(
                        "price_basis_repair:v1:2026-05-01:2026-10-12:20261013T070000Z:tencent:"+"a"*64)
                    from chanlun.price_basis import basis_sha256
                    ref["sha256"]=basis_sha256(ref["by_date"])
                else:
                    stock["klines"]["finals"][-1]=True
                doc["sha256"]=_digest(doc["result"])
                with self.assertRaises(ValueError):
                    self.produce(stock,minute,doc,ready)

    def test_producer_obeys_existing_wall_deadline(self):
        stock,minute,capture,ready=prepare()
        with self.assertRaisesRegex(ValueError,"proof_outside_run_window"):
            self.api().build_observation_fallback(stock,minute,capture,ready_at_ns=ready,
                as_of=FACT,previous=PREVIOUS,calendar_check=calendar,
                clock=lambda: datetime.fromisoformat(DAY+"T14:56:00+08:00"))

    def test_late_atomic_file_rejected_even_with_earlier_mtime(self):
        with tempfile.TemporaryDirectory() as location:
            path=Path(location)/"stock-SH600000.json"
            path.write_text("{}")
            import os
            before=datetime.fromisoformat(CUTOFF).timestamp()
            os.utime(str(path),(before,before))
            with self.assertRaisesRegex(ValueError,"capture_after_fact"):
                self.api().read_observation_capture(path,datetime.fromisoformat(FACT))

    def test_budget_expiry_never_reads_or_requests_a_fallback(self):
        stock,minute,capture,ready=prepare()
        original=copy.deepcopy(minute)
        with patch.object(self.api(),"read_observation_capture",side_effect=AssertionError("unbudgeted read")):
            diagnostics=self.api().apply_observation_fallback({"600000":minute},[stock],
                capture_dir="/unused",as_of=FACT,previous=PREVIOUS,calendar_check=calendar,
                budget_remaining=lambda: 0)
        self.assertEqual(minute,original)
        self.assertEqual(diagnostics["target_count"],1)
        self.assertEqual(diagnostics["reasons"],{"budget_exhausted":1})

    def test_default_formal_comparison_rejects_the_separate_receipt(self):
        from types import SimpleNamespace

        stock,minute,capture,ready=prepare()
        fallback=self.produce(stock,minute,capture,ready)
        result=SimpleNamespace(code=IDENTITY["code"],strategy_input_evidence={
            "minute_to_daily":fallback["proof"], "adjustment":"qfq"})
        self.assertIsNone(daily_intraday_factor(stock,result))

    def test_existing_verified_source_is_left_on_its_existing_contract(self):
        stock,minute,capture,ready=prepare()
        minute["klines"]["minute_to_daily"]["status"]="verified"
        with patch.object(self.api(),"read_observation_capture",side_effect=AssertionError("already verified")):
            result=self.api().apply_observation_fallback({"600000":minute},[stock],
                capture_dir="/unused",as_of=FACT,previous=PREVIOUS,calendar_check=calendar)
        self.assertNotIn(self.api().FALLBACK_KEY,minute)
        self.assertEqual(result["reasons"],{"original_not_pending_sina":1})

    def scheduled(self, location, configured, pipeline_runner=run_preclose_pipeline):
        _,minute,capture,ready=prepare()
        _,_,history,quote=historical_fixture()
        current=[datetime.fromisoformat(DAY+"T14:45:05+08:00")]

        def fetch_quote():
            current[0]=datetime.fromisoformat(FACT)
            return [quote], {"as_of":FACT,"complete":True,"requested":1,"unique":1}

        root=Path(location)
        capture_root=root/"observation"
        env=root/"preclose.env"
        env.write_text(f"PRECLOSE_OBSERVATION_CAPTURE_ROOT={capture_root}\n" if configured else "")
        env.chmod(0o600)
        database=root/"market.sqlite"
        with MarketHistoryStore(database):
            pass
        saved_db=database.read_bytes()
        builder=partial(build_scheduled_preclose_input,
            universe_loader=lambda *args, **kwargs: ([history],{"previous_market_date":PREVIOUS}),
            quote_fetcher=fetch_quote, target_selector=lambda rows: rows,
            min30_fetcher=lambda *args: {"600000":minute}, turnover_loader=lambda *args: [],
            index_fetcher=lambda day:{key:{"closes":[10.]*120,"close":10.,"date":DAY}
                                      for key in MARKET_INDICES})
        with patch("chanlun.intraday_observation_data._calendar_reader",return_value=calendar), \
             patch.object(self.api(),"read_observation_capture",return_value=(capture,ready,_digest(capture))) as reader, \
             patch.object(socket.socket,"connect",side_effect=AssertionError("unexpected network fallback")):
            result=run_scheduled_preclose(root=root/"preclose",formal_market_db=database,
                    env_file=env,source_sha="isolated", now=lambda: current[0],trading_day_check=lambda *_:True,
                    runtime_builder=builder,pipeline_runner=pipeline_runner,skip_publish=True)
        self.assertEqual(database.read_bytes(),saved_db)
        if configured:
            reader.assert_called_once_with(capture_root/DAY/"inputs"/"stock-SH600000.json",
                                           datetime.fromisoformat(FACT))
        else:
            reader.assert_not_called()
        self.assertEqual(result["status"],"completed",result)
        return (json.loads((root/"preclose"/DAY/"input.json").read_text()),
                json.loads((root/"preclose"/DAY/"snapshot.json").read_text()))

    def test_scheduled_dedicated_env_routes_to_real_builder_and_consumer(self):
        with tempfile.TemporaryDirectory() as location:
            frozen,snapshot=self.scheduled(location,True)
        evidence=frozen["min30"]["600000"]
        self.assertEqual(evidence["klines"]["source"],"sina")
        self.assertEqual(evidence[self.api().FALLBACK_KEY]["klines"]["source"],"eastmoney_cutoff")
        self.assertEqual(snapshot["diagnostics"]["min30"]["observation_basis"]["selected_codes"],["600000"])
        self.assertEqual(frozen["runtime_diagnostics"]["observation_basis"]["by_exchange"],{"SH":{"verified":1}})
        self.assertEqual(frozen["daily"][0]["price_basis"]["intraday_quote"]["known_at"],FACT)
        self.assertEqual(len(frozen["daily"][0]["price_basis"]["canonical_daily"]["by_date"]),29)

    def test_scheduled_absent_configuration_preserves_original_source(self):
        with tempfile.TemporaryDirectory() as location:
            frozen,snapshot=self.scheduled(location,False)
        self.assertNotIn(self.api().FALLBACK_KEY,frozen["min30"]["600000"])
        self.assertNotIn("observation_basis",snapshot["diagnostics"]["min30"])

    def test_nonunity_receipt_only_routes_to_the_classic_price_comparisons(self):
        normal=PreclosePipelineComponents()
        observed={}

        def pipeline(inputs, *, config, components):
            stock=inputs["daily"][0]
            evaluation=dict(stock,**stock["klines"])

            def classic(pool, minutes, *, mode, price_aligner):
                minute=minutes[0]
                observed["classic"]=minute.strategy_input_evidence["source"]
                self.assertAlmostEqual(minute.lows[-1],19.8)
                self.assertAlmostEqual(price_aligner(minute.lows[-1],evaluation,minute),19.8)
                wrong=copy.deepcopy(evaluation)
                wrong["lows"][-2]+=0.01
                self.assertIsNone(price_aligner(minute.lows[-1],wrong,minute))
                return normal.upgrade_daily_candidates(pool,minutes,mode=mode,price_aligner=price_aligner)

            def preserve(name, original):
                def upgrade(pool, minutes):
                    minute=minutes[0]
                    observed[name]=minute.strategy_input_evidence["source"]
                    self.assertAlmostEqual(minute.lows[-1],9.9)
                    self.assertEqual(minute.strategy_input_evidence["minute_to_daily"]["status"],"pending")
                    return original(pool,minutes)
                return upgrade

            return run_preclose_pipeline(inputs,config=config,components=replace(normal,
                upgrade_daily_candidates=classic,
                upgrade_strong_startup=preserve("startup",normal.upgrade_strong_startup),
                upgrade_right_side_startup=preserve("right",normal.upgrade_right_side_startup)))

        with tempfile.TemporaryDirectory() as location:
            self.scheduled(location,True,pipeline_runner=pipeline)
        self.assertEqual(observed,{"classic":"eastmoney_cutoff","startup":"sina","right":"sina"})

    def test_manual_cli_cannot_enable_produced_proof_with_an_arbitrary_path(self):
        with self.assertRaisesRegex(SystemExit,"requires --scheduled"), \
             patch("preclose_run.run_preclose_once",side_effect=AssertionError("manual proof input ran")):
            main(["--input","unused.json","--source-sha","isolated",
                  "--observation-capture-root","/tmp/unused"])
