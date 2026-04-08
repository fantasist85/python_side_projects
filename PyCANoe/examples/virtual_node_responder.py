# examples/virtual_node_responder.py
"""
Virtual Node 예제: DBC 신호 기반 조건부 응답 노드.

EngSpeed 신호가 3000rpm 이상이면 경고 메시지(0x600) 전송.
수신한 메시지의 신호 값을 SimStateStore에서 실시간 조회.

사전 조건: DBC 로드 완료 (EngSpeed 신호 포함 DBC)
"""

_last_eng_speed = 0.0
_warn_sent = False


def on_start(bus):
    bus.log("Responder 노드 시작 (EngSpeed 3000rpm 초과 시 경고 전송)")
    bus.set_interval(500)   # 500ms 마다 신호 상태 점검


def on_message(bus, msg):
    """CAN 메시지 수신 시 EngSpeed 신호 값 추출."""
    global _last_eng_speed
    if msg.signals and "EngSpeed" in msg.signals:
        _last_eng_speed = msg.signals["EngSpeed"]


def on_timer(bus):
    """500ms 주기로 SimStateStore에서 신호 값 재확인 후 조건 판단."""
    global _warn_sent

    # SimStateStore에서 최신값 조회 (on_message가 없는 경우에도 동작)
    speed = bus.get_signal(0, "EngSpeed")
    if speed is None:
        return

    if speed >= 3000.0 and not _warn_sent:
        # 경고 메시지 전송 (ID 0x600, 1바이트 = 0xFF)
        bus.send(0x600, b'\xFF\x00\x00\x00\x00\x00\x00\x00')
        bus.log(f"⚠ 경고 전송: EngSpeed={speed:.0f}rpm (≥3000)")
        _warn_sent = True
    elif speed < 3000.0 and _warn_sent:
        bus.log(f"정상 복귀: EngSpeed={speed:.0f}rpm")
        _warn_sent = False
