use std::{env, fs, path::{Path, PathBuf}};

use chrono::{DateTime, Datelike, Utc};

fn main() {
    let args: Vec<String> = env::args().collect();
    let from = Path::new(args.get(1).expect("args is not exist"));
    let to_dir = Path::new(args.get(2).expect("args is not exist"));

    execute(from, to_dir);
}

/// 指定されたパスにあるファイルを、
fn execute(from: &Path, to_dir: &Path) {
    if from.is_dir() {
        // ディレクトリの場合は再帰的に処理
        for entry in from.read_dir().expect("read_dir call failed") {
            if let Ok(entry) = entry {
                execute(entry.path().as_path(), to_dir);
            }
        }
    } else {
        // ファイルを移動する
        copy_file(from, to_dir);
    }
}

/// 指定されたファイルを、指定されたディレクトリの日付別ディレクトリにコピーする
fn copy_file(file: &Path, to_dir: &Path) {
    let moved_dir = create_moved_dir(file, to_dir);
    fs::create_dir_all(&moved_dir).expect(&format!("Can't create dir: {:?}", moved_dir));

    let to_file = moved_dir.join(file.file_name().unwrap());
    copy_file_sub(file, &to_file);
}

/// 指定されたファイルをコピーする
fn copy_file_sub(origin_file: &Path, to_file: &PathBuf) {
    match fs::copy(origin_file, &to_file) {
        Err(why) => println!("Can't copy {:?}: {:?}", origin_file, why.kind()),
        Ok(_) => println!("{:?} -> {:?}", origin_file, &to_file),
    }
}

/// 指定されたファイルを配置するためのディレクトリパスを作成する
fn create_moved_dir(file: &Path, to_dir: &Path) -> PathBuf {
    let created_datetime_utc = get_created_day(file);
    let moved_dir = to_dir.join(format!(
        "{}/{:02}/{:02}",
        created_datetime_utc.year(),
        created_datetime_utc.month(),
        created_datetime_utc.day()
    ));
    moved_dir
}

/// 指定されたファイルの作成日を返却する
fn get_created_day(path: &Path) -> DateTime<Utc> {
    let metadata = path
        .metadata()
        .expect("has not metadata");
    let created_time = match metadata.created() {
        Ok(t) => t,
        // もしcreated_timeが存在しないような場合は、仕方なくmodified_timeを利用する
        Err(_) => metadata.modified().expect("created time and modified time are not exist"),
    };
    let utc_time: DateTime<Utc> = created_time.into();
    utc_time
}