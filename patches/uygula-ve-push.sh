#!/usr/bin/env bash
# Mürekkep: bekleyen 5 commit'i main üzerine uygula, push et ve PR aç.
#
# Kullanım:
#   bash patches/uygula-ve-push.sh              # dal: seslendirme-ve-ui
#   bash patches/uygula-ve-push.sh benim-dalim  # özel dal adı
#
# Ön koşul: GitHub kimliği tanımlı olmalı (gh auth status).
set -euo pipefail

DAL="${1:-seslendirme-ve-ui}"
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KOK"

echo "» depo: $KOK"
git fetch origin
git checkout main
git pull --ff-only origin main
echo "» main: $(git rev-parse --short HEAD) (yamalar 87d94fc üzerine hazırlandı)"

git checkout -B "$DAL"

if git am patches/0*.patch; then
  echo "» 5 commit uygulandı"
else
  echo "» git am başarısız — tek parça yama deneniyor" >&2
  git am --abort || true
  git apply patches/kose-tum-degisiklikler.patch
  git add -A
  git commit -m "feat: seslendirme, mini oynatıcı, yazar adı biçimi ve okundu halkası"
fi

echo "» dalda uygulanacak commit'ler:"
git log --oneline "origin/main..HEAD"

git push -u origin "$DAL"
gh pr create --base main --head "$DAL" \
  --title "Seslendirme (Web Speech API), mini oynatıcı ve UI iyileştirmeleri" \
  --body-file patches/PR-GOVDE.md

echo "» tamam: $DAL push edildi ve PR açıldı"
