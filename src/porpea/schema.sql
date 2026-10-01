-- จุดสนใจ (POI) จากทุกแหล่ง: 1 แถว = 1 จุด ต่อ 1 หมวด ต่อ 1 แหล่ง
CREATE TABLE IF NOT EXISTS poi (
    poi_uid      VARCHAR PRIMARY KEY,   -- '{source}:{category}:{source_id}'
    source       VARCHAR NOT NULL,      -- osm | google | manual
    source_id    VARCHAR NOT NULL,
    category     VARCHAR NOT NULL,      -- convenience_711, market, school, competitor, ...
    name         VARCHAR,
    brand        VARCHAR,
    lat          DOUBLE NOT NULL,
    lon          DOUBLE NOT NULL,
    h3_r9        VARCHAR NOT NULL,      -- H3 resolution 9 (~0.1 ตร.กม.)
    rating       DOUBLE,
    rating_count INTEGER,
    status       VARCHAR,               -- OPERATIONAL / CLOSED_PERMANENTLY / ...
    extra        VARCHAR,               -- JSON: tags/types/address ดิบ
    fetched_at   TIMESTAMP NOT NULL
);

-- ประชากรแบบกริด H3 (เช่น Kontur res 8 = ~0.74 ตร.กม.)
CREATE TABLE IF NOT EXISTS population_hex (
    h3          VARCHAR NOT NULL,
    res         INTEGER NOT NULL,
    population  DOUBLE NOT NULL,
    source      VARCHAR NOT NULL,
    PRIMARY KEY (h3, source)
);

-- โรงงาน (กรมโรงงานอุตสาหกรรม) — ใช้จำนวนคนงานเป็นตัวแทนแรงงานกะ
CREATE TABLE IF NOT EXISTS factory (
    factory_id  VARCHAR PRIMARY KEY,
    name        VARCHAR,
    lat         DOUBLE NOT NULL,
    lon         DOUBLE NOT NULL,
    h3_r9       VARCHAR NOT NULL,
    workers     INTEGER,
    industry    VARCHAR,
    source      VARCHAR,
    fetched_at  TIMESTAMP
);

-- ประกาศเช่าพื้นที่/แผงตลาด (เฟส 2)
CREATE TABLE IF NOT EXISTS rent_listing (
    listing_id  VARCHAR PRIMARY KEY,    -- '{source}:{id}'
    source      VARCHAR,
    title       VARCHAR,
    lat         DOUBLE,
    lon         DOUBLE,
    h3_r9       VARCHAR,
    price_thb_month DOUBLE,
    area_sqm    DOUBLE,
    listing_type VARCHAR,               -- shophouse | stall | kiosk | space
    url         VARCHAR,
    fetched_at  TIMESTAMP
);

-- ช่วงเวลาคนแน่น (Popular times) — จากบริการเสียเงิน/เก็บมือ (เฟส 2)
CREATE TABLE IF NOT EXISTS popular_times (
    poi_uid   VARCHAR,
    dow       INTEGER,                  -- 0=จันทร์ .. 6=อาทิตย์
    hour      INTEGER,
    busyness  INTEGER,                  -- 0..100
    source    VARCHAR,
    fetched_at TIMESTAMP,
    PRIMARY KEY (poi_uid, dow, hour)
);

-- จุดผู้สมัคร = 7-11 / ตลาด ที่จะให้คะแนน
CREATE TABLE IF NOT EXISTS candidate (
    candidate_id     VARCHAR PRIMARY KEY,
    anchor_poi_uid   VARCHAR,
    anchor_category  VARCHAR,
    name             VARCHAR,
    lat              DOUBLE,
    lon              DOUBLE,
    h3_r9            VARCHAR
);

-- feature แบบ long format (เพิ่ม feature ใหม่ไม่ต้องแก้ schema)
CREATE TABLE IF NOT EXISTS candidate_feature (
    candidate_id VARCHAR,
    feature      VARCHAR,
    value        DOUBLE,
    PRIMARY KEY (candidate_id, feature)
);

CREATE TABLE IF NOT EXISTS score_run (
    run_id      VARCHAR PRIMARY KEY,
    created_at  TIMESTAMP,
    config      VARCHAR                 -- JSON ของ weights/flags ที่ใช้
);

CREATE TABLE IF NOT EXISTS candidate_score (
    run_id       VARCHAR,
    candidate_id VARCHAR,
    score        DOUBLE,                -- 0..100
    rank         INTEGER,
    breakdown    VARCHAR,               -- JSON: คะแนนย่อยราย feature
    flags        VARCHAR,
    PRIMARY KEY (run_id, candidate_id)
);

-- ผลการลงพื้นที่จริง → ใช้ปรับน้ำหนักในรอบถัดไป
CREATE TABLE IF NOT EXISTS field_visit (
    visit_id            VARCHAR PRIMARY KEY,
    candidate_id        VARCHAR,
    visited_at          TIMESTAMP,
    time_slot           VARCHAR,        -- morning | noon | after_school | evening
    foot_traffic_15min  INTEGER,        -- นับคนเดินผ่านใน 15 นาที
    rent_quote_thb      DOUBLE,
    stall_available     BOOLEAN,
    verdict             VARCHAR,        -- go | maybe | no
    notes               VARCHAR
);

-- log การดึงข้อมูล (ไว้ตรวจสอบย้อนหลัง/คิดค่า API)
CREATE TABLE IF NOT EXISTS fetch_log (
    source     VARCHAR,
    query      VARCHAR,
    fetched_at TIMESTAMP,
    n_items    INTEGER,
    raw_path   VARCHAR
);

-- โซน = กลุ่มตลาดที่อยู่ใกล้กัน (คำนวณใหม่ทุก score run)
CREATE TABLE IF NOT EXISTS zone (
    run_id            VARCHAR,
    zone_id           VARCHAR,          -- Z001 = โซนอันดับ 1
    rank              INTEGER,
    score             DOUBLE,           -- 0..100 จากคะแนนตลาดในโซน
    n_markets         INTEGER,
    lat               DOUBLE,           -- จุดกึ่งกลางโซน
    lon               DOUBLE,
    best_candidate_id VARCHAR,
    best_score        DOUBLE,
    summary           VARCHAR,          -- JSON: จำนวน 7-11/CJ/ห้าง/... ในโซน (นับไม่ซ้ำ)
    PRIMARY KEY (run_id, zone_id)
);

CREATE TABLE IF NOT EXISTS zone_member (
    run_id        VARCHAR,
    zone_id       VARCHAR,
    candidate_id  VARCHAR,
    PRIMARY KEY (run_id, candidate_id)
);
