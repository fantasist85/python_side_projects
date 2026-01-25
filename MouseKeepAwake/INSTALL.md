# MouseKeepAwake 설치 가이드

## Windows 사용자

### 방법 1: 실행 파일 사용 (가장 쉬움)

이미 빌드된 실행 파일이 있다면:
1. `MouseKeepAwake.exe` 더블클릭
2. 시스템 트레이에서 실행 확인

### 방법 2: Python 소스 코드로 실행

#### 1단계: Python 설치 확인

```powershell
python --version
```

Python 3.8 이상이 필요합니다. 없다면 https://www.python.org/downloads/ 에서 다운로드하세요.

#### 2단계: 가상 환경 생성 (권장)

```powershell
cd D:\Git\python\MouseKeepAwake
python -m venv venv
.\venv\Scripts\activate
```

#### 3단계: 의존성 설치

```powershell
pip install -r requirements.txt
```

설치되는 패키지:
- `pynput==1.7.6` - 마우스 이벤트 모니터링
- `pystray==0.19.5` - 시스템 트레이 아이콘
- `Pillow==10.1.0` - 이미지 처리
- `pyinstaller==6.3.0` - 실행 파일 빌드용

#### 4단계: 프로그램 실행

```powershell
python main.py
```

### 방법 3: 직접 빌드하기

#### 1단계: 의존성 설치

```powershell
pip install -r requirements.txt
```

#### 2단계: 빌드 스크립트 실행

```powershell
python build_exe.py
```

#### 3단계: 실행 파일 확인

빌드가 성공하면 `dist\MouseKeepAwake.exe` 파일이 생성됩니다.

```powershell
.\dist\MouseKeepAwake.exe
```

## 일반적인 문제 해결

### 문제 1: PyInstaller를 찾을 수 없습니다

**에러:**
```
❌ Unexpected error: [WinError 2] 지정된 파일을 찾을 수 없습니다
```

**해결 방법:**

```powershell
# PyInstaller 설치 확인
pip show pyinstaller

# 없다면 설치
pip install pyinstaller

# 설치 후 버전 확인
python -m PyInstaller --version
```

### 문제 2: 가상 환경 활성화 오류

**에러:**
```
이 시스템에서 스크립트를 실행할 수 없으므로...
```

**해결 방법:**

관리자 권한으로 PowerShell을 열고:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 문제 3: pynput 설치 오류

**해결 방법:**

```powershell
# Visual C++ 재배포 가능 패키지 설치 필요
# https://aka.ms/vs/17/release/vc_redist.x64.exe

# 또는 개별 설치
pip install --upgrade pip
pip install pynput --no-cache-dir
```

### 문제 4: 백신 프로그램이 차단함

**해결 방법:**

1. **Windows Defender:**
   - 설정 → Windows 보안 → 바이러스 및 위협 방지
   - "바이러스 및 위협 방지 설정 관리"
   - "제외 항목 추가" → 파일 선택 → `MouseKeepAwake.exe`

2. **다른 백신:**
   - 소스 코드로 직접 실행: `python main.py`
   - 또는 백신 프로그램의 예외 목록에 추가

### 문제 5: 빌드가 너무 오래 걸림

정상입니다. 첫 빌드는 2-5분 정도 소요될 수 있습니다.

## 빌드 최적화 옵션

더 작은 실행 파일을 원한다면:

### UPX 압축 사용 (선택사항)

1. UPX 다운로드: https://github.com/upx/upx/releases
2. UPX를 `C:\upx`에 압축 해제
3. `build_exe.py` 수정:

```python
# 이 줄의 주석 제거
'--upx-dir=C:/upx',
```

4. 다시 빌드

예상 크기:
- 압축 없음: ~10-12 MB
- UPX 압축: ~4-6 MB

## 자동 시작 설정

Windows 부팅 시 자동 실행:

1. `Win + R` 키 누르기
2. `shell:startup` 입력
3. `MouseKeepAwake.exe`의 바로가기 복사
4. 시작프로그램 폴더에 붙여넣기

## 추가 도움말

- 자세한 사용법: `USAGE.md` 참조
- 설정 변경: `config.py` 편집
- 버그 리포트: GitHub Issues
