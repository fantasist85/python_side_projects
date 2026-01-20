# Python 프로젝트 모음

이 저장소는 다양한 파이썬 프로젝트들을 모아놓은 모음집입니다. 각 프로젝트는 독립적으로 실행 가능하며, 개별 폴더로 구성되어 있습니다.

## 프로젝트 목록

| 프로젝트 이름 | 폴더 경로 | 설명 | 주요 기술/라이브러리 | 상태 |
|--------------|----------|------|-------------------|------|
| PyCANoe | `/PyCANoe` | CAN/LIN 네트워크 분석 및 시뮬레이션 도구 | PySide6, PyQtGraph, python-can, cantools | 개발중 |

## 프로젝트 구조

각 프로젝트는 다음과 같은 구조를 권장합니다:

```
project-name/
├── README.md           # 프로젝트 설명 및 사용법
├── requirements.txt    # 의존성 패키지 목록
├── main.py            # 메인 실행 파일 (또는 다른 진입점)
├── src/               # 소스 코드 (선택사항)
└── tests/             # 테스트 코드 (선택사항)
```

## 새 프로젝트 추가하기

1. 루트 디렉토리에 새 폴더 생성
2. 해당 폴더에 프로젝트 파일 추가
3. 프로젝트 폴더 내에 `README.md` 작성
4. 이 파일(`claude.md`)의 프로젝트 목록 표에 항목 추가

### 프로젝트 목록 추가 예시

```markdown
| Calculator | `/calculator` | 간단한 계산기 애플리케이션 | Python 3.x | 완료 |
| Web Scraper | `/web-scraper` | 웹 크롤링 도구 | requests, beautifulsoup4 | 진행중 |
```

## 실행 방법

각 프로젝트의 실행 방법은 해당 프로젝트 폴더 내의 `README.md`를 참조하세요.

일반적인 실행 순서:

```bash
# 1. 프로젝트 폴더로 이동
cd project-name

# 2. 가상환경 생성 (선택사항)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 프로젝트 실행
python main.py
```

## 기여 가이드

- 각 프로젝트는 독립적으로 관리됩니다
- 새 프로젝트 추가 시 반드시 `README.md`와 `requirements.txt` 포함
- 이 문서(`claude.md`)의 프로젝트 목록을 최신 상태로 유지

## 라이선스

각 프로젝트의 라이선스는 개별 프로젝트 폴더를 참조하세요.
