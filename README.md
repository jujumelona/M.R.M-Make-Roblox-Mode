# 🎮 R.M.M (Roblox Mod & Experience AI)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jujumelona/M.R.M-Make-Roblox-Mode/blob/main/R.M.M_Make_Roblox_Mode_Colab.ipynb)

> **M.M.M(Make Minecraft Mode)**의 핵심 아키텍처와 로컬 GGUF 모델 파이프라인을 재활용하여 구현된 **Roblox 전용 AI 경험 제작 자동화 프레임워크**입니다.

장르별 생성 템플릿으로 Luau·Rojo 프로젝트를 구성하고 요구사항 충족 검사를 수행합니다. 실제 `.rbxlx`는 Rojo로 컴파일된 경우에만 생성되며, **실제 Roblox 엔진 및 Studio 멀티플레이 테스트 전에는 완료로 판정하지 않습니다.**

---

## 📊 M.M.M vs Roblox 버전 (R.M.M) 비교

| 항목 | 기존 M.M.M (Minecraft) | Roblox 버전 (R.M.M) | 세부 설명 |
|---|---|---|---|
| **AI 모델** | 로컬 GGUF + llama.cpp | **그대로 재사용** | `LlamaCppAdapter`가 존재하지만 현재 기본 기획·코드 생성은 장르 템플릿 기반이며 완전한 소형 AI 자율 구현 엔진은 아님 |
| **기획·기능 분해** | 자연어 → 기능별 계획 | **그대로 재사용** | 자연어 요청을 게임플레이, 네트워크, 데이터스토어, UI, 오디오 서브시스템으로 분해 (`rmm/authored-plan-v1`) |
| **기존 자산 탐색** | CurseForge | **Roblox Creator Store** | Roblox Creator Store / Marketplace API 및 검증된 공식 3D 모델, 오디오, 이펙트 애셋 카탈로그 연동 |
| **코드 생성** | Java / Fabric | **Luau / Roblox API** | `--!strict` 타이핑, ServerScriptService (서버 권한), StarterPlayerScripts (클라이언트), ReplicatedStorage (공유 모듈/RemoteEvent) |
| **프로젝트 생성** | Fabric 프로젝트 | **Roblox Studio 프로젝트** | 업계 표준 Rojo `default.project.json` 생성 및 2-Way 라이브 싱크 지원 |
| **코드 검사** | Java / Gradle | **Luau 분석·타입 검사** | 정적 구문 분석, 블록 밸런스 검사, 비권장 글로벌(`wait()`, `spawn()`) 검출, DataStore `pcall` 누락 검사 (`LuauStaticAnalyzer`) |
| **실행 테스트** | Minecraft GameTest | **Roblox Studio Playtest** | 가짜 시뮬레이션 성공 제거. Open Cloud 실제 서버와 StudioTestService 멀티플레이 테스트 증거를 요구 |
| **최종 출력** | JAR + ZIP | **.rbxlx + 프로젝트 ZIP** | Rojo 실제 빌드 성공 시 `.rbxlx`와 동일 프로젝트 ZIP 생성. 실패 시 대체 XML 성공 처리 금지 |
| **수정·재실행** | 기존 계획·체크포인트 재사용 | **동일한 방식 구현** | 체크포인트 기반으로 기존 계획을 보존하면서 피드백 반영 및 점진적 재빌드 (`session.revise()`) |

> [!NOTE]
> 사용자의 요구에 따라 무거운 2D 텍스처팩 생성 파이프라인은 제외하고, Roblox Creator Store 3D 모델/오디오 애셋 탐색과 경량 Luau 코드 생성에 집중하도록 최적화되었습니다.

---

## 🚀 빠른 시작 (Quickstart)

### 1. Google Colab (클릭 한 번으로 즉시 실행)

M.M.M과 동일하게 브라우저에서 설치 없이 실행할 수 있는 공식 Colab 인터랙티브 노트북을 제공합니다:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jujumelona/M.R.M-Make-Roblox-Mode/blob/main/R.M.M_Make_Roblox_Mode_Colab.ipynb)

1. **상단 뱃지 클릭**: Colab에서 [`R.M.M_Make_Roblox_Mode_Colab.ipynb`](R.M.M_Make_Roblox_Mode_Colab.ipynb) 열기
2. **원하는 모드 선택**: `Full` (기획 + 빌드), `Plan` (기획만), `Revise` (수정), `Audit` (정적 감사)
3. **자연어 프롬프트 입력**: "코인 수집, 상점, 리더보드가 포함된 검투 아레나 만들어줘"
4. **셀 순차 실행**: 생성된 `.rbxlx` 및 프로젝트 ZIP 파일이 브라우저로 자동 다운로드됩니다.

---

### 2. Python API

```python
from roblox_mod_ai import CompleteRobloxAISession

# 1. 세션 초기화 (로컬 GGUF llama-server 연동)
session = CompleteRobloxAISession(output_root="rmm-output")

# 2. 자연어 기획 및 기능 분해 (Plan)
plan = session.plan("코인 수집, 상점, 리더보드가 포함된 검투 경기장 아레나 만들어줘")
print(plan.message)

# 3. 계획 수정 및 보완 (Revise)
revised = session.revise("마법 지팡이와 쿨다운 UI도 추가해줘")
print(revised.message)

# 4. Luau 코드 생성, 정적 분석, 플레이테스트 및 .rbxlx 빌드 (Build)
result = session.build(revised)

print(f"✅ 빌드 성공: {result.success}")
print(f"🎮 Roblox Place (.rbxlx): {result.rbxlx_path}")
print(f"📦 Rojo 프로젝트 ZIP: {result.project_zip_path}")
```

### 2. CLI 명령어

```bash
# 1. 게임 기획 생성
rmm plan "코인 수집과 상점이 있는 검투 아레나"

# 2. 피드백을 반영하여 기획 수정
rmm revise "마법 스킬과 파티클 이펙트 추가"

# 3. 전체 프로젝트 빌드 (.rbxlx 및 ZIP 출력)
rmm build

# 4. Luau 정적 검사 및 린트 실행
rmm analyze src/

# 5. (선택) Roblox Open Cloud로 클라우드 즉시 배포
rmm publish --universe <UNIVERSE_ID> --place <PLACE_ID> --file rmm-output/CombatArena.rbxlx
```

---

## 🛠️ Roblox 공식 도구 및 외부 동기화

### 1. Rojo 2-Way 라이브 동기화
Roblox 공식 도구 규격을 준수하는 `default.project.json`을 자동 생성합니다:
- `src/server/` ➔ `ServerScriptService`
- `src/client/` ➔ `StarterPlayer.StarterPlayerScripts`
- `src/shared/` ➔ `ReplicatedStorage`
- `src/gui/` ➔ `StarterGui`

외부 에디터(VS Code, Antigravity 등)에서 Git으로 코드를 관리하고, 터미널에서 `rojo serve`를 실행하면 Roblox Studio와 실시간 양방향으로 동기화됩니다.

### 2. 무설치 네이티브 `.rbxlx` 더블클릭 실행
**Rojo CLI가 필수입니다.** 자체 XML 대체 생성기는 릴리스 경로에서 사용하지 않습니다. Roblox Studio에서 열리는 것만으로 실제 게임 동작이 검증되지 않습니다.

### 3. Roblox Open Cloud 배포
`RobloxOpenCloudClient`를 통해 Studio를 직접 켜지 않고도 GitHub Actions CI/CD 또는 터미널에서 Open Cloud API로 게임 버전을 자동 배포할 수 있습니다:
- 환경변수 설정: `ROBLOX_OPEN_CLOUD_API_KEY`, `ROBLOX_UNIVERSE_ID`, `ROBLOX_PLACE_ID`

## 🧠 작은 AI(Small Models) 지원: MCP & Skills 생태계

7B~14B급 로컬 소형 AI 모델(Qwen, MiMo, Llama 등)이 한 번에 방대한 게임 코드를 작성하면 환각(Hallucination)이나 문법 오류가 발생합니다. R.M.M은 **MCP(Model Context Protocol)**와 **Skills(절차적 가이드)**를 통해 소형 모델이 세부 도구를 호출하며 완벽하게 작업할 수 있도록 지원합니다.

### 1. `.mcp.json` 및 MCP Server (`rmm-mcp`)
Claude Desktop, Cursor, Antigravity 등 표준 MCP 클라이언트에 즉시 등록 가능한 도구 세트:
- `roblox_api_search`: Roblox 엔진 API 시그니처 및 예제 검색 (틀린 메서드 호출 방지)
- `roblox_creator_store_search`: 공식 Creator Store 3D 모델 및 사운드 에셋 검색
- `roblox_luau_validate`: 작성한 Luau 코드의 블록 밸런스 및 린트 정적 검사
- `roblox_plan_experience`: 자연어 요구사항을 서브시스템으로 분해
- `roblox_project_write` / `read`: 프로젝트 내 스크립트 안전 읽기/쓰기
- `roblox_playtest_run`: 실제 엔진을 실행하지 않으므로 미검증 반환. Studio/Cloud 테스트는 별도 실행
- `roblox_rbxlx_build`: `.rbxlx` 및 프로젝트 ZIP 컴파일
- `roblox_open_cloud_deploy`: Roblox 클라우드 즉시 배포

### 2. 단계별 Skills (`skills/`)
소형 AI가 작업을 분할 수행할 수 있도록 표준 절차서 제공:
- [`skills/plan-roblox-experience/SKILL.md`](skills/plan-roblox-experience/SKILL.md): 서브시스템 기획 및 리모트 이벤트 설계
- [`skills/generate-luau-service/SKILL.md`](skills/generate-luau-service/SKILL.md): DataStore pcall 및 서버 권한 안티치트 패턴
- [`skills/generate-luau-client/SKILL.md`](skills/generate-luau-client/SKILL.md): UserInputService 및 TweenService UI 컨트롤러
- [`skills/validate-and-playtest/SKILL.md`](skills/validate-and-playtest/SKILL.md): 자체 오류 수정(Self-Correction) 피드백 루프
- [`skills/deploy-roblox-place/SKILL.md`](skills/deploy-roblox-place/SKILL.md): .rbxlx 패키징 및 Open Cloud 배포

---

## 🧪 테스트 실행

```bash
pytest tests -v
```

Python CI는 엔진 실행 없이 소스/계약을 검증합니다. 테스트 스위트 (세션 수명주기, MCP JSON-RPC 서버, API 카탈로그, 오픈소스 도구체인 매니저(Rojo/Wally/Selene/StyLua/Rokit), 인게임 모딩 시스템, Luau 정적 검사기, Rojo/Wally/.rbxlx 생성기, Creator Store 검색기, 헤드리스 플레이테스터)가 포함되어 있습니다.

---

## 검증 및 릴리스 기준 (2026-10)

- Python CI: Win/Linux × Python 3.10~3.13. 게임 엔진 런타임을 실행하지 않음.
- Rojo Smoke CI: 실제 Rokit/Wally/StyLua/Rojo로 릴리스 및 Studio E2E 테스트 장소를 컴파일.
- source_only: 소스 생성 전용으로 release success=false.
- Release: StyLua, Wally, Selene, luau-analyze, Rojo, Open Cloud 서버 테스트 및 StudioTestService 멀티플레이 테스트 증거 모두 필요.
- 별도 테스트 Place, Roblox API 키, Studio 실행이 없으면 런타임 미검증으로 실패. 사용자는 기존 생성물을 새 엔진에서 다시 생성해야 함.
- 상세 설명: [docs/VERIFICATION_PIPELINE.md](docs/VERIFICATION_PIPELINE.md)

## 📄 라이선스

[MIT License](LICENSE)
