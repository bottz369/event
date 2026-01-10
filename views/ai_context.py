import streamlit as st
import os

# 読み込み対象の拡張子
TARGET_EXTENSIONS = {".py", ".sql", ".toml", ".md", ".txt", ".json"}

# 無視するディレクトリ (セキュリティとノイズ除去のため)
IGNORE_DIRS = {
    ".git", "__pycache__", "venv", ".venv", "data", 
    "assets", ".streamlit", "images" # 画像フォルダなども除外
}

# 無視するファイル (APIキーなどが含まれる可能性のあるもの)
IGNORE_FILES = {
    "secrets.toml", ".env", ".DS_Store", "app.db", "package-lock.json"
}

def get_project_structure(start_path="."):
    """ディレクトリ構成図（ツリー）を生成する"""
    structure = []
    for root, dirs, files in os.walk(start_path):
        # 無視リストに含まれるディレクトリを除外
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        level = root.replace(start_path, '').count(os.sep)
        indent = ' ' * 4 * (level)
        folder_name = os.path.basename(root)
        if folder_name == ".": folder_name = "(root)"
        
        structure.append(f"{indent}📂 {folder_name}/")
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if f not in IGNORE_FILES:
                structure.append(f"{subindent}📄 {f}")
    return "\n".join(structure)

def get_all_source_code(start_path="."):
    """全ソースコードを連結したテキストを生成する"""
    combined_text = []
    
    # 1. ディレクトリ構成図を追加
    combined_text.append("# === PROJECT STRUCTURE ===\n")
    combined_text.append(get_project_structure(start_path))
    combined_text.append("\n\n# === FILE CONTENTS ===\n")

    for root, dirs, files in os.walk(start_path):
        # 無視リストを除外
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            if file in IGNORE_FILES: continue
            
            # 拡張子チェック
            _, ext = os.path.splitext(file)
            if ext not in TARGET_EXTENSIONS: continue

            file_path = os.path.join(root, file)
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                # Geminiが理解しやすい区切り文字を使用
                combined_text.append(f"\n{'='*50}")
                combined_text.append(f"File Path: {file_path}")
                combined_text.append(f"{'='*50}\n")
                combined_text.append(content)
                combined_text.append("\n") # 余白
            except Exception as e:
                combined_text.append(f"# Error reading {file_path}: {e}")

    return "".join(combined_text)

def render_ai_context_page():
    st.title("🤖 AI Context Dump")
    st.caption("現在の最新コードを全取得し、Geminiへのプロンプト用に整形します。")
    
    # ボタンを押したら生成（ファイル数が多いと重くなる可能性があるため）
    if st.button("🔄 最新コードを取得して生成", type="primary"):
        with st.spinner("プロジェクト全体を解析中..."):
            full_context = get_all_source_code(".")
            
            # 文字数カウント
            char_count = len(full_context)
            st.success(f"生成完了！ (約 {char_count} 文字)")
            
            st.info("👇 以下のテキストエリアの右上のコピーボタンを押して、Geminiに貼り付けてください。")
            
            # プロンプトのヘッダーをつける
            prompt_header = (
                "あなたは優秀なPythonエンジニアです。\n"
                "現在開発中のStreamlitアプリの全コードとディレクトリ構成を共有します。\n"
                "まず、このコードの全貌を把握してください。\n"
                "把握したら『コードを確認しました。指示を待機します。』とだけ答えてください。\n\n"
                "---\n\n"
            )
            
            # コピー用テキストエリア (高さ最大)
            st.code(prompt_header + full_context, language="markdown")
            
            # バックアップとしてダウンロードボタンも用意
            st.download_button(
                label="📄 テキストファイルとしてダウンロード",
                data=prompt_header + full_context,
                file_name="project_context.txt",
                mime="text/plain"
            )
