# 🎮 R.M.M (Roblox Mod & Experience AI)

> **M.M.M(Make Minecraft Mode)**의 핵심 아키텍처와 로컬 GGUF 모델 파이프라인을 재활용하여 구현된 **Roblox 전용 AI 경험 제작 자동화 프레임워크**입니다.

자연어 프롬프트만으로 게임플레이 기획, Roblox Creator Store 애셋 탐색, 타입 검증된 Luau 스크립트 생성, 정적 분석 및 플레이테스트를 수행하고, **Roblox Studio에서 즉시 열 수 있는 `.rbxlx` 및 Rojo 프로젝트 ZIP**을 출력합니다.

---

## 📊 M.M.M vs Roblox 버전 (R.M.M) 비교

| 항목 | 기존 M.M.M (Minecraft) | Roblox 버전 (R.M.M) | 세부 설명 |
|---|---|---|---|
| **AI 모델** | 로컬 GGUF + llama.cpp | **그대로 재사용** | `LlamaCppAdapter`를 통해 로컬 llama-server 호환 엔드포인트를 그대로 사용하며, 오프라인 및 고속 테스트 시뮬레이션 지원 |
| **기획·기능 분해** | 자연어 → 기능별 계획 | **그대로 재사용** | 자연어 요청을 게임플레이, 네트워크, 데이터스토어, UI, 오디오 서브시스템으로 분해 (`rmm/authored-plan-v1`) |
| **기존 자산 탐색** | CurseForge | **Roblox Creator Store** | Roblox Creator Store / Marketplace API 및 검증된 공식 3D 모델, 오디오, 이펙트 애셋 카탈로그 연동 |
| **코드 생성** | Java / Fabric | **Luau / Roblox API** | `--!strict` 타이핑, ServerScriptService (서버 권한), StarterPlayerScripts (클라이언트), ReplicatedStorage (공유 모듈/RemoteEvent) |
| **프로젝트 생성** | Fabric 프로젝트 | **Roblox Studio 프로젝트** | 업계 표준 Rojo `default.project.json` 생성 및 2-Way 라이브 싱크 지원 |
| **코드 검사** | Java / Gradle | **Luau 분석·타입 검사** | 정적 구문 분석, 블록 밸런스 검사, 비권장 글로벌(`wait()`, `spawn()`) 검출, DataStore `pcall` 누락 검사 (`LuauStaticAnalyzer`) |
| **실행 테스트** | Minecraft GameTest | **Roblox Studio Playtest** | TestEZ 호환 `.spec.luau` 테스트 스위트 생성 및 헤드리스 런타임 플레이테스트 시뮬레이터 실행 (`RobloxPlaytestRunner`) |
| **최종 출력** | JAR + ZIP | **.rbxlx + 프로젝트 ZIP** | Roblox Studio에서 즉시 더블클릭 실행 가능한 네이티브 XML 플레이스(`.rbxlx`) 및 Rojo 소스 ZIP 동시 생성 |
| **수정·재실행** | 기존 계획·체크포인트 재사용 | **동일한 방식 구현** | 체크포인트 기반으로 기존 계획을 보존하면서 피드백 반영 및 점진적 재빌드 (`session.revise()`) |

> [!NOTE]
> 사용자의 요구에 따라 무거운 2D 텍스처팩 생성 파이프라인은 제외하고, Roblox Creator Store 3D 모델/오디오 애셋 탐색과 경량 Luau 코드 생성에 집중하도록 최적화되었습니다.

---

## 🚀 빠른 시작 (Quickstart)

### 1. Python API

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
Rojo나 Luau CLI가 없어도 생성된 `<GameTitle>.rbxlx` 파일을 윈도우 탐색기에서 더블클릭하기만 하면 Roblox Studio가 바로 열리며, 모든 서비스와 스크립트, RemoteEvent가 즉시 세팅된 상태로 플레이테스트를 진행할 수 있습니다.

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
- `roblox_playtest_run`: TestEZ 헤드리스 플레이테스트 실행 및 오류 진단
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

전체 15개 테스트 스위트 (세션 수명주기, MCP JSON-RPC 서버, API 카탈로그, 오픈소스 도구체인 매니저(Rojo/Wally/Selene/StyLua/Rokit), 인게임 모딩 시스템, Luau 정적 검사기, Rojo/Wally/.rbxlx 생성기, Creator Store 검색기, 헤드리스 플레이테스터)가 포함되어 있습니다.

---

## 📄 라이선스

[MIT License](LICENSE)
