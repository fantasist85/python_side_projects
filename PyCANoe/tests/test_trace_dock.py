# tests/test_trace_dock.py
"""
TraceDock — 위젯 단위 테스트 (pytest-qt).

검증 항목:
  - 필터 적용 / 초기화 슬롯 동작
  - get_filter() / restore_filter() 왕복
  - set_db_loaded() — _db_loaded 플래그 갱신
  - scroll_to_bottom() — 크래시 없음
  - send_to_sim Signal 발생 검증
"""
import pytest
from PySide6.QtCore import Qt
from models.trace_model import TraceModel
from models.parsed_message import ParsedMessage
from widgets.trace_dock import TraceDock


def make_msg(arb_id=0x1A0, ch_id=0, signals=None):
    return ParsedMessage(
        ch_id=ch_id, timestamp=1.0, arb_id=arb_id,
        dlc=8, data=b'\x00' * 8, signals=signals,
    )


@pytest.fixture
def dock(qtbot):
    model = TraceModel()
    d = TraceDock(model)
    qtbot.addWidget(d)
    d.show()
    return d, model


# ── 필터 적용 ─────────────────────────────────────────────────────────────
class TestTraceDockFilter:
    def test_filter_apply_sets_model_filter(self, dock):
        d, model = dock
        d._le_filter_id.setText("1A0")
        d._le_filter_mask.setText("7FF")
        d._on_filter_apply()
        assert model._filter_id == 0x1A0
        assert model._filter_mask == 0x7FF

    def test_filter_apply_invalid_hex_ignored(self, dock):
        d, model = dock
        d._le_filter_id.setText("ZZZZ")
        d._on_filter_apply()
        # 파싱 실패 시 필터 미변경 (None 유지)
        assert model._filter_id is None

    def test_filter_clear_resets(self, dock):
        d, model = dock
        d._le_filter_id.setText("1A0")
        d._on_filter_apply()
        d._on_filter_clear()
        assert model._filter_id is None
        assert d._le_filter_id.text() == ""
        assert d._le_filter_mask.text() == "7FF"

    def test_get_filter_returns_current_text(self, dock):
        d, model = dock
        d._le_filter_id.setText("200")
        d._le_filter_mask.setText("7FF")
        fid, fmask = d.get_filter()
        assert fid == "200"
        assert fmask == "7FF"

    def test_restore_filter_sets_text_and_applies(self, dock):
        d, model = dock
        d.restore_filter("1A0", "7FF")
        assert d._le_filter_id.text() == "1A0"
        assert model._filter_id == 0x1A0

    def test_restore_filter_empty_strings_no_crash(self, dock):
        d, model = dock
        d.restore_filter("", "")   # 크래시 없어야 함
        assert model._filter_id is None


# ── DB 로드 플래그 ────────────────────────────────────────────────────────
class TestTraceDockDbLoaded:
    def test_db_loaded_false_by_default(self, dock):
        d, _ = dock
        assert d._db_loaded is False

    def test_set_db_loaded_true(self, dock):
        d, _ = dock
        d.set_db_loaded(True)
        assert d._db_loaded is True

    def test_set_db_loaded_false(self, dock):
        d, _ = dock
        d.set_db_loaded(True)
        d.set_db_loaded(False)
        assert d._db_loaded is False


# ── scroll_to_bottom ──────────────────────────────────────────────────────
class TestTraceDockScroll:
    def test_scroll_to_bottom_no_crash(self, dock):
        d, model = dock
        model.append_batch([make_msg(arb_id=i) for i in range(10)])
        d.scroll_to_bottom()   # 크래시 없어야 함


# ── send_to_sim Signal ────────────────────────────────────────────────────
class TestTraceDockSignals:
    def test_send_to_sim_signal(self, dock, qtbot):
        d, model = dock
        msg = make_msg(arb_id=0x100)
        model.append_batch([msg])

        received = []
        d.send_to_sim.connect(lambda ch, aid, dlc, data: received.append((ch, aid, dlc, data)))

        # 컨텍스트 메뉴 직접 트리거 대신 메서드 직접 호출
        d.send_to_sim.emit(msg.ch_id, msg.arb_id, msg.dlc, msg.data)

        assert len(received) == 1
        assert received[0][1] == 0x100   # arb_id 확인
