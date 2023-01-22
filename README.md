# copy_from_dropbox_camera

## インストール

```shell
wget https://github.com/koboriakira/copy_camerarolls/releases/download/v0.0.4/copy_camerarolls-x86_64-apple-darwin.zip -O - | sudo tar xvf - -C /usr/local/bin/
sudo chmod 775 /usr/local/bin/copy_camerarolls
```

## 使い方

```shell
copy_camerarolls {コピー元のディレクトリ} {コピー先のディレクトリ}
```

```shell
cargo run {コピー元のディレクトリ} {コピー先のディレクトリ}
```

だいたいこれで実行してる。

```shell
copy_camerarolls ~/Downloads /Volume/photo
```

## ビルド

```shell
cargo build --release --target=x86_64-apple-darwin 
zip --junk-paths copy_camerarolls-x86_64-apple-darwin target/x86_64-apple-darwin/release/copy_camerarolls
```