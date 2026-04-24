# 🚀 Master User Guide: CryptoStream AI (Institutional Edition)

ยินดีต้อนรับสู่ระบบ **CryptoStream AI** - นี่คือคู่มือปฏิบัติการสำหรับผู้ดูแลระบบและผู้ใช้งานระดับสูง เพื่อให้การรันระบบเป็นไปอย่างถูกต้องและเสถียรที่สุดครับ

---

## 🏗️ 1. ลำดับการเริ่มใช้งาน (Boot Sequence)
เพื่อให้ระบบทำงานได้สมบูรณ์และข้อมูล Market Data (DXY, SP500) ไหลลื่น **ควรทำตามลำดับนี้ครับ:**

### 🐳 วิธีที่ 1: รันผ่าน Docker (แนะนำสำหรับใช้งานทั่วไป)
วิธีนี้จะรัน Infra ทั้งหมดรวมถึง Backend และ Frontend ให้อัตโนมัติ
```bash
docker compose up -d
```
*💡 ระบบจะเริ่ม Ingestion Service อัตโนมัติเพื่อดึงข้อมูลจาก Binance และ Yahoo Finance*

### 🛠️ วิธีที่ 2: รันแบบ Manual (แนะนำสำหรับนักพัฒนา)
หากต้องการแก้ไขโค้ดและเห็นผลทันที ให้รันแยกดังนี้:

1.  **Infrastructure:** `docker compose up -d postgres redis kafka`
2.  **AI Intelligence Bridge:** 
    ```bash
    python -m uvicorn mcp_server.main:app --host 127.0.0.1 --port 8000
    ```
3.  **Core Backend & API Server:** 
    ```bash
    python chat_server.py
    ```
4.  **Market Screener & Tactical Engine (MANDATORY):**
    ```bash
    python screener_pipeline.py
    ```
    *🚨 สำคัญมาก: ตัวนี้จะคอยดึงข้อมูลหุ้นและคริปโตเข้า Database ล่วงหน้า หากไม่รันตัวนี้ หน้าต่าง Alpha Tactics (Trading Tactics) จะโหลดช้ามากจนถึงขั้น Timeout ค้าง (Skeleton boxes)*

5.  **Neural Sniper Loop:** 
    ```bash
    python production_sniper_loop.py
    ```

6.  **Frontend UI:** 
    ```bash
    cd frontend && npm run dev
    ```

---

## 📈 2. การตรวจสอบความพร้อมของข้อมูล (Health Check)
หลังจาก Boot ระบบแล้ว ให้ตรวจสอบส่วนประกอบสำคัญดังนี้:

1.  **Market Indices (DXY, S&P 500):** 
    *   ไปที่หน้า **News Sentiment Hub**
    *   ตรวจสอบว่าการ์ด "US Dollar Index" และ "Market Benchmarks" แสดงราคาปัจจุบัน (ไม่ใช่ "Syncing Tape...")
2.  **AI Verdict:** 
    *   ตรวจสอบว่ามีบทวิเคราะห์ AI Intelligence สำหรับดอลลาร์ปรากฏขึ้น
3.  **Live Signals:** 
    *   ตรวจสอบแถบ Signal Feed ว่ามีสัญญาณจาก MT5 (XM Broker) ไหลเข้ามาหรือไม่

---

## 🔗 3. สารบัญลิงก์ (System URL Directory)

| URL                      | Interface Name                | Purpose (หน้าที่ของระบบ) |
| :---                     | :---                          | :--- |
| **http://localhost:80**  | **Tactical Terminal (Docker)**| หน้าจอหลักเมื่อรันผ่าน Docker Compose |
| **http://localhost:5173**| **Tactical Terminal (Dev)**   | หน้าจอหลักเมื่อรันผ่าน `npm run dev` |
| **http://localhost:8888**| **FastAPI Backend**           | API หลักสำหรับ Chat และ Market Data |
| **http://localhost:8000**| **MCP Dashboard**             | ระบบตัวกลางที่ AI ใช้ดึงข้อมูลจาก Postgres |
| **http://localhost:3000**| **Grafana Metrics**           | ดูสถิติการไหลของข้อมูล (Postgres/Kafka Health) |

---

## 📟 3. ตารางรวมคำสั่งที่ใช้บ่อย (CMD Cheat Sheet)

| Command | Action | Description |
| :--- | :--- | :--- |
| `docker compose ps` | Check Status | ตรวจเช็คว่า Container ทุกตัว (Kafka, Postgres) รันอยู่ไหม |
| `docker compose logs -f` | View Logs | ดู Log แบบ Real-time เพื่อหาจุดเกิดปัญหา |
| `tail -f sniper_scanner.log` | Monitor AI | ติดตามการสแกนตลาดของ Neural V8 แบบ Real-time |
| `python intelligence/ml/train_v8.py` | Model Retrain | สั่งเทรนโมเดลใหม่ด้วยข้อมูล Big Data 10 ปีย้อนหลัง |

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

## 🏛️ 5. ฟีเจอร์ระดับสถาบัน (Institutional Intelligence)

ระบบได้รับการอัปเกรดให้รองรับฟีเจอร์ระดับกองทุน (Hedge Fund Grade):

### 🔔 5.1 Smart Alerts (Telegram)
AI สามารถเฝ้าตลาดให้คุณได้ตลอด 24 ชม. ผ่านระบบ Background Poller:
- **คำสั่ง:** "เฝ้าทองให้หน่อย ถ้าต่ำกว่า 2280 แจ้งเตือนใน Telegram"
- **การทำงาน:** ระบบจะไปบันทึกใน Alert Engine และยิงเข้า Telegram เมื่อเงื่อนไขเป็นจริง

### 🐋 5.2 Onchain & Options Flow
ดึงข้อมูล "Big Money" ของจริง:
- **Onchain flow:** ดึง Real-time Volume และ Market Cap ผ่าน CoinGecko API
- **Options Flow:** วิเคราะห์ Put/Call Ratio และ GEX (Gamma Exposure) ผ่าน Unusual Whales API (ต้องการ API Key ใน `.env`)

### 📰 5.3 Social Sentiment Scanner
วิเคราะห์ "ความโลภและความกลัว" จากข่าวจริง:
- **Data Source:** CryptoPanic (API / RSS)
- **AI Logic:** วิเคราะห์ Headline ข่าวเพื่อคำนวณ Hype Score (0-100)

### 📊 5.4 AI Trade Journal & Dashboard
วิเคราะห์การเทรดของคุณแบบมืออาชีพ:
- **Review:** สั่ง AI "รีวิวการเทรดของฉันหน่อย" เพื่อดู Critique และ Win-Rate ย้อนหลัง
- **Dashboard:** เข้าหน้าจอ **"Alerts & Reviews"** ทางด้านซ้าย เพื่อดูสถานะการแจ้งเตือนและประวัติการวิจารณ์ของ AI ทั้งหมด

### 🎯 5.5 Neural V8 Sniper Mode (Active)
ระบบการสแกนความแม่นยำสูง (Threshold 80%+) ที่ใช้ Hybrid Neural Network:
- **Consensus Engine:** ผสมผสานระหว่าง Ensemble Model (Fractal Analysis) และ Deep Learning (Attention-GRU)
- **Institutional Guards:** ตรวจสอบ Spread, Exposure และ Market Session (Forex/Stocks) อัตโนมัติก่อนส่งสัญญาณ
- **Dynamic Alerts:** แจ้งเตือนสถานะตลาด (Open/Closed) และสัญญาณ Sniper ผ่าน Telegram พร้อมประโยคที่หลากหลายสไตล์สถาบัน

### 🌓 5.6 Personalized UI Experience
- **Theme Toggle:** สามารถสลับโหมด **Light/Dark** ได้ที่มุมขวาบนของ Dashboard โดยระบบจะจดจำการตั้งค่าของคุณไว้ใน `localStorage` อัตโนมัติ
- **Auth Integration:** ข้อมูลผู้ใช้ทุกคนจะถูกบันทึกลงใน PostgreSQL โดยอัตโนมัติเมื่อมีการ Login เพื่อการวิเคราะห์พฤติกรรมและความแม่นยำในระยะยาว

---

---

> [!TIP]
> **Pro Tip:** หาก Chat Server รันไม่ได้ หรือ AI ค้าง ให้ลองใช้ไฟล์ `debug.bat` หรือ `run_ui.bat` ในหน้าแรกเพื่อ Reset ระบบโดยรวมอัตโนมัติครับ
