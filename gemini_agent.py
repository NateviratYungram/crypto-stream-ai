import os
import sys
import json
import requests
from google import genai
from dotenv import load_dotenv

# โหลด Environment Variables จากไฟล์ .env อัตโนมัติ
load_dotenv()

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ
# ==========================================
# ดึง API Key จาก Environment (ต้อง set ก่อนรัน)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MCP_API_KEY = os.environ.get("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")
MCP_URL = "http://localhost:8000"

# เช็คว่ามี Gemini API Key หรือยัง
if not GEMINI_API_KEY:
    print("❌ ไม่พบ GEMINI_API_KEY!")
    print("กรุณาสร้างไฟล์ .env ก่อนรัน (ดูตัวอย่างที่ .env.example)")
    sys.exit(1)

# เริ่มต้นการทำงานของ Gemini ด้วย SDK แบบใหม่
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = 'gemini-2.5-flash'

# ==========================================
# 2. ฟังก์ชันคุยกับ MCP Server
# ==========================================
def get_schema():
    """ถาม MCP ว่าตอนนี้มีตารางและคอลัมน์อะไรให้ AI ใช้ได้บ้าง"""
    headers = {"X-API-Key": MCP_API_KEY}
    try:
        response = requests.get(f"{MCP_URL}/api/v1/schemas", headers=headers)
        if response.status_code != 200:
            print(f"❌ ดึง Schema ไม่ได้ (ลืมเปิด MCP Server หรือเปล่า?): {response.text}")
            return None
        return response.json()
    except Exception as e:
        print(f"❌ เชื่อมต่อ MCP Server ไม่ได้: {e}")
        return None

def execute_sql(sql: str):
    """ส่งคำสั่ง SQL ที่ AI คิดได้ ไปรันที่ MCP Server"""
    headers = {"X-API-Key": MCP_API_KEY, "Content-Type": "application/json"}
    payload = {"sql": sql, "max_rows": 100} # จำกัดให้ดึงข้อมูลได้สูงสุด 100 แถวเพื่อความปลอดภัย
    response = requests.post(f"{MCP_URL}/api/v1/query", headers=headers, json=payload)
    if response.status_code != 200:
       return {"error": response.text}
    return response.json()

# ==========================================
# 3. ห้องแชทอัจฉริยะ (Main Chat)
# ==========================================
def chat():
    print("="*60)
    print("📊 CryptoStream AI — Institutional Trading Intelligence")
    print("   Senior Quant Strategist | Powered by Gemini + MCP")
    print("   ระบุตลาด/สัญลักษณ์ที่ต้องการวิเคราะห์ หรือพิมพ์ 'exit' เพื่อออก")
    print("="*60)
    
    # AI ต้องรู้ก่อนว่าระบบคุณมีคอลัมน์อะไรบ้าง (Context Injection)
    schema = get_schema()
    if not schema:
        return
        
    schema_str = json.dumps(schema, indent=2)

    while True:
        try:
            user_input = input("\n👤 คำถามของคุณ: ")
            if user_input.lower() in ['exit', 'quit']:
                break
            if not user_input.strip():
                continue
                
            print("⏳ [AI กำลังวิเคราะห์และแปลภาษาไทยเป็น SQL...]")
            
            # Step 1: Intent Detection & Text-to-SQL
            # เราจะให้ AI แยกแยะก่อนว่าเป็นคำถามเกี่ยวกับอะไร เพื่อเลือกโครงสร้างการสรุปที่เหมาะสม
            sql_prompt = f"""
You are the advanced reasoning core of CryptoStream AI.
Your personality is a dual-mode intelligence:
1. [Primary] Senior Institutional Quant Strategist (Elite, Precise, Data-Driven)
2. [Secondary] System Architect & Partner (Transparent, Helpful, Tech-Savvy)

Database Schema:
{schema_str}

User Question: {user_input}

TASK:
Identify the intent and generate the necessary data query if needed. 
Return ONLY a JSON object with this structure:
{{
  "intent": "MARKET" | "SYSTEM" | "GENERAL",
  "explanation": "Brief internal reason for this classification",
  "query": "PostgreSQL query or null",
  "persona_lean": "QUANT" | "ARCHITECT" | "PARTNER"
}}

CLASSIFICATION RULES:
- MARKET: Any question requiring price action, trends, whale moves, support/resistance, or data from the schema.
- SYSTEM: Questions about YOURSELF, your model (Gemini 2.5 Flash), technical architecture, MCP, Postgres, or how the app works. You are allowed to be transparent here!
- GENERAL: Greetings, casual chat, or non-technical/non-market questions.

SQL RULES:
- If intent is MARKET, produce valid PostgreSQL using available schema.
- Symbol format: append 'USDT' to crypto tickers (BTC -> BTCUSDT).
- If intent is SYSTEM/GENERAL, query remains null.

Return ONLY the raw JSON.
"""
            
            intent_response = client.models.generate_content(
                model=MODEL_ID,
                contents=sql_prompt,
                config={'response_mime_type': 'application/json'}
            )
            
            intent_data = json.loads(intent_response.text)
            intent = intent_data.get("intent", "GENERAL")
            sql_query = intent_data.get("query")
            persona_lean = intent_data.get("persona_lean", "PARTNER")
            
            print(f"🧠 [Intent Detected]: {intent} ({persona_lean})")

            if intent == "MARKET" and sql_query:
                print(f"🔍 [SQL ที่สร้างได้]: {sql_query}")
                
                # Step 2: ให้ระบบ MCP รัน SQL แทน AI (เพื่อความปลอดภัย ไม่ยอมให้ AI ใช้ DB ตรงๆ)
                print("⏳ [ดึงข้อมูลจาก Postgres ด้วยความปลอดภัยระดับองค์กร...]")
                result = execute_sql(sql_query)
                
                if "error" in result:
                    print(f"❌ ฐานข้อมูลปฏิเสธคำสั่ง: {result['error']}")
                    continue
            else:
                result = {"data": "No database query executed for this intent."}
                
            # Step 3: Adaptive Summary (Tailored to Persona)
            print("⏳ [AI กำลังเรียบเรียงคำตอบที่เหมาะสมกับบริบท...]")
            summary_prompt = f"""
You are CryptoStream AI. Respond to the User based on the detected intent and persona lean.

CONTEXT:
- User Question: {user_input}
- Detected Intent: {intent}
- Recommended Persona: {persona_lean}
- Background Data (if any): {json.dumps(result)}

STRICT FORMATTING PROTOCOL:
To maintain institutional readability, follow this layout exactly:

[MARKET INTENT LAYOUT]
---
🧭 **ภาพรวมตลาด (MARKET OVERVIEW)**
- <Summary of trend in 2-3 brief sentences>
- <Key dynamic or volatility context>

---
⚡ **การวิเคราะห์เชิงปริมาณ (QUANT INSIGHTS)**
- Use `monospace` for all prices: `{symbol}` at `{price}`.
- Highlight whale activity with `monospace` values.
- Keep paragraphs punchy (max 2-3 lines).

---
🎯 **แผนกลยุทธ์ (STRATEGY MAP)**
| Action | Zone / Level | Note |
| :--- | :--- | :--- |
| **ENTRY** | `price_range` | <condition> |
| **STOP LOSS** | `price` | <invalidation> |
| **TAKE PROFIT** | `target_p1` / `target_p2` | <objective> |

> [!TIP]
> **Executive Summary**: <One-line punchy takeaway>

---
🛡️ **การบริหารความเสี่ยง (RISK PROTOCOL)**
- <Specific warning about data quality or market conditions>
- "นี่เป็นการวิเคราะห์เชิงข้อมูล ไม่ใช่คำแนะนำการลงทุน ควรบริหารความเสี่ยงทุกครั้ง"

[SYSTEM INTENT LAYOUT]
🤖 **สถานะข้อมูลและระบบ (SYSTEM ARCHITECTURE)**
---
- **Identity**: Gemini 2.5 Flash Autonomous Node
- **Core Stack**: FastAPI + Model Context Protocol (MCP) Bridge
- **Persistence**: High-Frequency PostgreSQL Cluster
- **Streams**: Real-time Kafka / Flink Pipeline
---
<Detailed technical explanation in professional Thai>

[GENERAL INTENT LAYOUT]
🤝 **CryptoStream Partner Response**
---
<Natural, intelligent, and warm conversation in Thai>
---

Final output must be professional, impressively formatted, and visually distinct. Use double line breaks between sections.
"""
            
            summary_response = client.models.generate_content(
                model=MODEL_ID,
                contents=summary_prompt,
            )
            print(f"\n📊 CryptoStream AI Analysis:\n{summary_response.text}\n")
            print("-" * 60)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️ เกิดข้อผิดพลาดของระบบ: {e}")

if __name__ == "__main__":
    chat()
