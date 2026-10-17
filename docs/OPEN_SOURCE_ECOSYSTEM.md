# 🌐 Roblox AI & Open-Source Ecosystem Guide

로블록스 생태계에서 공개되어 있는 **공식/커뮤니티 MCP 서버**, **Hugging Face LoRA 및 GGUF 모델**, **오픈소스 개발 도구체인**의 완벽 정리 가이드입니다.

---

## 1. 공개된 Roblox MCP (Model Context Protocol) 서버

AI 에이전트(Claude Desktop, Cursor, Antigravity 등)가 Roblox Studio 및 Luau 프로젝트를 직접 제어할 수 있도록 해주는 표준 MCP 서버들입니다:

| 프로젝트명 | 저장소 및 링크 | 언어 / 런타임 | 주요 기능 및 특징 |
|---|---|---|---|
| **Roblox 공식 Rust MCP** | [`Roblox/studio-rust-mcp-server`](https://github.com/Roblox/studio-rust-mcp-server) | Rust | **Roblox 공식 레퍼런스 구현체**. stdio를 통해 Studio 플러그인과 롱폴링 통신, 인스턴스/스크립트/플레이테스트 제어 |
| **RobloxStudio MCP** | [`boshyxd/robloxstudio-mcp`](https://github.com/boshyxd/robloxstudio-mcp) | Node.js (`npx`) | `npx -y robloxstudio-mcp@latest`로 실행 가능하며 Studio 내부 스크립트 탐색, 일괄 수정, 계층 구조 분석 지원 |
| **Weppy Roblox MCP** | [`hope1026/weppy-roblox-mcp`](https://github.com/hope1026/weppy-roblox-mcp) | TypeScript | Cursor 및 Claude Code 연동에 특화되어 지형(Terrain), 조명(Lighting), 스크립트 양방향 동기화 지원 |
| **Chrrxs Studio MCP** | [`Chrrxs/robloxstudio-mcp`](https://github.com/Chrrxs/robloxstudio-mcp) | Python | 런타임 디버깅, 스크린샷 캡처, 콘솔 로그 스트리밍, 멀티플레이어 테스트 평가에 특화 |
| **R.M.M 내장 MCP (본 저장소)** | [`roblox_mod_ai.mcp_server`](file:///c:/Users/kkk/Desktop/새%20폴더/roblox_mod_ai/mcp_server.py) | Python (Stdio) | 로컬 GGUF 모델을 위한 API 카탈로그 검색, Creator Store 애셋 탐색, Luau 정적 검증, .rbxlx 빌드, Open Cloud 배포 |

### 클라이언트 연동 예시 (`.mcp.json`)
```json
{
  "mcpServers": {
    "rmm-roblox-mod-ai": {
      "command": "python",
      "args": ["-m", "roblox_mod_ai.mcp_server"]
    },
    "roblox-studio-bridge": {
      "command": "npx",
      "args": ["-y", "robloxstudio-mcp@latest"],
      "env": { "PORT": "3000" }
    }
  }
}
```

---

## 2. 로블록스 오픈소스 도구체인 (Toolchain) 실연동 아키텍처

R.M.M은 [`RobloxToolchainManager`](../roblox_mod_ai/roblox_toolchain.py)를 통해 커뮤니티 표준 CLI 도구들을 프로젝트 빌드 및 검사 수명주기에 직접 연결하여 실행합니다:

| 도구명 | CLI 명령어 | 연동 파이프라인 단계 | 기능 설명 |
|---|---|---|---|
| **Rojo** | `rojo build`, `rojo serve` | **Step 5: 컴파일** | `default.project.json`을 기반으로 공식 네이티브 `.rbxlx` 바이너리/XML 생성 및 2-Way 실시간 동기화 |
| **Wally** | `wally install` | **Step 2: 의존성 설치** | `wally.toml`에 선언된 `Promise`, `Signal`, `TestEZ` 등의 오픈소스 패키지를 `Packages/`로 자동 다운로드 |
| **StyLua** | `stylua <dir>` | **Step 2c: 코드 포매팅** | 생성된 모든 Luau 스크립트를 로블록스 표준 코딩 스타일에 맞춰 자동 포매팅 |
| **Selene** | `selene <dir>` | **Step 3: 정적 린팅** | 컴파일 전 Luau 전용 초고속 정적 린터를 실행하여 버그 및 잠재적 런타임 오류 감지 |
| **Rokit / Aftman** | `rokit install`, `aftman install` | **도구체인 버전 고정** | 프로젝트 루트에 `rokit.toml`, `aftman.toml` 매니페스트를 자동 생성하여 팀/CI 환경에서 모든 도구를 원클릭 설치 |
| **TestEZ** | `roblox/testez` | **Step 4: 플레이테스트** | BDD 스타일(`describe`, `it`, `expect`) 단위 및 통합 테스트 실행 |

### 도구체인 자동 폴백 (Graceful Fallback)
시스템에 Rojo나 StyLua 등의 바이너리가 아직 설치되어 있지 않은 환경이라도 빌드가 실패하지 않도록 설계되었습니다:
- **Rojo 미설치 시**: 내장된 고속 Python XML `.rbxlx` 빌더가 대신 완전한 스튜디오 플레이스를 생성.
- **Selene 미설치 시**: 내장 정적 분석 엔진(`LuauStaticAnalyzer`)이 블록 밸런스, 비권장 글로벌, DataStore `pcall`을 전수 검사.
- **Wally 미설치 시**: 패키지 매니페스트(`wally.toml`)를 올바르게 보존하여 추후 `wally install`이 가능하도록 유지.

