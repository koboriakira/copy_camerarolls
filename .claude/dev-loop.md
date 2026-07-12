# dev-loop 完了契約

## done の定義
- PR を作成し `Closes #<Issue番号>` を本文に含める
- テストコードを伴う変更を行う（TDD: テスト→実装→リファクタリング）
- マージは人間ゲート

## VERIFY ゲート
CI 必須。ローカルで push 前に実行すべきコマンド:
```bash
ruff check .
pytest
```

osxphotos は `pyobjc-*` 等 macOS 専用パッケージに依存するため、CI は `macos-latest` ランナーで実行する（`.github/workflows/ci.yml` 参照）。

## 副作用の境界
- **Vault への書き込み: なし**
- **外部サービスへの送信: なし**
- **NAS（`/Volumes/photo` 等）への書き込み: あり**。ただし CI 環境では実機の NAS マウント・Photos ライブラリにアクセスできないため、ファイル操作ロジック（`dest_dir_for` / `copy_one` / 状態ファイルの読み書き等）はモック・`tmp_path` フィクスチャで検証すること。実機必須の統合確認はマージ後に人間が行う
- **Apple Photos ライブラリへの書き込み・削除: 絶対禁止**。osxphotos は読み取り専用ラッパーとして使うことが大前提（iCloud からのダウンロードや削除を自動化するコードを書かない）
