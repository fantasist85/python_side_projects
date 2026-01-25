# **PyCANoe 통합 프로젝트 계획 및 설계서**

## **1\. 프로젝트 개요 (계획서)**

### **1.1. 프로젝트 명**

PyCANoe (Python CAN/LIN Analyzer)

### **1.2. 프로젝트 목표**

* LGPL 라이선스를 준수하는 PySide6를 기반으로, 경량화되고 고성능인 CAN/LIN 네트워크 분석 및 시뮬레이션 도구를 개발한다.  
* UI 멈춤 현상이 없는(Non-Blocking) 반응형 인터페이스를 제공한다.  
* 향후 기능 확장이 용이한 모듈식 계층형 아키텍처를 구축한다.

### **1.3. 핵심 기능 범위 (Scope)** 

요청사항(UDS, CAPL, H/W)을 반영하여 범위를 3단계(현재/향후/제외)로 명확히 구분합니다.

| In-Scope (v1.0 구현 대상) | Future Scope (향후 확장) |
| :---- | :---- |
| **1\. 모니터링 (Trace):** CAN/LIN 실시간 추적 | 1\. **진단 (UDS)** |
| **2\. 시각화 (Graph):** DBC/LDF 기반 신호 그래프 | 2\. **H/W 확장:** Kvaser, PCAN, 기타 python-can 지원 H/W |
| **3\. 시뮬레이션 (Sim):** CANoe IG 스타일의 메시/신호 전송 |  |
| **4\. 데이터베이스:** DBC (CAN), LDF (LIN) 로드 및 파싱 |  |
| **5\. 로깅:** ASC, BLF, CSV 포맷 로그 저장 및 읽기 (Replay 제외) |  |
| **6\. H/W (v1.0):** **Vector** (VN16xx, VT 등 python-can 지원 장비) |  |

## **2\. 기술 스택 및 개발 환경 (작업지시서)**

### **2.1. 핵심 기술 스택**

| 구분 | 기술 | 라이선스 | 선정 사유 |
| :---- | :---- | :---- | :---- |
| **UI** | **PySide6** | **LGPL** | **(핵심)** GPL을 회피, 상업적/사내 사용 자유. QDockWidget, Model/View 등 전문 UI 기능 제공. |
| **그래프** | **PyQtGraph** | MIT | matplotlib 대비 압도적인 실시간 성능. PySide6와 완벽 호환. |
| **통신** | **python-can** | LGPL | **Vector(현재), Kvaser/PCAN(향후)** 등 다양한 H/W 백엔드를 동일 API로 지원. (확장성) |
| **DB 파싱** | cantools (DBC) | MIT | CAN DBC 파싱의 사실상 표준. 경량화. |
| **(DB 파싱)** | ldfparser (LDF) | MIT | LDF 파싱을 위한 경량화 라이브러리. |

### **2.2. 개발 환경 구축 (작업지시서)**

**1\. 가상환경 생성 (필수)**

\# 프로젝트 루트 폴더에서 실행  
python \-m venv venv  
\# Windows  
.\\venv\\Scripts\\activate  
\# macOS/Linux  
source venv/bin/activate

**2\. 의존성 파일 (requirements.txt)**

\# \---------------------------------  
\# PyCANoe Project Dependencies  
\# \---------------------------------

\# Core Framework (LGPL)  
PySide6

\# High-Speed Plotting (MIT)  
pyqtgraph

\# Hardware Communication (LGPL)  
python-can

\# Database Parsing (MIT)  
cantools  
ldfparser

\# Required by pyqtgraph (BSD)  
numpy

**설치:** pip install \-r requirements.txt

**3\. Git 무시 파일 (.gitignore)**

\# Python  
venv/  
\_\_pycache\_\_/  
\*.pyc  
\*.egg-info/

\# IDE  
.vscode/  
.idea/

\# Build artifacts  
dist/  
build/  
\*.spec

## **3\. 시스템 아키텍처 및 설계 (설계도)**

### **3.1. 아키텍처 목표**

1. **UI 멈춤 방지:** QThread (멀티스레딩)를 통해 H/W I/O 및 모든 무거운 작업을 메인 UI 스레드와 완벽히 분리한다.  
2. **확장성 및 유지보수:** "계층 분리(Layered Architecture)"를 통해 UI, 로직, 데이터를 명확히 분리한다.

### **3.2. 계층 분리 (Layered Architecture)**

* **Presentation Layer (UI):** (app/, widgets/)  
* **Service Layer (Logic):** (core/)  
* **Data Layer (Model):** (models/, core/db\_parser.py)  
* **Infrastructure Layer (I/O):** (python-can 라이브러리)

### **3.3. 핵심 아키텍처: 멀티스레딩 (Signal / Slot)**

* **Main Thread (UI Thread):** UI 위젯 관리, 사용자 입력 수신.  
* **CANWorker(QThread):** H/W I/O, 메시지 수신/파싱/로깅 전담.  
* **SimWorker(QThread):** 시뮬레이션(IG) 주기적 전송 로직 전담.

### **3.4. 핵심 데이터 흐름 (설계도)**

1. **흐름 1: CAN 연결** (User \-\> UI \-\> connect\_requested Signal \-\> CANWorker)  
2. **흐름 2: Trace 업데이트 (Model/View)** (CANWorker \-\> new\_message\_received Signal \-\> TraceModel \-\> QTreeView 자동 업데이트)

## **4\. 상세 UI/UX 설계 (설계도)**

### **4.1. UI/UX 목표**

* QDockWidget을 활용하여 **Menu, Connection, Trace, Simulation** 창은 기본적으로 표시되고 고정된 레이아웃을 제공한다.  
* **Graph Dock은 기본적으로 숨겨진(Folded/Tabbed) 상태**이며, 사용자가 View \-\> Graph 메뉴나 툴바의 'Graph' 버튼을 누르면 우측에 펼쳐지도록(Un-fold) 한다.  
* QSettings를 사용하여 사용자의 마지막 창 레이아웃과 설정을 저장/복원한다.  
* Simulation(IG) 창은 CANoe IG와 유사하게 \*\*'신호/메시지 트리'\*\*와 \*\*'제어 패널'\*\*이 분리된 QSplitter 기반 레이아웃을 제공한다.

### **4.2. UI (TXT GUI) 시각화**

* 기본 레이아웃 (Graph Dock 숨김 상태)
+--------------------------------------------------------------------------------------+
| PyCANoe v1.0 (LGPL)                                                                  |
+--------------------------------------------------------------------------------------+
| File  Edit  View  Connection  Tools  Help                                            |
+--------------------------------------------------------------------------------------+
| [Connect 🔌] [DBC 📚] [Graph 📈] [Start ▶] [Stop ■]                                    |
+======================================================================================+
| [Dock] Trace Monitor (고정)                                                          |
|--------------------------------------------------------------------------------------|
| Timestamp | Type | ID   | DLC | Data               | Signal (DBC)                    |
| 100.1234  | CAN  | 1A0  | 8   | 01 02 03 04 FF...  | EngSpeed (1200)                 |
| 100.1255  | CAN  | 1B2  | 4   | FF 00 FF 00        |                                 |
| 100.1278  | LIN  | 3C   | 8   | 00 00 00 00 00...  | L_Signal_A (0)                  |
| ...       | ...  | ...  | ... | ...                | ...                             |
|           |      |      |     |                    |                                 |
|           |      |      |     |                    |                                 |
+======================================================================================+
| [Dock] Simulation (IG) (고정) - (문서 4.3의 QSplitter 레이아웃)                        |
|--------------------------------------------------------------------------------------|
| + [Tree] DBC/LDF 메시지/신호      + [Controls] 신호 제어판 (QStackedWidget)          |
| | ▾ CAN_Msg_A (100ms)           | |                                              |
| |     [S] EngSpeed (1200)       | | [Signal: EngSpeed]                             |
| |     [S] VehSpeed (40)         | | 값 (Value): [ 1200   ] (rpm)                 |
| |   ▸ CAN_Msg_B (20ms)          | | 슬라이더:   [    |=======o    ] (0-8000)      |
| |   ▸ LIN_Msg_C (500ms)         | | Waveform:   [None ▼] [Ramp] [Sine]            |
| |                               | |                                              |
| +---------------------------------+ +----------------------------------------------+ |
+--------------------------------------------------------------------------------------+
| [Status: Connected] [Baud: 500k] [HW: Vector VN1610] [DBC: my_car.dbc]               |
+--------------------------------------------------------------------------------------+

* Graph Dock 표시 상태
+--------------------------------------------------+ +--------------------------------+
| PyCANoe v1.0 (LGPL)                              | |                                |
+--------------------------------------------------+ |                                |
| File  Edit  View  Connection  Tools  Help        | |                                |
+--------------------------------------------------+ |                                |
| [Connect 🔌] [DBC 📚] [Graph 📈] [Start ▶] [Stop ■] | |                                |
+==================================================+ |                                |
| [Dock] Trace Monitor (고정)                      | | [Dock] Graph (우측에 표시/도킹)  |
|--------------------------------------------------| |--------------------------------|
| Timestamp | ID   | Data         | Signal       | | 4000 |         /--\         |
| 100.1234  | 1A0  | 01 02 03...  | EngSpeed(1200) | | 3000 |        /    \        |
| 100.1255  | 1B2  | FF 00 FF...  |              | | 2000 |       /      \       |
| 100.1278  | 3C   | 00 00 00...  | L_Signal_A(0)| | 1000 | -----/        \      |
| 100.1334  | 1A0  | 01 03 03...  | EngSpeed(1250) | | 0    +---|---|---|---|Time|
| ...       | ...  | ...          | ...          | |      100 101 102 103 104 |
|           |      |              |              | | (EngSpeed)                     |
+==================================================+ |                                |
| [Dock] Simulation (IG) (고정)                    | |                                |
|--------------------------------------------------| |                                |
| + [Tree] DBC/LDF ...        + [Controls] ...   | |                                |
| | ▾ CAN_Msg_A (100ms)       | | [EngSpeed]     | |                                |
| |     [S] EngSpeed (1250)   | | Val: [ 1250 ] | |                                |
| |     [S] VehSpeed (40)     | | [|=======o  ] | |                                |
| |   ▸ CAN_Msg_B (20ms)      | |                | |                                |
| +---------------------------+ +------------------+ |                                |
+--------------------------------------------------+ +--------------------------------+
| [Status: Connected] [Baud: 500k] [HW: Vector VN1610] [DBC: my_car.dbc]              |
+------------------------------------------------------------------------------------+

### **4.3. 컴포넌트별 상세 명세**

* **MainWindow (QMainWindow):**  
  * 메뉴, 툴바, 상태바, QDockWidget 영역 관리.  
  * **View 메뉴** (QMenu)를 포함하여 Trace, Graph, Simulation Dock의 toggleViewAction()을 연결.  
  * 'Graph' 툴바 버튼 추가.  
* **Connection Dialog (QDialog):**  
  * Interface: "Vector" (Default/v1.0), (향후 Kvaser, PCAN 등 python-can 백엔드 확장)  
  * Channel: "CAN 1" (드롭다운)  
  * Baudrate: "500k" (드롭다운)  
  * DBC/LDF Path: \[...\] (파일 열기 버튼)  
* **Trace Dock (QDockWidget):**  
  * (기본 고정) QTreeView \+ TraceModel(QAbstractItemModel) 사용.  
  * **컬럼:** Timestamp, Type, ID, DLC, Data, Signal (DBC 해석).  
  * **우클릭 메뉴:** Send to Graph, Send to Simulation.  
* **Graph Dock (QDockWidget):**  
  * **(기본 숨김/Folded)** pyqtgraph.PlotWidget 사용.  
  * View 메뉴 또는 Graph 툴바 버튼으로 토글 시 우측에 표시.  
* **Simulation Dock (QDockWidget):**  
  * (기본 고정) \*\*QSplitter\*\*를 사용하여 IG 스타일 UI 구현 (기존 QTabWidget 설계 변경).  
  * **좌측 (Tree):** QTreeWidget (DBC/LDF 메시지/신호 계층 구조).  
  * **우측 (Controls):** QStackedWidget 또는 QFrame. 좌측 트리에서 신호 선택 시, 해당 신호의 제어판(값 입력, 슬라이더, Waveform 설정 테이블 등)을 동적으로 표시.

## **5\. 프로젝트 스캐폴딩 (작업지시서)**

PyCANoe/  
├── .gitignore  
├── README.md  
├── requirements.txt  
├── venv/  
└── src/  
    ├── main.py                \# 1\. Entry Point  
    ├── resources/             \# (아이콘, QSS)  
    │  
    ├── app/                   \# 2\. UI Layer (MainWindow, Dialogs)  
    │   ├── main\_window.py  
    │   ├── config\_manager.py  \# (QSettings)  
    │   └── dialogs/  
    │       └── connect\_dialog.py  
    │  
    ├── core/                  \# 3\. Service Layer (Workers, Parsers)  
    │   ├── can\_worker.py      \# (QThread)  
    │   ├── sim\_worker.py      \# (QThread)  
    │   └── db\_parser.py       \# (cantools/ldfparser 래핑)  
    │  
    ├── models/                \# 4\. Data Layer (Qt Models)  
    │   └── trace\_model.py     \# (QAbstractItemModel)  
    │  
    └── widgets/               \# 5\. UI Layer (Dock Components)  
        ├── trace\_dock.py      \# (QDockWidget \+ QTreeView)  
        ├── graph\_dock.py      \# (QDockWidget \+ PlotWidget)  
        └── sim\_dock.py        \# (QDockWidget \+ QSplitter)

## **6\. M1. 핵심 작업 지시서 (작업지시서)**

**목표:** UI를 제외한 핵심 아키텍처(멀티스레딩)와 백엔드 기능(HW, DBC)을 검증한다.

**Task (작업 목록):**

1. **\[Setup\]** git init, venv 생성, .gitignore, requirements.txt 작성 및 pip install.  
2. **\[Setup\]** 5번 항목의 "프로젝트 스캐폴딩"에 따라 빈 폴더와 \_\_init\_\_.py, main.py 파일 생성.  
3. **\[Spike\]** test\_hw.py (별도 스크립트) 작성, python-can \+ Vector H/W로 CLI 환경에서 메시지 수신(listen) 검증.  
4. **\[Spike\]** test\_dbc.py (별도 스크립트) 작성, cantools로 샘플 DBC 로드 및 decode() 검증.  
5. **\[Arch-POC\]** src/main.py, src/app/main\_window.py, src/core/can\_worker.py 3개 파일로 멀티스레딩 아키텍처 프로토타입(POC) 구현.  
   * main\_window: 'Connect'/'Disconnect' 버튼, QStatusBar만 구현.  
   * can\_worker: (가짜) start\_connection 슬롯이 1초마다 counter\_updated(int) 시그널을 emit.  
   * main\_window: counter\_updated 시그널을 받아 QStatusBar 텍스트 업데이트.  
6. **\[AC\] (인수 기준):**  
   * **M1 완료 조건:** 'Connect' 버튼을 눌러 카운트가 시작된 상태에서, **메인 윈도우 창을 마우스로 격렬하게 드래그해도 UI가 절대 멈추거나 버벅이지 않아야 한다.**  
   * (검증 완료 시, M2: 고성능 Trace 구현으로 진행)