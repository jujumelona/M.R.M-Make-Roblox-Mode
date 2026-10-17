from __future__ import annotations

import json
from pathlib import Path
import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "R.M.M_Make_Roblox_Mode_Colab.ipynb"


def build_notebook() -> None:
    nb = new_notebook()
    nb.metadata = {
        "accelerator": "GPU",
        "colab": {
            "name": "R.M.M_Make_Roblox_Mode_Colab.ipynb",
            "provenance": [],
            "toc_visible": True,
        },
        "kernelspec": {
            "display_name": "Python 3",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
        },
    }

    # 0. Title
    cell_0 = new_markdown_cell(
        source=(
            "# 🎮 R.M.M Make Roblox Mode (Roblox Mod & Experience AI)\n"
            "\n"
            "[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jujumelona/R.M.M-Make-Roblox-Mode/blob/main/R.M.M_Make_Roblox_Mode_Colab.ipynb)\n"
            "\n"
            "> 자연어 요구사항만으로 **Roblox Studio 경험 및 인게임 모딩 시스템**을 자동 기획하고, Luau 코드를 정적 검증 및 플레이테스트한 뒤 **즉시 열 수 있는 `.rbxlx` 및 Rojo 프로젝트 ZIP**을 생성하는 올인원 Colab 노트북입니다.\n"
            "\n"
            "- **Full**: 기획 생성부터 Luau 생성, 정적 분석, TestEZ 플레이테스트, `.rbxlx` 및 Rojo ZIP 빌드까지 전체 실행\n"
            "- **Plan**: 자연어 요구사항을 게임플레이, 네트워크(RemoteEvent), DataStore, UI 서브시스템으로 분해 및 기획안 생성\n"
            "- **Revise**: 이전 계획 또는 체크포인트를 바탕으로 사용자 피드백을 반영하여 부분 수정\n"
            "- **Execute**: 이미 확정된 `proposal.json` 계획 파일로 즉시 코드 생성 및 빌드 수행\n"
            "- **Audit**: 프로젝트 전체 검사 및 Luau 린트 / 구문 분석 실행\n"
        ),
        id="title",
    )

    # 1. Configuration
    cell_1 = new_code_cell(
        source=(
            "# @title 1. 실행 모드 및 게임 설정\n"
            "import os\n"
            "\n"
            'RUN_MODE = "Full" #@param ["Full", "Plan", "Revise", "Execute", "Audit"]\n'
            'PROMPT = "코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나 게임을 만들어줘." #@param {type:"string"}\n'
            'PLAN_FILE = "" #@param {type:"string"}\n'
            'ROBLOX_EXPERIENCE_NAME = "CombatArena" #@param {type:"string"}\n'
            'GENRE = "Action" #@param ["Action", "RPG", "Simulator", "Tycoon", "Obby", "Survival", "Minigame", "Custom"]\n'
            'MODEL_PROFILE = "t4_local" #@param ["t4_local", "fast_test", "openai-compatible"]\n'
            'REMOTE_BASE_URL = "" #@param {type:"string"}\n'
            'REMOTE_API_KEY = "" #@param {type:"string"}\n'
            'SEARCH_CREATOR_STORE = True #@param {type:"boolean"}\n'
            'RUN_PLAYTEST = True #@param {type:"boolean"}\n'
            'SAVE_TO_GOOGLE_DRIVE = False #@param {type:"boolean"}\n'
            "\n"
            'VALID_RUN_MODES = {"Full", "Plan", "Revise", "Execute", "Audit"}\n'
            "if RUN_MODE not in VALID_RUN_MODES:\n"
            '    raise ValueError(f"지원하지 않는 실행 모드: {RUN_MODE}")\n'
            "\n"
            'if RUN_MODE not in {"Execute", "Audit"} and not PROMPT.strip():\n'
            '    raise ValueError("선택한 실행 모드에서는 PROMPT를 입력해야 합니다.")\n'
            "\n"
            'os.environ["RMM_EXPERIENCE_NAME"] = ROBLOX_EXPERIENCE_NAME\n'
            'os.environ["RMM_GENRE"] = GENRE\n'
            "if REMOTE_BASE_URL:\n"
            '    os.environ["RMM_MODEL_BASE_URL"] = REMOTE_BASE_URL\n'
            "if REMOTE_API_KEY:\n"
            '    os.environ["RMM_MODEL_API_KEY"] = REMOTE_API_KEY\n'
        ),
        id="configuration",
    )

    # 2. Setup
    cell_2 = new_code_cell(
        source=(
            "# @title 2. GitHub 최신 main 설치 및 의존성 설정\n"
            "import importlib.util\n"
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            'REPO_DIR = Path("/content/R.M.M-Make-Roblox-Mode")\n'
            'REPO_URL = "https://github.com/jujumelona/R.M.M-Make-Roblox-Mode.git"\n'
            "\n"
            'IN_COLAB = "google.colab" in sys.modules or Path("/content").is_dir()\n'
            "\n"
            "if IN_COLAB:\n"
            '    if (REPO_DIR / ".git").is_dir():\n'
            '        subprocess.run(["git", "-C", str(REPO_DIR), "fetch", "origin", "+main:refs/remotes/origin/main"], check=True)\n'
            '        subprocess.run(["git", "-C", str(REPO_DIR), "checkout", "-f", "main"], check=True)\n'
            '        subprocess.run(["git", "-C", str(REPO_DIR), "reset", "--hard", "refs/remotes/origin/main"], check=True)\n'
            '        subprocess.run(["git", "-C", str(REPO_DIR), "clean", "-fd"], check=True)\n'
            "    elif REPO_DIR.exists():\n"
            '        raise RuntimeError(f"Git 저장소가 아닌 경로가 이미 존재합니다: {REPO_DIR}")\n'
            "    else:\n"
            '        subprocess.run(["git", "clone", "--depth", "1", "--branch", "main", REPO_URL, str(REPO_DIR)], check=True)\n'
            "\n"
            '    USED_COMMIT = subprocess.check_output(["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"], text=True).strip()\n'
            '    print("GitHub commit:", USED_COMMIT)\n'
            "\n"
            '    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(REPO_DIR)], check=True)\n'
            "    if str(REPO_DIR) not in sys.path:\n"
            "        sys.path.insert(0, str(REPO_DIR))\n"
            '    OUTPUT_ROOT = Path("/content/rmm-output")\n'
            "else:\n"
            "    REPO_DIR = Path.cwd()\n"
            '    OUTPUT_ROOT = REPO_DIR / "rmm-output"\n'
            '    print("Local workspace detected:", REPO_DIR)\n'
            "\n"
            "OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)\n"
            'print(f"Output directory initialized at: {OUTPUT_ROOT}")\n'
        ),
        id="setup",
    )

    # 3. Existing Input
    cell_3 = new_code_cell(
        source=(
            "# @title 3. 기존 입력 및 체크포인트 확인\n"
            "import json\n"
            "from pathlib import Path\n"
            "\n"
            "EXISTING_PLAN_DATA = None\n"
            'if RUN_MODE in {"Revise", "Execute"}:\n'
            "    target_plan_path = None\n"
            "    if PLAN_FILE.strip():\n"
            "        target_plan_path = Path(PLAN_FILE).expanduser().resolve()\n"
            "    else:\n"
            '        default_candidate = OUTPUT_ROOT / "proposal.json"\n'
            "        if default_candidate.is_file():\n"
            "            target_plan_path = default_candidate\n"
            "\n"
            "    if target_plan_path and target_plan_path.is_file():\n"
            "        try:\n"
            '            EXISTING_PLAN_DATA = json.loads(target_plan_path.read_text(encoding="utf-8"))\n'
            '            print(f"기존 계획 파일 로드 성공: {target_plan_path}")\n'
            '            print(f"  게임 제목: {EXISTING_PLAN_DATA.get(\'proposal\', {}).get(\'title\', \'Unknown\')}")\n'
            '            print(f"  서브시스템 수: {len(EXISTING_PLAN_DATA.get(\'proposal\', {}).get(\'subsystems\', []))}")\n'
            "        except Exception as exc:\n"
            '            print(f"계획 파일 로드 중 경고: {exc}")\n'
            "    else:\n"
            '        if RUN_MODE == "Execute":\n'
            '            raise FileNotFoundError(f"Execute 모드에는 유효한 PLAN_FILE이 필요합니다: {target_plan_path}")\n'
            '        print("기존 계획 파일이 없습니다. 새 세션으로 시작합니다.")\n'
            "else:\n"
            '    print(f"실행 모드: {RUN_MODE} (새 계획 생성)")\n'
        ),
        id="existing-input",
    )

    # 4. Registry
    cell_4 = new_code_cell(
        source=(
            "# @title 4. Roblox API 카탈로그 및 도구체인 상태 확인\n"
            "from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog\n"
            "from roblox_mod_ai.roblox_api_catalog import RobloxAPICatalog\n"
            "from roblox_mod_ai.roblox_toolchain import RobloxToolchainManager\n"
            "\n"
            "api_catalog = RobloxAPICatalog()\n"
            "services = api_catalog.list_services()\n"
            'print(f"Roblox API Catalog 로드 완료: {len(services)}개 핵심 서비스 인덱싱됨")\n'
            'print(f"  - 대표 서비스: {\', \'.join(services[:6])}...")\n'
            "\n"
            "creator_catalog = RobloxCreatorStoreCatalog()\n"
            'sample_models = creator_catalog.search_models("sword")\n'
            'print(f"Roblox Creator Store 카탈로그 연동 확인: \'sword\' 검색 시 {len(sample_models)}개 에셋 매칭")\n'
            "\n"
            "toolchain = RobloxToolchainManager()\n"
            "tool_status = toolchain.check_tools()\n"
            'print("Roblox Toolchain 상태:")\n'
            "for tool_name, available in tool_status.items():\n"
            '    icon = "사용 가능" if available else "미설치 (내장 폴백 동작)"\n'
            '    print(f"  - {tool_name}: {icon}")\n'
        ),
        id="registry",
    )

    # 5. Plan
    cell_5 = new_code_cell(
        source=(
            "# @title 5. 플랜 생성 및 서브시스템 분해\n"
            "import json\n"
            "from roblox_mod_ai.api import CompleteRobloxAISession\n"
            "\n"
            "session = CompleteRobloxAISession(\n"
            "    output_root=OUTPUT_ROOT,\n"
            "    model_profile=MODEL_PROFILE,\n"
            '    fast_mode=(MODEL_PROFILE == "fast_test"),\n'
            ")\n"
            "\n"
            "FINAL_PLAN_REPLY = None\n"
            'if RUN_MODE == "Audit":\n'
            '    print("Audit 모드: 계획 생성을 건너뜁니다.")\n'
            'elif RUN_MODE == "Execute":\n'
            "    if EXISTING_PLAN_DATA is not None:\n"
            '        plan_file = OUTPUT_ROOT / "proposal.json"\n'
            '        plan_file.write_text(json.dumps(EXISTING_PLAN_DATA, indent=2, ensure_ascii=False), encoding="utf-8")\n'
            "        FINAL_PLAN_REPLY = session.load_plan(plan_file)\n"
            '        print("기존 계획 로드 완료:")\n'
            "        print(FINAL_PLAN_REPLY.message)\n"
            "    else:\n"
            '        raise ValueError("Execute 모드에 필요한 계획 데이터가 없습니다.")\n'
            'elif RUN_MODE == "Revise":\n'
            "    if EXISTING_PLAN_DATA is not None:\n"
            '        plan_file = OUTPUT_ROOT / "proposal.json"\n'
            '        plan_file.write_text(json.dumps(EXISTING_PLAN_DATA, indent=2, ensure_ascii=False), encoding="utf-8")\n'
            "        session.load_plan(plan_file)\n"
            "    else:\n"
            "        session.plan(PROMPT)\n"
            '    print(f"수정 피드백 반영 중: {PROMPT}")\n'
            "    FINAL_PLAN_REPLY = session.revise(PROMPT)\n"
            "    print(FINAL_PLAN_REPLY.message)\n"
            "else:\n"
            '    print(f"자연어 계획 생성 중: {PROMPT}")\n'
            "    FINAL_PLAN_REPLY = session.plan(PROMPT)\n"
            '    print("=" * 60)\n'
            "    print(FINAL_PLAN_REPLY.message)\n"
            '    print("=" * 60)\n'
            "\n"
            'SAVED_PLAN_PATH = OUTPUT_ROOT / "proposal.json"\n'
            'print(f"계획 저장 경로: {SAVED_PLAN_PATH}")\n'
        ),
        id="plan",
    )

    # 6. Build
    cell_6 = new_code_cell(
        source=(
            "# @title 6. Luau 코드 생성, 정적 분석, 플레이테스트 및 빌드\n"
            "import json\n"
            "from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer\n"
            "\n"
            "BUILD_RESULT = None\n"
            "\n"
            'if RUN_MODE == "Plan":\n'
            '    print("Plan 모드: 빌드를 건너뜁니다.")\n'
            'elif RUN_MODE == "Audit":\n'
            '    print("전체 프로젝트 및 Luau 스크립트 정적 감사(Audit) 실행 중...")\n'
            "    analyzer = LuauStaticAnalyzer()\n"
            '    src_dir = REPO_DIR / "src"\n'
            "    total_files = 0\n"
            "    issues_found = 0\n"
            "    if src_dir.is_dir():\n"
            '        for luau_file in src_dir.rglob("*.luau"):\n'
            "            total_files += 1\n"
            '            code = luau_file.read_text(encoding="utf-8")\n'
            "            res = analyzer.analyze(code, filename=luau_file.name)\n"
            "            if not res.valid or res.warnings:\n"
            "                issues_found += len(res.errors) + len(res.warnings)\n"
            '                print(f"  [{luau_file.name}] 오류: {len(res.errors)}, 경고: {len(res.warnings)}")\n'
            '    print(f"Audit 완료: 총 {total_files}개 파일 검사, {issues_found}개 이슈 감지됨.")\n'
            "else:\n"
            "    if FINAL_PLAN_REPLY is None:\n"
            '        raise RuntimeError("빌드할 계획이 없습니다. 5번 셀(플랜 준비)을 먼저 실행해 주세요.")\n'
            "\n"
            '    print("빌드 시작: Luau 코드 생성 -> 정적 분석 -> TestEZ 플레이테스트 -> .rbxlx / ZIP 컴파일")\n'
            "    BUILD_RESULT = session.build(FINAL_PLAN_REPLY, run_name=ROBLOX_EXPERIENCE_NAME)\n"
            "\n"
            '    print("=" * 60)\n'
            '    print(f"빌드 상태: {\'성공 (SUCCESS)\' if BUILD_RESULT.success else \'실패 (FAILED)\'}")\n'
            '    print(f"Roblox Place (.rbxlx): {BUILD_RESULT.rbxlx_path}")\n'
            '    print(f"Rojo 프로젝트 ZIP: {BUILD_RESULT.project_zip_path}")\n'
            '    print(f"생성된 Luau 파일 수: {len(BUILD_RESULT.generated_files)}개")\n'
            "    if BUILD_RESULT.playtest_report:\n"
            "        pt = BUILD_RESULT.playtest_report\n"
            '        print(f"플레이테스트 결과: {\'통과\' if pt.passed else \'실패\'} (테스트 {pt.tests_run}개 중 {pt.tests_passed}개 성공)")\n'
            '    print("=" * 60)\n'
        ),
        id="build",
    )

    # 7. Download
    cell_7 = new_code_cell(
        source=(
            "# @title 7. 결과물 다운로드 (.rbxlx 및 Rojo ZIP)\n"
            "from pathlib import Path\n"
            "\n"
            "DOWNLOAD_TARGETS = []\n"
            "\n"
            'if RUN_MODE == "Plan":\n'
            "    if SAVED_PLAN_PATH.is_file():\n"
            "        DOWNLOAD_TARGETS.append(SAVED_PLAN_PATH)\n"
            "elif BUILD_RESULT is not None and BUILD_RESULT.success:\n"
            "    if BUILD_RESULT.rbxlx_path and Path(BUILD_RESULT.rbxlx_path).is_file():\n"
            "        DOWNLOAD_TARGETS.append(Path(BUILD_RESULT.rbxlx_path))\n"
            "    if BUILD_RESULT.project_zip_path and Path(BUILD_RESULT.project_zip_path).is_file():\n"
            "        DOWNLOAD_TARGETS.append(Path(BUILD_RESULT.project_zip_path))\n"
            "    if SAVED_PLAN_PATH.is_file():\n"
            "        DOWNLOAD_TARGETS.append(SAVED_PLAN_PATH)\n"
            "elif SAVED_PLAN_PATH.is_file():\n"
            "    DOWNLOAD_TARGETS.append(SAVED_PLAN_PATH)\n"
            "\n"
            "if not DOWNLOAD_TARGETS:\n"
            '    print("다운로드할 결과 파일이 없습니다.")\n'
            "else:\n"
            '    print(f"총 {len(DOWNLOAD_TARGETS)}개의 결과물이 준비되었습니다:")\n'
            "    for target in DOWNLOAD_TARGETS:\n"
            '        print(f"  - {target.name} ({target.stat().st_size:,} bytes): {target}")\n'
            "\n"
            "    try:\n"
            "        from google.colab import files as colab_files\n"
            "        for target in DOWNLOAD_TARGETS:\n"
            '            print(f"Google Colab 다운로드 시작: {target.name}")\n'
            "            colab_files.download(str(target))\n"
            "    except (ImportError, Exception):\n"
            '        print("로컬 환경에서는 위 파일 경로에서 직접 접근하거나 더블클릭할 수 있습니다.")\n'
        ),
        id="download",
    )

    # 8. Boundaries
    cell_8 = new_markdown_cell(
        source=(
            "## 🎮 생성된 Roblox 산출물 활용 안내\n"
            "\n"
            "### 1. Roblox Studio에서 즉시 열기 (.rbxlx)\n"
            "다운로드된 `<GameName>.rbxlx` 파일은 Roblox의 표준 XML 플레이스 파일입니다.\n"
            "- **실행 방법**: Windows 탐색기 또는 Mac Finder에서 `.rbxlx` 파일을 더블클릭하면 Roblox Studio가 바로 실행됩니다.\n"
            "- **구성 요소**:\n"
            "  - `ServerScriptService`: 서버 권한 게임플레이 서비스 및 인게임 모딩 시스템 (`ModdingSystem.luau`)\n"
            "  - `StarterPlayer.StarterPlayerScripts`: 클라이언트 컨트롤러 및 UI 바인딩\n"
            "  - `ReplicatedStorage`: 서버-클라이언트 공유 모듈 및 자동 바인딩된 `RemoteEvent`\n"
            "  - `StarterGui`: 게임 HUD 및 화면 UI\n"
            "\n"
            "### 2. Rojo로 실시간 2-Way 라이브 싱크 (`<GameName>_rojo_project.zip`)\n"
            "외부 코드 편집기(VS Code, Cursor, Antigravity)에서 프로젝트를 개발하려면:\n"
            "1. ZIP 파일의 압축을 풉니다.\n"
            "2. 터미널에서 다음 명령어를 실행합니다:\n"
            "   ```bash\n"
            "   rojo serve\n"
            "   ```\n"
            "3. Roblox Studio에서 Rojo 플러그인을 열고 **Connect**를 누르면 파일 변경사항이 Studio에 실시간 반영됩니다.\n"
            "\n"
            "### 3. 소형 AI 모델(Small AI) 및 MCP 연동\n"
            "R.M.M은 Claude Desktop, Cursor 등에서 사용할 수 있는 MCP 서버(`roblox_mod_ai/mcp_server.py`) 및 API 카탈로그를 내장하고 있어, 7B~14B급 소형 AI도 API 실수 없이 완벽하게 Luau 코드를 작성하고 플레이테스트할 수 있습니다.\n"
        ),
        id="boundaries",
    )

    nb.cells = [
        cell_0,
        cell_1,
        cell_2,
        cell_3,
        cell_4,
        cell_5,
        cell_6,
        cell_7,
        cell_8,
    ]

    with open(NOTEBOOK_PATH, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    print(f"Notebook written to: {NOTEBOOK_PATH}")


if __name__ == "__main__":
    build_notebook()
