# MouseKeepAwake 사용 가이드

## 빠른 시작

### 1. 프로그램 실행

**실행 파일 사용:**
```bash
# dist 폴더의 exe 파일 실행
./dist/MouseKeepAwake.exe
```

**Python 소스 코드 사용:**
```bash
# 의존성 설치 (최초 1회)
pip install -r requirements.txt

# 프로그램 실행
python main.py
```

### 2. 시스템 트레이 확인

프로그램이 실행되면 시스템 트레이(알림 영역)에 마우스 아이콘이 나타납니다.

### 3. 프로그램 제어

시스템 트레이의 마우스 아이콘을 우클릭하면 메뉴가 나타납니다:

- **Enabled** (체크박스): 프로그램 활성화/비활성화 토글
- **Quit**: 프로그램 종료

## 설정 변경

`config.py` 파일을 편집하여 프로그램 동작을 커스터마이징할 수 있습니다:

```python
# 마우스 움직임이 없을 때까지 대기하는 시간 (초)
IDLE_TIMEOUT = 10  # 기본값: 10초

# 마우스 이동 거리 (픽셀)
MOVEMENT_PIXELS = 1  # 기본값: 1픽셀

# 마우스 이동 후 원위치로 돌아올 때까지의 지연 시간 (초)
MOVEMENT_DELAY = 0.05  # 기본값: 0.05초 (50ms)

# 유휴 시간 체크 간격 (초)
CHECK_INTERVAL = 1  # 기본값: 1초
```

### 설정 예시

**더 빠르게 작동하도록 설정:**
```python
IDLE_TIMEOUT = 5  # 5초마다 체크
CHECK_INTERVAL = 0.5  # 0.5초마다 확인
```

**더 조용하게 작동하도록 설정:**
```python
IDLE_TIMEOUT = 30  # 30초마다 체크
MOVEMENT_PIXELS = 0  # 0픽셀 이동 (일부 시스템에서는 작동 안 할 수 있음)
```

## EXE 파일 빌드

직접 실행 파일을 빌드하려면:

```bash
# 빌드 스크립트 실행
python build_exe.py
```

빌드가 완료되면 `dist/MouseKeepAwake.exe` 파일이 생성됩니다.

## 문제 해결

### 프로그램이 보이지 않음

1. 작업 관리자에서 `MouseKeepAwake.exe` 또는 `python.exe` 프로세스 확인
2. 시스템 트레이의 숨겨진 아이콘 영역 확인 (^)

### 백신 프로그램 차단

일부 백신 프로그램이 마우스 제어를 의심할 수 있습니다:

**해결 방법:**
1. 백신 프로그램 설정에서 예외 목록에 추가
2. 소스 코드를 직접 확인하고 Python으로 실행
3. 빌드 시 코드 서명 추가 (고급 사용자)

### 프로그램이 작동하지 않음

1. **관리자 권한으로 실행**: 일부 시스템에서 마우스 제어에 관리자 권한 필요
2. **Python 버전 확인**: Python 3.8 이상 필요
3. **의존성 재설치**:
   ```bash
   pip uninstall pynput pystray pillow
   pip install -r requirements.txt
   ```

### 마우스가 움직이지 않음

1. 시스템 트레이에서 프로그램이 "Enabled" 상태인지 확인
2. `config.py`에서 `IDLE_TIMEOUT` 값 확인
3. 터미널에서 실행하여 에러 메시지 확인:
   ```bash
   python main.py
   ```

## 고급 사용

### Windows 시작 프로그램에 등록

1. `Win + R` 키를 눌러 실행 창 열기
2. `shell:startup` 입력
3. `MouseKeepAwake.exe`의 바로가기를 시작프로그램 폴더에 복사

### 로깅 활성화

디버깅을 위해 로그 파일을 생성하려면 `main.py` 실행 시:

```bash
python main.py > mousekeepawake.log 2>&1
```

### 특정 시간대에만 작동

Windows 작업 스케줄러나 별도 스크립트를 사용하여 특정 시간에만 프로그램을 실행/종료할 수 있습니다.

## 성능 최적화

### 메모리 사용량 확인

```bash
# Windows
tasklist /FI "IMAGENAME eq MouseKeepAwake.exe"

# Python 실행 시
python -m memory_profiler main.py
```

### CPU 사용량 최소화

`config.py`에서 `CHECK_INTERVAL` 값을 늘리면 CPU 사용량을 줄일 수 있습니다:

```python
CHECK_INTERVAL = 2  # 2초마다 확인
```

## 라이선스 및 법적 고지

이 프로그램은 **합법적인 목적**으로만 사용하세요:
- ✅ 프레젠테이션 중 화면 유지
- ✅ 긴 문서 읽기
- ✅ 모니터링 화면 유지
- ✅ 개인 편의

다음과 같은 용도로 사용하지 마세요:
- ❌ 회사 감시 시스템 우회
- ❌ 근태 부정
- ❌ 기타 부적절한 목적

## 지원

- **버그 리포트**: GitHub Issues
- **기능 제안**: GitHub Discussions
- **문의**: 프로젝트 README 참조
