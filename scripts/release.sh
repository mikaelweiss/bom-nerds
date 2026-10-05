#!/bin/sh
set -eu

root=$(dirname "$(dirname "$(realpath "$0")")")
database="$root/scripture.db"
dist="$root/dist"

[ -f "$database" ] || { echo "No scripture.db to release." >&2; exit 1; }

if [ "${1:-}" != "--no-upload" ]; then
    [ "$(git -C "$root" branch --show-current)" = main ] || { echo "Release from main." >&2; exit 1; }
    [ -z "$(git -C "$root" status --porcelain)" ] || { echo "Commit your changes first." >&2; exit 1; }
    git -C "$root" fetch --quiet origin main
    [ "$(git -C "$root" rev-parse HEAD)" = "$(git -C "$root" rev-parse origin/main)" ] || { echo "Push main first." >&2; exit 1; }
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
rm -rf "$dist"
mkdir -p "$dist" "$work/json"

sqlite3 "$database" "vacuum into '$work/scripture.db'"

for table in $(sqlite3 "$work/scripture.db" "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by rowid"); do
    sqlite3 -json "$work/scripture.db" "select * from $table" > "$work/json/$table.json"
done

zip -q -j "$dist/scripture-db.zip" "$work/scripture.db" "$root/LICENSE-DATA.txt" "$root/CREDITS.md"
zip -q -j "$dist/scripture-json.zip" "$work"/json/*.json "$root/LICENSE-DATA.txt" "$root/CREDITS.md"
ls -lh "$dist"

[ "${1:-}" = "--no-upload" ] && exit 0

commit=$(git -C "$root" rev-parse HEAD)
tag="data-$(date -u +%Y-%m-%d-%H%M%S)"
gh release create "$tag" "$dist/scripture-db.zip" "$dist/scripture-json.zip" \
    --repo mikaelweiss/bom-nerds --target "$commit" --title "$tag" \
    --notes "scripture.db and a JSON export of every table, as of $commit. The data is CC BY 4.0: CREDITS.md, inside each zip, lists the credit every source requires."
