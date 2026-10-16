# SyncLab

Windows에서 영상과 외부 녹음을 소리로 맞추는 프로그램입니다.

## 설치

1. [다운로드](https://github.com/contentriumkorea/synclab/releases/latest)에서 `SyncLab-Windows-x64.zip`을 받습니다.
2. 압축을 모두 풀고 `SyncLab/SyncLab.exe`를 실행합니다. `_internal` 폴더가 함께 있어야 합니다.
3. 다음 버전부터는 상단 **업데이트** 버튼으로 확인·설치·재시작할 수 있습니다.

## 프리미어 사용 순서

1. 카메라 영상과 외부 오디오를 시퀀스에 넣습니다.
2. 프리미어 **파일 → 내보내기 → Final Cut Pro XML**로 저장합니다.
3. SyncLab에서 XML을 열고 오디오 준비가 끝나면 **자동 싱크**를 누릅니다.
4. 그룹·파형·미일치·드리프트 경고를 확인합니다. 필요하면 수동으로 보정합니다.
5. **XML 저장**으로 다른 이름으로 저장합니다.
6. 프리미어 **파일 → 가져오기**에서 결과 XML을 열고 새 Synced 시퀀스를 확인합니다.

원본 미디어는 기존 폴더에 유지됩니다. XML은 배치 정보이며 영상 파일이 아닙니다.

## 그룹과 주의할 점

- 공통 소리가 확인되는 클립끼리는 그룹 안에서 정렬합니다.
- 기준 음원과 연결되지 않는 별도 그룹도 내부 정렬하되 그룹 사이의 실제 시간은 추정하지 않습니다.
- 어떤 소스와도 맞지 않는 클립은 결과 끝에 보존합니다.
- 모든 녹음의 완벽한 싱크를 보장하지 않습니다. 드리프트·구간별 편차·미일치는 직접 확인하세요.
- 시간 늘이기/줄이기, 자동 카메라 컷, Premiere 내부 확장 패널은 제공하지 않습니다.
- XML이 지원하지 않는 효과는 Premiere에서 변환 경고가 나타날 수 있습니다.
- 파일당 최대 6시간, 최대 200개 소스입니다. 분석 캐시는 `%LOCALAPPDATA%/SyncLab/audio-cache-v1`에 보관합니다.

## 업데이트

**업데이트**를 누르면 이 저장소의 최신 버전을 확인합니다. 새 버전을 선택하면
GitHub의 SHA256 정보로 ZIP을 검증하고 별도 폴더에 풀어 실행 검사 후 다시 시작합니다.
미저장 작업은 먼저 저장/취소할 수 있습니다. 실패하면 현재 작업과 기존 앱을 유지합니다.
업데이트 파일은 `%LOCALAPPDATA%/SyncLab/updates`에 보관합니다.
이전 실행 파일을 열어도 검증된 새 버전으로 연결됩니다. 자동 백그라운드 다운로드는 하지 않습니다.

## 개발

Python 3.12 / Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pyinstaller
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m synclab
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm SyncLab.spec
```

버전은 `synclab/version.py`에서 관리합니다. 배포 ZIP 이름은 업데이트 호환성을 위해 유지합니다.
서드파티 고지와 라이선스는 `THIRD_PARTY.md` 및 배포본의 `LICENSES`를 참고하세요.
