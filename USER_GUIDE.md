# 🚀 Master User Guide: CryptoStream AI (Institutional Edition)

ยินดีต้อนรับสู่ระบบ **CryptoStream AI** - นี่คือคู่มือปฏิบัติการสำหรับผู้ดูแลระบบและผู้ใช้งานระดับสูง เพื่อให้การรันระบบเป็นไปอย่างถูกต้องและเสถียรที่สุดครับ

---

## 🏗️ 1. ลำดับการเริ่มใช้งาน (Boot Sequence)
เพื่อให้ระบบทำงานได้สมบูรณ์ (โดยเฉพาะ AI ที่ต้องต่อกับฐานข้อมูล) **ต้องรันตามลำดับนี้เท่านั้นครับ:**

### Step 1: Infrastructure (Docker)
รันระบบฐานข้อมูลและ Message Broker ทั้งหมด
```bash
docker compose up -d
```
*รอประมาณ 30-60 วินาทีเพื่อให้ Kafka และ Postgres พร้อมทำงาาน*

### Step 2: Intelligence Bridge (MCP Server)
เริ่มระบบตัวกลางสำหรับเชื่อมต่อ AI กับฐานข้อมูล
```bash
# เปิด CMD ใหม่
python -m uvicorn mcp_server.main:app --host 127.0.0.1 --port 8000
```

### Step 3: Core Chat Backend
เริ่มระบบวิเคราะห์และแชทหลัก
```bash
# เปิด CMD ใหม่
python chat_server.py
```

### Step 4: Tactical UI (Frontend)
เริ่มหน้าจอการใช้งาน (Tactical Terminal)
```bash
# เปิด CMD ใหม่
cd frontend
npm run dev
```

---

## 🔗 2. สารบัญลิงก์ (System URL Directory)

รวบรวมลิงก์ทั้งหมดที่คุณต้องเข้าถึงเพื่อใช้งานและดูแลระบบ:

| URL                      | Interface Name                | Purpose (หน้าที่ของระบบ) |
| :---                     | :---                          | :--- |
| **http://localhost:8888**| **Tactical Terminal (Main)**  | หน้าจอหลักสำหรับพูดคุยกับ AI และดู Market Trends |
| **http://localhost:8000**| **MCP Dashboard**             | ระบบตัวกลางที่ AI ใช้ดึงข้อมูลจาก Postgres (เช็คว่า Online ไหม) |
| **http://localhost:3000**| **Grafana Metrics**           | ดูสถิติการไหลของข้อมูล (Postgres/Kafka Health) [User: admin / Pass: institutional-secret] |
| **http://localhost:9090**| **Prometheus Telemetry**      | ตรวจสอบ Metrics ของระบบ Infrastructure โดยตรง |

---

## 📟 3. ตารางรวมคำสั่งที่ใช้บ่อย (CMD Cheat Sheet)

| Command | Action | Description |
| :--- | :--- | :--- |
| `docker compose ps` | Check Status | ตรวจเช็คว่า Container ทุกตัว (Kafka, Postgres) รันอยู่ไหม |
| `docker compose logs -f` | View Logs | ดู Log แบบ Real-time เพื่อหาจุดเกิดปัญหา |
| `python scripts/check_db.py` | DB Audit | ตรวจสอบว่ามีข้อมูลอัปเดตเข้าฐานข้อมูลล่าสุดเมื่อไหร่ |
| `python tests/test_e2e.py` | E2E Test | รันระบบทดสอบเพื่อยืนยันว่าดาต้าไหลตั้งแต่ต้นสายจนถึงปลายสาย |

---

## ☁️ 3.5 การจัดเก็บข้อมูลระยะยาว (Google BigQuery)
ระบบรองรับการ Archive ข้อมูลจาก Local Data Lake ขึ้นสู่ Cloud เพื่อการวิเคราะห์ระดับ Global (OLAP):
- **Dataset:** `crypto_stream`
- **Table:** `raw_trades`
- **Airflow DAG:** `datalake_to_bigquery` (รันอัตโนมัติทุกวันเวลา 02:00 AM)
- **Purpose:** ใช้สำหรับวิเคราะห์ข้อมูลย้อนหลังหลายปี และเชื่อมต่อกับ Tool อย่าง Looker Studio หรือ Tableau
- **Action:** หากต้องการรันแมนนวล ให้รันผ่าน Airflow UI หรือคำสั่ง:
  `docker exec airflow-scheduler airflow dags trigger datalake_to_bigquery`

---

## 🎭 4. คู่มือการคุยกับ AIคู่ใจ (Persona Guide)

AI ของเรามีความสามารถพิเศษในการสลับโหมดตามเจตนาของคุณ (Dual-Mode):

*   **โหมดนักวางแผน (Quant Mode):** ถามเกี่ยวกับราคา, แนวโน้ม, หรือวาฬ (เช่น *"วิเคราะห์ BTC ให้หน่อย"*) AI จะให้ตารางแผนเทรดที่อ่านง่าย
*   **โหมดวิศวกร (System Mode):** ถามเกี่ยวกับเทคโนโลยีหรือตัวตน (เช่น *"คุณรันบนไหน?"*) AI จะอธิบายสถาปัตยกรรม Gemini 2.5 Flash และ MCP อย่างละเอียด

---

> [!TIP]
> **Pro Tip:** หาก Chat Server รันไม่ได้ หรือ AI ค้าง ให้ลองใช้ไฟล์ `debug.bat` หรือ `run_ui.bat` ในหน้าแรกเพื่อ Reset ระบบโดยรวมอัตโนมัติครับ
