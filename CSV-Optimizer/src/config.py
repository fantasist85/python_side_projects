"""
CSV-Optimizer 설정 파일
"""

from pathlib import Path

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent

# 입출력 폴더
INPUT_FOLDER = PROJECT_ROOT / "input"
OUTPUT_FOLDER = PROJECT_ROOT / "output"
REDUCED_FOLDER = OUTPUT_FOLDER / "reduced"
MERGED_FOLDER = OUTPUT_FOLDER / "merged"
IMAGES_FOLDER = OUTPUT_FOLDER / "images"
EXAMPLES_FOLDER = PROJECT_ROOT / "examples"

# 폴더 자동 생성
for folder in [INPUT_FOLDER, OUTPUT_FOLDER, REDUCED_FOLDER, MERGED_FOLDER, IMAGES_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

# CSV 읽기/쓰기 설정
CSV_READ_OPTIONS = {
    'infer_schema_length': 10000,  # 첫 10000줄로 스키마 추론
    'ignore_errors': True,  # 읽기 오류 무시
    'truncate_ragged_lines': True,  # 스키마와 맞지 않는 행 자동 처리
}

CSV_WRITE_OPTIONS = {
    'include_header': True,  # 헤더 포함
    'null_value': '',  # null 값 표현
    'quote_style': 'necessary',  # 필요한 경우만 인용 (불필요한 쉼표 제거)
}

# 시각화 설정
VIZ_DPI = 100
VIZ_FIGSIZE = (12, 6)
VIZ_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

# 성능 설정
CHUNK_SIZE = 50000  # 파일 분할 시 청크 크기
MAX_ROWS = 1000000  # 메모리 제한 행 수

# 로깅
DEBUG = False
