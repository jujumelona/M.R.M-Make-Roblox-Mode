# R.M.M — Roblox 게임 제작 도구

자연어로 Roblox 게임의 요구사항을 입력하고, 기획 파일을 만든 뒤 Luau 소스와 Roblox Studio 프로젝트를 생성하는 도구입니다. Google Colab 또는 로컬 CLI에서 사용할 수 있습니다.

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jujumelona/M.R.M-Make-Roblox-Mode/blob/main/R.M.M_Make_Roblox_Mode_Colab.ipynb)

## 1. Google Colab에서 시작하기

1. 위 **Open in Colab** 버튼을 눌러 노트북을 엽니다.
2. **런타임 → 런타임 유형 변경**에서 GPU 사용 환경을 선택합니다. 로컬 모델을 사용하는 경우 GPU 런타임이 필요합니다.
3. 첫 번째 설정 셀에서 `RUN_MODE`, `PROMPT` 및 필요한 옵션을 지정합니다.
4. 셀을 **1번부터 7번까지 순서대로** 실행합니다.
5. 결과 파일이 생성되면 마지막 셀에서 `proposal.json`, `.rbxlx`, 프로젝트 ZIP 등을 다운로드합니다. 생성에 실패하면 가능한 경우 실패 진단 ZIP이 제공됩니다.

처음 게임을 만들 때는 `RUN_MODE = "Full"`, `MODEL_PROFILE = "t4_local"`을 사용합니다.

### 실행 모드

| 모드 | 용도 |
| --- | --- |
| `Full` | 새 기획 생성 → Luau 소스 생성 → 정적 검사 → Rojo 빌드 |
| `Plan` | 기획 파일(`proposal.json`)만 생성 |
| `Revise` | 저장된 기획에 `PROMPT`의 수정 지시를 반영한 뒤 빌드 |
| `Execute` | 기존 `proposal.json`을 불러와 코드 생성 및 빌드 |
| `Audit` | 노트북이 지정한 저장소 `src/` 내 Luau 파일에 정적 검사 실행 |

`Revise`와 `Execute`에서는 이전에 저장한 계획 파일이 필요할 수 있습니다. `PLAN_FILE`을 지정하거나 노트북의 출력 폴더에 있는 `proposal.json`을 사용하세요. `Execute`는 유효한 계획 파일이 없으면 실행할 수 없습니다.

### Colab 설정 옵션

| 옵션 | 설명 |
| --- | --- |
| `RUN_MODE` | `Full`, `Plan`, `Revise`, `Execute`, `Audit` 중 선택 |
| `PROMPT` | 제작할 Roblox 게임의 설명. `Revise`에서는 수정 지시로 사용 |
| `PLAN_FILE` | 기존 `proposal.json`의 경로. 새 기획을 만드는 `Full`에서는 비워도 됨 |
| `ROBLOX_EXPERIENCE_NAME` | 생성할 게임/빌드 이름 |
| `GENRE` | `Action`, `RPG`, `Simulator`, `Tycoon`, `Obby`, `Survival`, `Minigame`, `Custom` 중 선택 |
| `MODEL_PROFILE` | `t4_local`(Colab 로컬 모델), `openai-compatible`(호환 서버 사용), `fast_test`(테스트용) |
| `REMOTE_BASE_URL` | 외부 또는 이미 실행 중인 OpenAI 호환 모델 서버 주소 |
| `REMOTE_API_KEY` | 해당 서버에 필요한 API 키. 필요하지 않으면 비워 둠 |
| `SEARCH_CREATOR_STORE` | UI에 표시되는 설정값. 현재 노트북에서는 다른 셀로 전달되지 않아 토글만으로 검색 동작이 바뀌지 않음 |
| `SAVE_TO_GOOGLE_DRIVE` | UI에 표시되는 설정값. 현재 노트북에서는 별도 Drive 저장 처리에 연결되지 않음 |

`fast_test`는 모델 추론 및 최종 게임 품질을 검증하는 용도가 아닙니다. 실제 게임 생성에는 준비된 추론 서버 또는 `t4_local`을 권장합니다.

## 2. 로컬 PC에서 CLI 사용하기

Python **3.10 이상** 및 Git이 필요합니다. (현재 코드에서 Python 3.10 이상의 타입 표기법을 사용합니다.) 프로젝트 루트에서 설치합니다.

```bash
git clone https://github.com/jujumelona/M.R.M-Make-Roblox-Mode.git
cd M.R.M-Make-Roblox-Mode
python -m pip install -e .
```

기획 및 소스 생성에는 사용할 AI 모델 서버가 준비되어 있어야 합니다. `.rbxlx` 파일을 만들려면 **Rojo CLI**도 필요합니다. Roblox Studio는 완성된 파일을 실제로 플레이테스트할 때 사용합니다.

### 기본 명령

```bash
# 게임 기획 생성
rmm plan "체크포인트와 타이머가 있는 50단계 점프맵"

# 기존 계획에 수정사항 반영
rmm revise "마지막 단계에 보상 UI를 추가해줘"

# 저장된 계획으로 코드 생성 및 빌드
rmm build

# Luau 파일 정적 검사
rmm analyze ./src

# Roblox 공식 문서 등을 검색하고 근거 기록 저장
rmm research "점프맵 체크포인트와 데이터 저장"
```

### CLI 명령별 옵션

| 명령 | 옵션 | 설명 |
| --- | --- | --- |
| `rmm plan "설명"` | `-o, --output 경로` | 출력 폴더 지정 (기본 `rmm-output`) |
| | `--mode new_experience\|existing_experience_addon` | 새 게임 또는 기존 게임에 추가할 기능으로 기획 |
| `rmm revise "수정 지시"` | `-p, --plan-file 파일` | 수정할 계획 파일 지정 (기본 `rmm-output/proposal.json`) |
| `rmm build` | `-p, --plan-file 파일` | 빌드할 기획 파일 지정 |
| | `-o, --output 경로` | 출력 폴더 지정 |
| | `--source-only` | `.rbxlx`를 컴파일하지 않고 소스만 생성 |
| `rmm analyze [폴더]` | 폴더 생략 가능 | 해당 폴더 아래 `*.luau` 파일 검사 (기본 현재 폴더) |
| `rmm research "설명"` | `-o, --output 파일` | 검색 결과 JSON 저장 경로 (기본 `rmm-output/pre_design_research.json`) |
| | `--offline` | 온라인 공식 문서 검색 대신 로컬 카탈로그 사용 |
| `rmm publish` | `-u, --universe ID` | 게시 대상 Universe ID (필수) |
| | `-p, --place ID` | 게시 대상 Place ID (필수) |
| | `-f, --file 파일` | 게시할 `.rbxlx` 파일 경로 (필수) |

각 명령의 도움말은 `rmm <명령> --help`로 확인할 수 있습니다.

### 로컬 모델 서버 설정

OpenAI 호환 API를 제공하는 서버를 실행하고, 필요에 따라 아래 환경변수를 지정합니다.

| 환경변수 | 설명 |
| --- | --- |
| `RMM_MODEL_BASE_URL` 또는 `ROBLOX_LLAMA_SERVER_URL` | 모델 서버 주소 |
| `RMM_MODEL_API_KEY` | 모델 서버 인증 키 (필요한 경우) |
| `RMM_MODEL_ID` | 사용할 모델 ID |
| `RMM_MODEL_TIMEOUT_SECONDS` | 모델 응답 제한 시간(초) |

서버는 실제 채팅 생성 요청에 응답할 수 있어야 합니다. URL만 입력했다고 모델이 준비되는 것은 아닙니다.

## 3. 생성 파일과 Roblox Studio 사용법

| 결과물 | 용도 |
| --- | --- |
| `proposal.json` | 생성된 기획 및 이후 `Revise` / `Execute` / `build`에서 사용할 계획 |
| `.rbxlx` | Roblox Studio에서 열 수 있는 Place 파일 (Rojo 빌드 성공 시) |
| 프로젝트 `.zip` | Rojo 프로젝트 소스와 빌드 산출물 |
| `verification_report.json` | 정적 검사 및 실행된 도구별 검사 결과 |
| 실패 진단 ZIP | 기획 또는 빌드 실패 시 원인 확인용 로그 (생성된 경우) |

Colab의 일반적인 출력 폴더는 `/content/rmm-output`이고, 로컬 CLI의 기본 출력 폴더는 `rmm-output/`입니다.

**Roblox Studio에서 실행**

1. 다운로드한 `.rbxlx`를 Roblox Studio에서 엽니다. 프로젝트 ZIP을 받은 경우 압축을 풀고 `compiled_place.rbxlx` 파일을 사용합니다.
2. Studio에서 **Play**를 눌러 실제 조작, UI, 게임 진행을 확인합니다.
3. 프로젝트를 수정하며 동기화하려면 Rojo CLI와 Studio용 Rojo 플러그인을 설치하고, 프로젝트 폴더에서 `rojo serve`를 실행한 뒤 Studio에서 연결합니다.
4. 선택적으로 프로젝트 ZIP의 `local_studio/run_smoke.ps1`을 Windows에서 실행해 Studio CLI 기반 구조 검사를 수행할 수 있습니다. 이는 실제 플레이테스트를 대신하지 않습니다.

### Roblox에 게시하기 (선택)

게시할 때만 Roblox Open Cloud API 키, Universe ID, Place ID가 필요합니다.

```bash
# API 키는 셸의 환경변수 ROBLOX_OPEN_CLOUD_API_KEY에 미리 설정
rmm publish --universe YOUR_UNIVERSE_ID --place YOUR_PLACE_ID --file path/to/game.rbxlx
```

게임을 로컬에서 생성하거나 Studio에서 여는 데는 Open Cloud API 키가 필요하지 않습니다.

## 4. 사용 시 주의사항

- `Full` 또는 `build` 성공은 **파일 생성과 오프라인 검사 성공**을 뜻합니다. Roblox Studio에서의 실제 게임플레이, 멀티플레이, DataStore 동작까지 검증했다는 의미는 아닙니다.
- `Plan`은 게임 파일을 빌드하지 않습니다. `Audit`도 새 게임을 생성하지 않습니다.
- `--source-only`는 `.rbxlx` 없이 소스 생성만 진행합니다.
- `Revise` 또는 `Execute` 시 `proposal.json`의 위치를 먼저 확인하세요.
- 문제가 발생하면 출력 폴더의 실패 로그와 검사 결과를 확인하세요.

## 라이선스

[MIT License](LICENSE)
