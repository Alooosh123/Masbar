# نظام المساعد الصناعي الذكي للحوسبة المكانية والواقع المعزز (Industrial Spatial AI Assistant)

حزمة هندسية وبرمجية متكاملة (Architecture + 6-Phase Engineering Blueprint + Backend AI Pipeline + Mobile RTL AR Starter + Safety Guardrails) جاهزة للاستيراد مباشرة في بيئات التطوير الذكية (**Cursor** / **Google Antigravity** / **VS Code**) أو البدء في بناء النموذج الأولي (MVP).

---

## هيكلية الحزمة (Repository Structure)

```text
Industrial_Spatial_AI_Assistant/
├── README.md                                              # الدليل الشامل للمشروع وكيفية التشغيل
├── 00_Master_Prompt/
│   └── INDUSTRIAL_SPATIAL_AI_PROMPT.md                    # البرومت الهندسي الرئيسي لفريق العمل متعدد التخصصات
├── 01_Architecture_and_Specs/                             # المخرجات الهندسية الكاملة للمراحل الست (Phases 1-6)
│   ├── Phase_1_System_Architecture_and_Tech_Stack.md      # المعمارية الشاملة، حزمة التقنيات، وميزانية زمن الاستجابة
│   ├── Phase_2_Multimodal_RAG_and_Schematics_Pipeline.md  # خط معالجة كتيبات الصيانة والمخططات الهندسية والجداول
│   ├── Phase_3_Spatial_Vision_and_3D_AR_Engine.md         # محرك الرؤية المكانية 6DoF والواقع المعزز التفاعلي
│   ├── Phase_4_Arabic_Dialect_Voice_and_Noise_Robustness.md # عزل الضوضاء الصناعية وفهم اللهجات العربية (ASR/TTS)
│   ├── Phase_5_Industrial_RTL_UI_UX_and_Mobile_App.md     # تصميم الواجهة العربية الصناعية وتجربة الاستخدام الميدانية
│   └── Phase_6_Safety_Guardrails_Testing_and_Deployment.md # بروتوكولات منع الهلوسة والسلامة المهنية LOTO والنشر
├── 02_Backend_AI_Pipeline/                                # الكود المصدري الأساسي لخدمات الذكاء الاصطناعي (Python / FastAPI)
│   ├── requirements.txt
│   ├── schemas/maintenance_schemas.py                     # نماذج البيانات الصارمة (Pydantic Schemas)
│   ├── rag/schematics_ingestion.py                        # خط استخراج وفهرسة الكتيبات والمخططات الهندسية
│   ├── voice/arabic_industrial_asr.py                     # معالجة الصوت الصناعي واللهجات العربية وإدارة الحوار
│   ├── safety/zero_hallucination_guard.py                 # محرك التحقق من السلامة وقيم عزم الشد (Zero-Hallucination)
│   └── api/main.py                                        # خادم FastAPI + WebSocket للتفاعل اللحظي
├── 03_Mobile_AR_Client/                                   # الهيكل البرمجي لتطبيق الجوال والواقع المعزز (React Native / TS)
│   ├── package.json
│   └── src/
│       ├── theme/industrialTheme.ts                       # نظام الألوان عالي التباين والخطوط العربية RTL
│       ├── types/spatial.ts                               # واجهات TypeScript المتطابقة مع الخادم
│       ├── components/SafetyLockoutBanner.tsx             # مكون تحذيرات السلامة الإلزامية (LOTO)
│       └── screens/LiveMaintenanceARScreen.tsx            # شاشة الواقع المعزز الميدانية التفاعلية
└── 04_Sample_Data_and_Prompts/                          # برومتات الوكلاء التخصصيين وقاعدة بيانات تجريبية
    ├── system_prompts/
    │   ├── spatial_vision_agent.txt
    │   ├── arabic_dialect_interpreter.txt
    │   └── safety_auditor_agent.txt
    └── sample_kb/
        └── caterpillar_c15_valve_manual_sample.json       # عينة بيانات صيانة حقيقية للاختبار الفوري
```

---

## البدء السريع (Quick Start)

### 1. تشغيل الخادم الخلفي (Backend AI Pipeline)
```bash
cd 02_Backend_AI_Pipeline
python -m venv venv
source venv/bin/activate  # أو venv\Scripts\activate على ويندوز
pip install -r requirements.txt
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. استيراد المشروع في Cursor أو Google Antigravity
افتح المجلد الرئيسي `Industrial_Spatial_AI_Assistant` داخل بيئة التطوير، واستخدم ملفات `01_Architecture_and_Specs/` كسياق مرجعي (`@docs`) لتوجيه وكلاء البرمجة لتوسيع الوحدات البرمجية في `02_Backend_AI_Pipeline` و `03_Mobile_AR_Client`.
