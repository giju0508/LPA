# 0.18.1b1 Beta GitHub 게시 확인

게시 시각: **2026-10-19 19:06:48 KST**. 공개 저장소 [giju0508/LPA](https://github.com/giju0508/LPA)의
[v0.18.1b1 Beta](https://github.com/giju0508/LPA/releases/tag/v0.18.1b1)를 published prerelease로 게시했다.
Release ID: **417145562**. Release code commit: `ccb0bcb0c3b35bc7e714c7bcd1f52239a3ca5e87`.

기존 main에 release code를 fast-forward하고 annotated tag를 atomic push했다.
Release ZIP은 해당 코드로 빌드한 EXE와 게시 전 문서를 포함한다. 이 게시 확인
기록은 후속 문서 commit으로 저장하며 release code tag와 asset을 다시 만들지 않는다.

| 배포 파일 | bytes | SHA-256 |
|---|---:|---|
| LPA-0.18.1b1-Windows-x64-Beta.zip | 81691502 | `75687dcd84bdad2cccb774e9f4eaea719a1061a9ae3c533fd2c52a0468859130` |
| rocketcea-1.2.3.tar.gz | 69126862 | `66f306407f11ba36186342dc2716417d3a5c9d94c95b0c5663380091bb11caa9` |
| SHA256SUMS.txt | 266 | `a67e3822cf24f8363b1d325ad191910fb4178ff6e04a5378f44f94c213cb64e7` |

세 asset 모두 uploaded이며 서버 SHA-256 digest가 로컬 파일과 일치했다.
인증 없는 별도 API 요청에서 public repo, published prerelease, annotated tag의
code commit 일치와 가장 최근 게시 버전을 확인했다. 각 다운로드 URL의 HEAD는
**HTTP 200** 및 정확한 Content-Length를 반환했다. 전체 asset을 재다운로드한
검사와는 구분한다. prerelease를 안정판 Latest 배지로 주장하지 않는다.

근거: `github_publication.json`, `anonymous_publication_check.json`,
`publish_run.txt`, `public_check_run.txt`, `release_manifest.json`.

최종 전체 회귀 **867 passed / 176.43 s**, source/EXE GUI 정상 종료, 추출 native
계산 및 최종 소스/archive 일치를 통과했다. 실제 RP-1 사례의 3격자 결과는
**invalid**이며 온도 피크를 안전한 운전 온도로 보증하지 않는다. 원본 CFG는
변경하거나 저장소/배포 ZIP에 포함하지 않았다. 세부 사항은
[열전달 검토](../THERMAL_REVIEW_0181.md)에 기록한다.
