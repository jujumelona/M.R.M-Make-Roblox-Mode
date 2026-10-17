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

## 2. Hugging Face에 공개된 Roblox Luau LoRA 및 GGUF 모델

작은 AI 모델(Small LLMs)이 로블록스 특유의 Luau API와 네트워킹 구조를 정확히 작성할 수 있도록 파인튜닝된 공개 가중치 모델들입니다:

| 모델 ID / Repo | 아키텍처 / 기반 모델 | 포맷 | VRAM 요구량 | 특징 및 용도 |
|---|---|---|---|---|
| [`preferredev/Roblox-Coder-v2_gguf`](https://huggingface.co/preferredev/Roblox-Coder-v2_gguf) | Qwen2.5-Coder-7B | GGUF (양자화) | **~6.0 GB** | **llama.cpp / llama-server 즉시 로드 가능**. 로블록스 스튜디오 Luau 스크립트 생성에 최적화 |
| [`squaredcuber/roblox-luau-mistral-7b-2`](https://huggingface.co/squaredcuber/roblox-luau-mistral-7b-2) | Mistral-7B-Instruct-v0.3 | PEFT LoRA | **~8.0 GB** | 로블록스 개발 문법 및 관용구 학습 LoRA 어댑터 |
| [`bostonstrong567/Luau-Qwen3-Coder-30B-A3B`](https://huggingface.co/bostonstrong567/Luau-Qwen3-Coder-30B-A3B) | Qwen2.5-Coder-32B | PEFT LoRA (Unsloth) | **~18.0 GB** | 수만 개의 실제 로블록스 게임 오픈소스 코드로 학습된 고성능 대형 어댑터 |
| [`thameurabderrahim/deepseek-coder-1.3b-roblox-lora`](https://huggingface.co/thameurabderrahim/deepseek-coder-1.3b-roblox-lora) | DeepSeek-Coder-1.3B | PEFT LoRA | **~3.5 GB** | 4GB 이하 저사양 GPU에서도 동작하는 초경량 Luau 코드 생성 어댑터 |

### 공개 학습 데이터셋 (Corpus)
* [`khtsly/roblox-luau-corpus`](https://huggingface.co/datasets/khtsly/roblox-luau-corpus): 약 19만 행, 수억 토큰 규모의 실제 로블록스 Luau 코드 및 API 문서 모음집.
* [`Pinkstack/luau-coding-instructions-pretrain`](https://huggingface.co/datasets/Pinkstack/luau-coding-instructions-pretrain): 레이캐스팅, 데이터스토어, 컴포넌트 시스템 관련 Instruction 파인튜닝 데이터.

---

## 3. 핵심 오픈소스 로블록스 도구체인 (Toolchain)

전문 로블록스 개발팀에서 표준으로 사용하는 오픈소스 스택입니다:

1. **Rojo (`rojo.space`)**: 파일 시스템 ↔ Studio 간 2-Way 실시간 동기화.
2. **Wally (`wally.run`)**: 로블록스 전용 패키지 관리자 (`wally.toml` 기반, `Promise`, `Signal`, `Knit` 등 관리).
3. **Lune / Remodel**: 스튜디오 외부 CLI 환경에서 `.rbxlx` XML 플레이스 파일을 조작하고 헤드리스 Luau를 실행하는 러너.
4. **Selene (`kampfkarren/selene`)**: Luau 전용 초고속 정적 코드 린터.
5. **StyLua (`JohnnyMorganz/StyLua`)**: 공인 Luau 코드 포매터.
6. **Rokit / Aftman**: 위 도구들의 버전을 고정하고 자동 설치해 주는 도구체인 매니저.
7. **TestEZ (`Roblox/testez`)**: BDD 스타일 (`describe`, `it`, `expect`) 로블록스 단위 테스트 프레임워크.
