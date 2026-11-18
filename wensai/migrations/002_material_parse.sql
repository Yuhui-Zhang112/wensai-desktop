-- B 的解析器标识、已结构化的 JSON 和写入时间；现存版本在首次解析前均为空。
ALTER TABLE material_versions ADD COLUMN parser_key TEXT;
ALTER TABLE material_versions ADD COLUMN parsed_json TEXT
    CHECK (parsed_json IS NULL OR json_valid(parsed_json));
ALTER TABLE material_versions ADD COLUMN parsed_at TEXT;
