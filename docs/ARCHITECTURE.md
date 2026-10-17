# 🏛️ Architecture: M.M.M vs R.M.M (Roblox Version)

## 1. Core Comparison Matrix

| 항목 (Category) | 기존 M.M.M (Minecraft) | Roblox 버전 (R.M.M) | 세부 구현 및 특징 |
|---|---|---|---|
| **AI 모델** | 로컬 GGUF + llama.cpp | 로컬 GGUF + llama.cpp | `LlamaCppAdapter`를 통해 로컬 llama-server(`/v1/chat/completions`) 그대로 재사용. 오프라인 시뮬레이션 지원 |
| **기획·기능 분해** | 자연어 → 기능별 계획 | 자연어 → 기능별 계획 | 자연어 프롬프트를 게임플레이, 네트워크, 데이터스토어, UI, 오디오 서브시스템으로 분해 (`RobloxGameDesignPlanner`) |
| **기존 자산 탐색** | CurseForge | Roblox Creator Store | Roblox Creator Store / Marketplace API 검색 및 검증된 공식/커뮤니티 3D 모델/오디오 애셋 카탈로그 연동 (`RobloxCreatorStoreCatalog`) |
| **코드 생성** | Java / Fabric | Luau / Roblox API | `--!strict` 타이핑 적용, ServerScriptService (서버 권한), StarterPlayerScripts (클라이언트), ReplicatedStorage (공유 모듈/RemoteEvent) |
| **프로젝트 생성** | Fabric Gradle 프로젝트 | Roblox Studio 프로젝트 | 업계 표준 Rojo `default.project.json` 생성 및 2-Way 라이브 싱크 지원 |
| **코드 검사** | Java / Gradle (`./gradlew check`) | Luau 분석·타입 검사 | 정적 구문 분석, 블록 밸런스 검사, 비권장 글로벌(`wait()`, `spawn()`) 검출, DataStore `pcall` 누락 방지 (`LuauStaticAnalyzer`) |
| **실행 테스트** | Minecraft GameTest | Roblox Studio Playtest | TestEZ 호환 `.spec.luau` 테스트 스위트 생성 및 헤드리스 런타임 시뮬레이터 실행 (`RobloxPlaytestRunner`) |
| **최종 출력** | JAR + ZIP | .rbxlx + 프로젝트 ZIP | Roblox Studio에서 즉시 더블클릭 실행 가능한 네이티브 XML 플레이스(`.rbxlx`) 및 Rojo 소스 ZIP 동시 생성 |
| **수정·재실행** | 기존 계획·체크포인트 재사용 | 동일한 방식 구현 | `rmm/authored-plan-v1` 스키마 기반 체크포인트 저장, `session.revise()`로 기존 구조 보존형 점진적 수정 |

---

## 2. Roblox 공식 도구 및 외부 동기화 (External Synchronization)

### Rojo 라이브 동기화
Roblox 공식 생태계에서 지원하는 외부 파일 동기화 도구인 **Rojo** 규격을 준수합니다:
- `src/server/` → `ServerScriptService`: 서버 스크립트 (`*.server.luau`)
- `src/client/` → `StarterPlayer.StarterPlayerScripts`: 클라이언트 스크립트 (`*.client.luau`)
- `src/shared/` → `ReplicatedStorage`: 공유 모듈 (`*.luau`)
- `src/gui/` → `StarterGui`: UI 컨트롤러

이를 통해 개발자는 VS Code나 Antigravity 등의 외부 전문 IDE에서 Git 버전 관리를 수행하며, `rojo serve` 명령어로 Roblox Studio와 양방향 실시간 동기화를 진행할 수 있습니다.

### 네이티브 `.rbxlx` 자동 패키징
Rojo CLI나 별도 도구가 설치되어 있지 않은 환경에서도, 생성된 `.rbxlx` 파일만 더블클릭하면 Roblox Studio가 바로 실행되어 스크립트, 리모트 이벤트, 기본 베이스플레이트 및 스폰 포인트가 준비된 상태로 즉시 플레이테스트할 수 있습니다.

### Roblox Open Cloud API 연동
- **Place 배포**: `publish_place(universe_id, place_id, file_path)`로 Studio를 열지 않고도 클라우드 유니버스에 게임 빌드를 직접 배포 가능.
- **Creator Store 애셋 업로드**: Open Cloud Assets API 지원.
