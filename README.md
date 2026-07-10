# copy_camerarolls

Apple Photos → NAS 増分バックアップ。osxphotos で Photos ライブラリを読み取り、
YYYY/MM/DD 構造で NAS にコピーする。

## 前提

- macOS + Apple Photos
- ターミナルに **Full Disk Access** が付与されていること（Photos.sqlite の読み取りに必要）
- NAS がマウント済み（デフォルト: `/Volumes/photo`）

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

```bash
# 通常実行（/Volumes/photo にバックアップ）
python3 backup.py

# 別のパスに出力
python3 backup.py --dest /Volumes/other-nas

# テスト（コピーせずに計画だけ表示）
python3 backup.py --dry-run

# 10枚だけ試す
python3 backup.py --dry-run --limit 10

# 状態をリセットして全件再処理
python3 backup.py --reset-state
```

## 仕組み

- osxphotos で Photos ライブラリの全写真を列挙
- 各写真の撮影日から `YYYY/MM/DD/` にコピー
- Live Photo の動画ペア（.MOV）も同じディレクトリにコピー
- UUID ベースの状態ファイル（`.backup_state.json`）で増分管理
- iCloud のみの写真はスキップ（ローカルにある写真のみ対象）
