# -*- mode: python ; coding: utf-8 -*-
# PyCANoe — PyInstaller Build Spec
#
# 빌드 명령:
#   Windows: pyinstaller build.spec
#   Linux  : pyinstaller build.spec  (테스트/검증용)
#
# 주요 검증 포인트 (M3 AC):
#   1. Vector DLL — Windows 전용. vxlapi64.dll 경로는 설치 환경에 맞게 조정.
#   2. lark grammars — ldfparser 내부 lark 문법 파일 포함 필수.
#   3. can.interfaces.vector/virtual — hiddenimports 명시 필수.
#   4. Python 없는 환경에서 dist/PyCANoe 실행 검증.
#
# Windows DLL 경로 조정:
#   VXLAPI_DLL 변수를 실제 설치 경로로 변경 후 빌드.
#   Vector XL Driver Library 미설치 시 주석 처리 → vector 인터페이스만 비활성.

import sys
import pathlib

# ── 경로 설정 ──────────────────────────────────────────────────────────────
SRC_DIR = pathlib.Path('src').resolve()

# ldfparser 내부 lark 문법 파일 경로 (설치 환경에 따라 자동 탐색)
try:
    import ldfparser
    LDFPARSER_ROOT = pathlib.Path(ldfparser.__file__).parent
    LDFPARSER_GRAMMARS = str(LDFPARSER_ROOT / 'grammars')
    _ldfparser_datas = [(LDFPARSER_GRAMMARS, 'ldfparser/grammars')]
except Exception:
    _ldfparser_datas = []

# lark 내장 grammars (common.lark 등 — ldfparser가 의존)
try:
    import lark
    LARK_ROOT = pathlib.Path(lark.__file__).parent
    LARK_GRAMMARS = str(LARK_ROOT / 'grammars')
    _lark_datas = [(LARK_GRAMMARS, 'lark/grammars')]
except Exception:
    _lark_datas = []

# ── Windows Vector DLL (선택) ──────────────────────────────────────────────
# Windows에서 Vector H/W 사용 시: 아래 두 줄의 주석을 해제하고
# VXLAPI_DLL 경로를 실제 설치 위치로 변경한다.
# 기본 설치 경로: C:\Program Files\Vector XL Driver Library\bin\vxlapi64.dll
#
# VXLAPI_DLL = r'C:\Program Files\Vector XL Driver Library\bin\vxlapi64.dll'
# _vector_binaries = [(VXLAPI_DLL, '.')] if sys.platform == 'win32' and pathlib.Path(VXLAPI_DLL).exists() else []
_vector_binaries = []   # Linux 빌드 / Vector DLL 없는 환경

# ── Analysis ───────────────────────────────────────────────────────────────
a = Analysis(
    [str(SRC_DIR / 'main.py')],
    pathex=[str(SRC_DIR)],
    binaries=_vector_binaries,
    datas=_ldfparser_datas + _lark_datas,
    hiddenimports=[
        # python-can 인터페이스 — 동적 import라 PyInstaller가 자동 탐지 불가
        'can.interfaces.vector',
        'can.interfaces.virtual',
        'can.interfaces.kvaser',
        'can.interfaces.pcan',
        'can.interfaces.socketcan',
        # lark — cantools/ldfparser 내부에서 동적 import
        'lark',
        'lark.grammars',
        'lark.parsers',
        'lark.parsers.earley_forest',
        'lark.parsers.earley_common',
        'lark.parsers.xearley',
        # cantools 내부 포맷 모듈
        'cantools.database.can.formats.dbc',
        'cantools.database.can.formats.sym',
        'cantools.database.can.formats.kcd',
        'cantools.database.diagnostics.formats.cdd',
        # numpy (NumpySignalBuffer)
        'numpy',
        'numpy.core',
        # pyqtgraph (GraphDock)
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        # widgets — PyInstaller가 동적 import를 놓칠 수 있음
        'widgets.bus_stats_dock',
        'widgets.graph_dock',
        'widgets.sim_dock',
        'widgets.trace_dock',
        # PySide6 — 일부 서브모듈 동적 로드
        'PySide6.QtPrintSupport',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 대형 패키지 제외 → 바이너리 크기 절감
        'matplotlib',
        'tkinter',
        'scipy',
        'PIL',
        'IPython',
        'jupyter',
        'notebook',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── EXE / 바이너리 ────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PyCANoe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # GUI 앱 — 콘솔 창 없음
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='resources/icon.ico',  # 아이콘 파일 있을 때 활성화
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PyCANoe',
)
