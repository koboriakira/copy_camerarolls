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

## 削除候補の一覧表示（offload_candidates.py）

ディスク容量が逼迫してきたときに、「NASへの転送を検証済みで、ローカル削除しても
安全なもの」を一覧表示する読み取り専用スクリプト。**削除は一切自動化しない**。
一覧を見てユーザー自身が Photos.app 上で手動削除する。

```bash
# 一覧表示（既定: /Volumes/photo）
python3 offload_candidates.py

# 動画のみに絞る
python3 offload_candidates.py --type video

# 少数件でテスト
python3 offload_candidates.py --limit 10
```

判定条件（すべて満たすものだけを「安全」として出す）:

1. ローカルにダウンロード済み
2. NAS の状態ファイル（`.backup_state.json`）に UUID が記録済み
3. 実際に NAS 上にファイルが存在し、ローカルとファイルサイズが一致する

条件1・2を満たしても条件3を満たさない（NAS側にファイルが無い／サイズが不一致）
場合は、安全リストとは別の「警告」セクションに出す。状態ファイルの内容を
鵜呑みにせず実ファイルで再検証することで、誤って未バックアップのファイルを
「安全」と報告しないようにしている。
