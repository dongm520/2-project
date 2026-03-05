import os
import json
import pandas as pd

# ==========================
# 경로 설정
# ==========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_ROOT = os.path.join(BASE_DIR, "data")                # 원본 데이터 위치
SCHEMA_ROOT = os.path.join(BASE_DIR, "data", "datasets") # 스키마 저장 위치

os.makedirs(SCHEMA_ROOT, exist_ok=True)


# ==========================
# 파일 로딩 (csv + xlsx)
# ==========================
def load_dataframe(file_path):
    try:
        if file_path.endswith(".csv"):
            try:
                return pd.read_csv(file_path, encoding="utf-8")
            except UnicodeDecodeError:
                return pd.read_csv(file_path, encoding="cp949")
        elif file_path.endswith(".xlsx"):
            return pd.read_excel(file_path)
        else:
            return None
    except Exception as e:
        print(f"❌ 파일 로딩 실패: {file_path} → {e}")
        return None


# ==========================
# 스키마 생성
# ==========================
def create_schema(file_path):
    df = load_dataframe(file_path)
    if df is None:
        return None

    schema = {
        "file_name": os.path.basename(file_path),
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": []
    }

    for col in df.columns:
        schema["columns"].append({
            "name": col,
            "dtype": str(df[col].dtype),
            "sample_values": df[col].dropna().astype(str).head(3).tolist(),
            "null_count": int(df[col].isnull().sum())
        })

    return schema


# ==========================
# 전체 실행
# ==========================
def build_all_schemas_and_metadata():

    metadata = {
        "total_files": 0,
        "datasets": []
    }

    for file in os.listdir(DATA_ROOT):
        file_path = os.path.join(DATA_ROOT, file)

        # csv, xlsx만 처리
        if file.endswith((".csv", ".xlsx")):

            print(f"📊 처리 중: {file}")

            schema = create_schema(file_path)

            if schema:
                # 스키마 저장
                schema_filename = file.replace(".csv", "").replace(".xlsx", "") + "_schema.json"
                schema_path = os.path.join(SCHEMA_ROOT, schema_filename)

                with open(schema_path, "w", encoding="utf-8") as f:
                    json.dump(schema, f, indent=4, ensure_ascii=False)

                print(f"✅ 스키마 저장 완료 → {schema_path}")

                # 메타데이터 추가
                metadata["datasets"].append({
                    "file_name": file,
                    "rows": schema["row_count"],
                    "columns": schema["column_count"]
                })

                metadata["total_files"] += 1


    # 메타데이터 저장
    metadata_path = os.path.join(SCHEMA_ROOT, "metadata.json")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, ensure_ascii=False)

    print(f"📁 메타데이터 저장 완료 → {metadata_path}")


# 실행
build_all_schemas_and_metadata()