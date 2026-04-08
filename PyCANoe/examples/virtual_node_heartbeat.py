# examples/virtual_node_heartbeat.py
"""
Virtual Node 예제: 100ms 주기 Heartbeat 전송 + 수신 카운터 로그.

사용 방법:
  1. PyCANoe 실행 → CH1 추가 (virtual 인터페이스)
  2. View > Virtual Node → 스크립트 로드 → 이 파일 선택 → CH1 선택
  3. Trace에서 0x7FF 메시지 수신 확인

버스 API:
  bus.send(arb_id, data)          CAN 메시지 전송
  bus.send_fd(arb_id, data)       CAN FD 메시지 전송
  bus.log(text)                   Virtual Node 로그 콘솔 출력
  bus.get_signal(ch_id, name)     최신 신호값 조회 (float | None)
  bus.set_interval(ms)            on_timer 주기 변경 (런타임 가능)
"""

_rx_count = 0
_tx_count = 0


def on_start(bus):
    """노드 시작 시 1회 호출."""
    bus.log("Heartbeat 노드 시작 — 100ms 주기로 0x7FF 전송")
    bus.set_interval(100)   # on_timer 주기 100ms


def on_message(bus, msg):
    """메시지 수신 시마다 호출 (is_tx=True 메시지는 전달되지 않음)."""
    global _rx_count
    _rx_count += 1
    if _rx_count % 100 == 0:
        bus.log(f"수신 {_rx_count}건 누적 (최근: ID=0x{msg.arb_id:X})")


def on_timer(bus):
    """set_interval() 주기마다 호출."""
    global _tx_count
    _tx_count += 1

    # 1바이트 카운터 페이로드 (0~255 순환)
    payload = bytes([_tx_count & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    bus.send(0x7FF, payload)

    if _tx_count % 10 == 0:
        bus.log(f"TX {_tx_count}건 | RX {_rx_count}건")
