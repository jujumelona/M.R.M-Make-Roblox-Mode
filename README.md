# 🎮 R.M.M (Roblox Mod & Experience AI)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jujumelona/M.R.M-Make-Roblox-Mode/blob/main/R.M.M_Make_Roblox_Mode_Colab.ipynb)

> **M.M.M(Make Minecraft Mode)**의 핵심 아키텍처와 로컬 GGUF 모델 파이프라인을 재활용하여 구현된 **Roblox 전용 AI 경험 제작 자동화 프레임워크**입니다.

장르별 생성 템플릿으로 Luau·Rojo 프로젝트를 구성하고 요구사항 충족 검사를 수행합니다. 실제 `.rbxlx`는 Rojo로 컴파일된 경우에만 생성됩니다. **코드 생성·정적 검사·Rojo 빌드 성공은 오프라인 생성 완료일 뿐, 실제 게임플레이 완성이나 릴리스 인증이 아닙니다.** Roblox Studio 플레이테스트 결과는 별도 증거로 기록합니다. API 키나 테스트용 Place 게시를 기본 빌드에서 요구하지 않습니다.

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
| **실행 테스트** | Minecraft GameTest | **Roblox Studio Playtest** | 가짜 테스트 통과 금지. 기본은 오프라인 빌드 성공이며, 로컬 Studio CLI 구조 검사·Studio Play·내장 MCP 테스트는 별도 검증 |
| **최종 출력** | JAR + ZIP | **.rbxlx + 프로젝트 ZIP** | Rojo 성공 시 `.rbxlx`가 포함된 ZIP과 로컬 Studio 검사 도구 생성. 실제 플레이테스트는 미실행으로 별도 표기 |
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

### 3. Roblox Open Cloud 배포 (선택 사항, 게임 제작과 무관)
`RobloxOpenCloudClient`를 통해 Studio를 직접 켜지 않고도 GitHub Actions CI/CD 또는 터미널에서 Open Cloud API로 게임 버전을 자동 배포할 수 있습니다:
- 환경변수 설정: `ROBLOX_OPEN_CLOUD_API_KEY`, `ROBLOX_UNIVERSE_ID`, `ROBLOX_PLACE_ID`

## 상세 구현 설계 및 MCP 검증 (기본 적용)

모든 새 게임은 코드 작성 전에 `implementation_blueprint`를 생성합니다. 장르 키워드 몇 개를 감지했다고 사용자 게임을 완성했다고 판단하지 않습니다.

- **요구사항 추적**: 원문 요구 → 메커니즘 → 실제 모듈·파일·소유권 → 승인 조건. 담당 모듈이 없거나 기능이 누락되면 생성 전 차단합니다.
- **행동 상세화**: 각 메커니즘의 입력, 사전조건, 서버 상태 변경, 플레이어 피드백, 거부해야 할 조작, 저장 동작을 기획에 기록합니다.
- **통합 계약**: 코인→상점, 구매→전투, 전투→리더보드, 아레나 참가→전투→승패/재시작 등 요청된 기능 간 연결을 개별적으로 검증합니다. 임의의 상점/아레나를 모든 게임에 강제하지 않습니다.
- **수정 요청**: 기존 기능 목록에 한두 개 키워드만 이어 붙이지 않고 전체 원문+수정사항을 기준으로 모듈과 연결 관계를 재기획합니다.
- **오프라인 차단**: `roblox_plan_audit`가 이전 계획의 누락·오염을 확인하고, `quality_gates.py`가 생성된 Lua 소스/맵과 blueprint를 대조합니다. 변경된 `implementation_blueprint.json`은 Rojo 프로젝트 ZIP에도 저장됩니다.
- **실전 검증**: Studio MCP 또는 로컬 Studio CLI에서 플레이어 조작/서버 로그/멀티플레이/저장을 실제 실행해야 runtime-verified 상태를 인정합니다. 단순히 시나리오를 생성했다는 사실은 성공이 아닙니다.

RMM의 MCP 서버(`python -m roblox_mod_ai.mcp_server`)는 `roblox_plan_experience`, `roblox_plan_audit`, `roblox_api_search`, `roblox_official_docs_search`, `roblox_luau_validate`와 로컬 Studio 전용 `roblox_studio_inspect` / `roblox_studio_action`을 제공합니다. Studio에서 지원하는 실제 도구만 허용하며 입력·실행은 로컬 연결 및 명시적인 `allow_write=true`에 따라 동작합니다. Colab만 사용하는 경우 Studio MCP가 자동으로 연결되지는 않으며, 게시 API 키는 기본 코드 생성에 필요하지 않습니다.

## 범용 게임플레이 완료 계약 (기본 적용)

새로 생성하는 Roblox 게임은 사용자 요청을 먼저 분석한 후 `gameplay_contract`에 **입장/목표 → 조작·상호작용 → 상태 변화·피드백 → 성과/실패/보상 → 재진입**을 정의합니다. 모든 게임에 강제로 스토리 엔딩을 만들지 않습니다.

- **명시적 PvP 아레나**: 서버 `ArenaRoundService`가 두 명 이상 참가할 때 시작하고, 사망·상대 퇴장·시간 초과에 따른 승리/무승부, 결과 표시, 보상 및 다음 경기까지 처리합니다. 혼자 접속하면 대기하며 임의의 NPC를 만들지 않습니다. 서버는 경기 전 또는 참가자가 아닌 공격을 거부합니다.
- **오비·점프맵**: 마지막 체크포인트를 완료 조건으로 기록하고 완료 HUD에 반영합니다.
- **타이쿤·시뮬레이터·자유형 게임**: 모든 요청에 허위 승리 화면을 강제하지 않고, 반복되는 행동과 실제 상태 변화를 추적합니다.
- **새 게임의 목표 안내**: 호스트 `GameObjectiveController`가 원문 요구와 첫 행동을 보여주며, Studio에서 숨기거나 다시 표시할 수 있습니다.
- **기존 Experience 추가 기능**: 독립 게임 엔딩을 추가하거나 기존 월드를 교체하지 않습니다.
- **미지원·신규 게임 요소**: 실제 모듈 소유권과 관찰 가능한 결과가 필요한 모델 기획에 귀속됩니다. 요청된 서사 엔딩이 구현 근거 없이 누락되면 계획 검증이 실패합니다.

`gameplay_contract.json`과 `gameplay_playtest_scenarios.json`은 최종 프로젝트에 함께 보관합니다. `quality_gates.py`는 각 상태 전환·모듈 소유권·실제로 저장된 Luau 소스를 검사하고, 누락되면 빌드 성공 판정을 막습니다.

**검증 경계:** 생성된 테스트 시나리오는 *미실행*이며, 정적 소스 검증이나 Rojo 성공을 Roblox Studio에서의 실제 플레이/멀티플레이 성공으로 표시하지 않습니다. 런타임 검증에는 로컬 Studio 테스트가 필요합니다.

## 로컬 Roblox Studio 검증 (기본 제작에는 API 키 불필요)

- RMM은 Luau 생성, 정적 검사, Rojo 빌드와 ZIP 생성까지만 기본 실행합니다.
- 성공한 ZIP에 **compiled_place.rbxlx**가 들어 있습니다. Windows에서 압축 해제 후 Roblox Studio로 열어 Play할 수 있습니다.
- ZIP의 **local_studio/run_smoke.ps1**는 공식 Studio CLI로 로컬 Place의 인스턴스 구조를 검사합니다. **게임플레이·멀티플레이·DataStore 복원은 검증하지 않습니다.**
- AI가 실제 Studio에서 스크립트를 읽고 수정하거나 Play 테스트를 조작해야 할 경우, **Studio Assistant > Manage MCP Servers > Enable Studio as MCP server**를 켜고 신뢰하는 로컬 AI 클라이언트에서 MCP로 연결합니다. ZIP의 **local_studio/studio_mcp.windows.json**을 참고할 수 있습니다.
- 파일 실시간 동기화는 Rojo CLI와 Studio 플러그인을 설치해 rojo serve로 연결합니다.
- **Colab 자체에는 Windows Roblox Studio가 없으므로, 사용자의 PC에서 Studio를 실행하는 테스트는 별도 로컬 작업**입니다. 게임 게시·Open Cloud API 키는 개발의 필수 조건이 아닙니다.

관련 공식 문서: https://create.roblox.com/docs/studio/command-line-interface, https://create.roblox.com/docs/studio/mcp, https://rojo.space

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

### 공식 오픈소스 통합 (2026-10)

- [Roblox Studio MCP](https://create.roblox.com/docs/studio/mcp) — Studio 실행 중 로컬 연결. `tools/studio_mcp_config.py`.
- [Roblox 공식 문서](https://create.roblox.com/docs/llms.txt) — 허용된 공식 URL에서만 API 문서 검색. `roblox_official_docs_search`.
- [Creator Store](https://create.roblox.com/docs/cloud/reference/toolbox-service) — 실제 자산 검색/상세 확인. 검색 실패 시 가짜 ID를 반환하지 않음.
- [ProfileStore](https://github.com/MadStudioRoblox/ProfileStore) — 선택적 데이터 세션 관리. `RMM_STORAGE_BACKEND=profilestore`.
- [Fusion](https://github.com/dphfox/Fusion) — 선택적 반응형 HUD. `RMM_UI_BACKEND=fusion`.
- [Jest Roblox](https://roblox.github.io/jest-roblox/) — 테스트 전용 프로젝트에서 `Jest.runCLI` 사용.
- [Lune](https://lune-org.github.io/docs/) — CI에서 실제 상점 경제 로직 Luau 실행.
- [rbx-dom](https://github.com/rojo-rbx/rbx-dom) — Rojo 도구체인 간접 활용. 생성 파일은 별도의 컴파일 결과 감사 시행.

위 코드와 라이브러리의 설치·컴파일 성공만으로 실제 게임플레이 성공을 주장하지 않습니다.
세부 사항: [docs/EXTERNAL_INTEGRATIONS.md](docs/EXTERNAL_INTEGRATIONS.md).


### 프롬프트 우선 게임 설계 RAG

MMM의 요구사항 원장·호스트 소유 검색·증거 전달 패턴을 Roblox에 맞게 적용했습니다.
`rmm plan`은 계획 생성 전에 Roblox 공식 문서·로컬 API·재사용 코드 후보를 검색하며,
한국어 프롬프트의 원문과 미구현 요구를 보존합니다. 소형 모델은 근거가 되는
원문 구간을 지정한 영어 검색어만 제안할 수 있습니다.
실제 외부 근거를 못 찾은 경우 성공으로 위장하지 않습니다.
실행: `rmm research "50단계 점프맵에 펫과 상점 추가"`.
자세한 내용: [docs/PREDESIGN_ROBLOX_RAG.md](docs/PREDESIGN_ROBLOX_RAG.md).

### 범용 게임 로직 설계 및 부적합 코드 재사용 방지

로컬 소형 모델 주소(`ROBLOX_LLAMA_SERVER_URL` 또는 `RMM_MODEL_BASE_URL`)가 설정되어 있으면,
기존 장르 템플릿보다 원문 요구사항별 신규 모듈 설계를 우선합니다. 기존 외부 코드와
Creator Store 모델은 이름만 보고 재사용하지 않습니다. 새로 설계한 모듈은 범위가 제한된
World/Remote 계약을 검증한 후 Luau로 생성하며, Selene/StyLua/Rojo를 통과해야 합니다.
엔진 실제 게임플레이 검증은 별도로 필요합니다.
[상세 설계·제약](docs/UNIVERSAL_GAME_PIPELINE.md).
