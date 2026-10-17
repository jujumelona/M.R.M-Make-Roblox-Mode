# 🛠️ Roblox Development Methods in R.M.M

## 1. Server-Authoritative Architecture
모든 플레이어 데이터, 코인/재화, 체력 및 피격 판정은 서버(`ServerScriptService`)에서 독점적으로 소유 및 검증합니다:
- 클라이언트는 `UserInputService`로 입력을 감지하고 `RemoteEvent:FireServer()`로 공격 요청을 보냅니다.
- 서버는 요청 수신 시:
  1. 쿨다운 타이머 검사 (속도 핵 방지)
  2. 공격자와 대상 간의 CFrame 유클리드 거리 검사 (15스터드 이내, 리치 핵 방지)
  3. 유효한 경우에만 대상의 `Humanoid:TakeDamage()` 적용
  4. 모든 클라이언트에 `DamageEvent:FireAllClients()`로 시각/사운드 이펙트 브로드캐스트

## 2. Safe DataStore Persistence
`DataStoreService` 요청은 네트워크 실패나 로블록스 백엔드 스로틀링이 발생할 수 있으므로, 항상 안전 패턴을 적용합니다:
- `pcall`로 감싼 호출
- 최대 3회 지수 백오프 재시도
- `game:BindToClose`를 통한 서버 종료 시 퇴장 플레이어 데이터의 강제 플러시

## 3. Luau Typing and Static Linting
- 최상단 `--!strict` 타입 검사 활성화
- `wait()`, `spawn()`, `delay()` 대신 최신 태스크 스케줄러 `task.wait()`, `task.spawn()`, `task.defer()` 사용
- `game.Players`와 같은 직접 인덱싱 대신 `game:GetService("Players")` 사용
