# Porpea — ระบบคัดกรองทำเลร้านเปาะเปี๊ยะทอด

ดึงข้อมูล 7-11, ตลาด, โรงเรียน, โรงงาน, ประชากร, คู่แข่ง ฯลฯ มาให้คะแนน "จุดผู้สมัคร" (หน้า 7-11 / ในตลาด)
แล้วออกเป็นรายการ Top-N + แผนที่ ไว้วางแผนลงพื้นที่ เริ่มที่ **ชลบุรี**

📄 แนวคิด, factor, แหล่งข้อมูล และโครงสร้างข้อมูล: [docs/DESIGN.md](docs/DESIGN.md)

## ติดตั้ง

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## ลองรันด้วยข้อมูลจำลอง (ไม่ต้องใช้เน็ต/API key)

```bash
porpea --config config/settings.yaml demo-seed
porpea analyze
porpea serve      # เปิดแผนที่ในเบราว์เซอร์ (อย่าดับเบิลคลิก map.html ตรงๆ พื้นหลังจะไม่ขึ้น)
```

## รันกับข้อมูลจริง

```bash
# 1) ประชากร (ดาวน์โหลด "Kontur Population: Thailand" จาก data.humdata.org)
porpea load-population ~/Downloads/kontur_population_TH_20231101.gpkg.gz

# 2) OSM (ฟรี)
porpea collect-osm                      # ทุกหมวด
porpea collect-osm --only market school # เฉพาะบางหมวด

# 3) โรงงาน (CSV จาก data.go.th — แก้ชื่อคอลัมน์ให้ตรงไฟล์)
porpea load-factories factories.csv --map id=เลขทะเบียน name=ชื่อโรงงาน lat=ละติจูด lon=ลองจิจูด workers=คนงานรวม

# 4) Google Places (เสียเงิน) — ดูจำนวน request ก่อน
export GOOGLE_MAPS_API_KEY=...
porpea collect-google --dry-run
porpea collect-google

# 5) วิเคราะห์ + export
porpea analyze
```

ผลลัพธ์อยู่ที่ `data/out/<run_id>/`:
- `top_candidates.csv` — import เข้า Google My Maps ได้ทันที
- `top_candidates.geojson` — เปิดใน kepler.gl / QGIS
- `map.html` — แผนที่ คลิกดูคะแนนย่อยแต่ละ feature (เปิดด้วย `porpea serve`)

ปรับ factor / รัศมี / น้ำหนัก ได้ที่ `config/settings.yaml` แล้วรัน `porpea features && porpea score && porpea export`

## ทดสอบ

```bash
pip install pytest && PYTHONPATH=src pytest -q
```
