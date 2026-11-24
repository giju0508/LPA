# LPA Windows 배포판 목록

2026-11-24 KST에 확인한 배포판과 소스 기록입니다. 날짜는 변경 이력에 기록된 KST 날짜입니다.

- 최신 로컬 배포 후보 **0.18.3b1**의 ZIP은 저장소 기준 `releases/archive/0.18.3b1/LPA-0.18.3b1-Windows-x64-Beta.zip`에 있습니다. 같은 폴더에 `LPA.exe`, 원본 체크섬, 빌드 검증 기록을 보관합니다.
- 최신 GitHub 공개본은 [0.18.1b1 Windows x64 Beta](https://github.com/giju0508/LPA/releases/tag/v0.18.1b1)입니다. 공개된 다섯 버전은 로컬 ZIP과 GitHub 첨부 파일의 SHA-256이 일치합니다.
- 표에 있는 ZIP의 로컬 위치는 `releases/archive/<버전>/<파일명>`입니다. Git에서 [SHA-256 목록](SHA256SUMS.txt)과 후보별 [원본 매니페스트](manifests)를 확인할 수 있습니다. Git 복제본에는 로컬 보관소의 바이너리가 포함되지 않습니다.

| 버전 | 날짜 (KST) | 배포 기록 | Git 소스 | 보관 ZIP 파일명 |
|---|---|---|---|---|
| 0.18.3b1 | 2026-11-21 | [로컬 배포 후보](manifests/0.18.3b1.json) | 소스 커밋 미확인 | `LPA-0.18.3b1-Windows-x64-Beta.zip` |
| 0.18.2b1 | 2026-11-20 | [로컬 배포 후보](manifests/0.18.2b1.json) | 소스 커밋 미확인 | `LPA-0.18.2b1-Windows-x64-Beta.zip` |
| 0.18.1b1 | 2026-10-19 | [GitHub 사전 릴리스](https://github.com/giju0508/LPA/releases/tag/v0.18.1b1) | [`v0.18.1b1`](https://github.com/giju0508/LPA/tree/v0.18.1b1) | `LPA-0.18.1b1-Windows-x64-Beta.zip` |
| 0.18.0b1 | 2026-10-19 | [GitHub 사전 릴리스](https://github.com/giju0508/LPA/releases/tag/v0.18.0b1) | [`v0.18.0b1`](https://github.com/giju0508/LPA/tree/v0.18.0b1) | `LPA-0.18.0b1-Windows-x64-Beta.zip` |
| 0.17.0b1 | 2026-10-19 | [GitHub 사전 릴리스](https://github.com/giju0508/LPA/releases/tag/v0.17.0b1) | [`v0.17.0b1`](https://github.com/giju0508/LPA/tree/v0.17.0b1) | `LPA-0.17.0b1-Windows-x64-Beta.zip` |
| 0.16.0b2 | 2026-10-19 | [GitHub 사전 릴리스](https://github.com/giju0508/LPA/releases/tag/v0.16.0b2) | [`v0.16.0b2`](https://github.com/giju0508/LPA/tree/v0.16.0b2) | `LPA-0.16.0b2-Windows-x64-Beta.zip` |
| 0.16.0b1 | 2026-10-19 | [GitHub 사전 릴리스](https://github.com/giju0508/LPA/releases/tag/v0.16.0b1) | [`v0.16.0b1`](https://github.com/giju0508/LPA/tree/v0.16.0b1) | `LPA-0.16.0b1-Windows-x64-Beta.zip` |
| 0.15.0 | 2026-10-11 | 로컬 배포 ZIP | 소스 커밋 미확인 | `LPA v0.15.0.zip` |
| 0.14.0 | 2026-10-11 | 로컬 배포 ZIP | 소스 커밋 미확인 | `LPA v0.14.0.zip` |
| 0.13.0 | 2026-10-08 | 로컬 배포 ZIP | 소스 커밋 미확인 | `LPA v0.13.0.zip` |
| 0.12.0 | 2026-10-08 | 로컬 배포 ZIP | 소스 커밋 미확인 | `LPA v0.12.0.zip` |
| 0.11.0 | 2026-09-18 | 로컬 배포 ZIP | 소스 커밋 미확인 | `LPA v0.11.0.zip` |
| 0.10.0 | 2026-07-21 | 로컬 배포 ZIP | [`v0.10.0`](https://github.com/giju0508/LPA/tree/v0.10.0) (백업 복구) | `LPA v0.10.0.zip` |
| 0.9.0 | 2026-07-20 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.8.0 | 2026-07-20 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.7.0 | 2026-07-14 | 소스 보관 | [`v0.7.0`](https://github.com/giju0508/LPA/tree/v0.7.0) | 미확인 |
| 0.6.1 | 2026-07-14 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.6.0 | 2026-07-13 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.5.0 | 2026-07-12 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.4.0 | 2026-07-12 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.3.0 | 2026-07-12 | 변경 이력 | 소스 커밋 미확인 | 미확인 |
| 0.2.0 | 2026-07-12 | 변경 이력 | 소스 커밋 미확인 | 미확인 |

## 소스와 배포 파일의 대조

- `v0.7.0`은 최초 Git 커밋에 나중에 부여한 태그입니다. `v0.10.0`은 7월 작업 폴더 백업에서 복구한 프로젝트 파일 69개의 스냅샷입니다. 백업에 들어 있던 EXE와 0.10.0 배포 ZIP 안의 EXE는 SHA-256 `303f701f079e25ff80bdf578c6887a9e6a2c613cbadc9821c81654ebde4566f2`로 일치합니다.
- 0.18.2b1과 0.18.3b1은 당시 패키징한 ZIP·EXE와 검증 기록이 남아 있습니다. 빌드 당시 소스에 정확히 대응하는 커밋은 확인되지 않았습니다. 11월 24일 IPA 변경은 11월 21일자 0.18.3b1 ZIP 이후의 작업입니다.
- 다음 버전은 빌드에 사용한 커밋에 태그를 달고 ZIP·검증 기록을 해당 버전 폴더에 보관합니다. GitHub에 게시한 버전은 첨부 ZIP의 해시를 대조한 뒤 표의 릴리스 링크를 갱신합니다.
