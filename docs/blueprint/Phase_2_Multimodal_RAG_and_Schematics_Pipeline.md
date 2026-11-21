# المرحلة 2: هندسة بيانات الصيانة والمخططات (Multimodal RAG & Schematics Pipeline)

## 1. تحديات كتيبات الصيانة الصناعية
كتيبات الصيانة الهندسية (مثل Caterpillar SIS, Cummins QuickServe, Siemens Electrical Schematics) ليست نصوصاً عادية؛ بل تحتوي على:
1. **رسومات تفجيرية (Exploded Views)** تربط أرقاماً مرجعية صغيرة (Callout IDs مثل `14`, `22A`) بجداول أرقام القطع.
2. **جداول عزم الشد (Torque Specification Tables)** حيث يؤدي خلط صف واحد إلى كسر مسمار أو تسريب خطير.
3. **مخططات كهربائية وهيدروليكية (P&ID & Wiring Diagrams)** تمتد عبر عدة صفحات.

---

## 2. خط أنابيب الاستيعاب والفهرسة (Ingestion & Indexing Pipeline)

### الخطوة أ: التفكيك البصري والهيكلي (Layout & Table Parsing)
- تحويل كل صفحة PDF إلى صورة عالية الدقة (300 DPI) مع الاحتفاظ بطبقة النص المتجه إن وجدت.
- استخدام **Surya OCR / Docling** لاكتشاف مناطق الجداول والرسومات والعناوين.
- تمرير الصفحات عبر نموذج **ColPali (Vision-Language Retriever)** لتوليد تضمينات بصرية متعددة المتجهات (Multi-Vector Embeddings) تحافظ على التخطيط المكاني للصفحة كما هي.

### الخطوة ب: استخراج الجداول والرسوم البيانية المعرفية (Structured Extraction -> Neo4j)
- استخراج كل جدول عزم شد وتحويله إلى عقد (Nodes) وعلاقات في **Neo4j**:
  `(:Equipment)-[:HAS_SUBSYSTEM]->(:Subsystem)-[:CONTAINS_PART]->(:Part {part_number, name_en, name_ar})-[:HAS_TORQUE]->(:TorqueSpec {value_nm, value_lbft, sequence})`
- ربط كل خطوة صيانة بعقدة تحذير سلامة إلزامية:
  `(:MaintenanceProcedure)-[:REQUIRES_LOTO]->(:SafetyProtocol)`

### الخطوة ج: قاموس المرادفات الصناعية (Arabic-English Industrial Lexicon)
بناء طبقة ربط دلالي تربط المصطلحات العامية للفنيين العرب بالمصطلحات الهندسية الإنجليزية:
- `"بلف" / "صمام" / "سولونويد"` $ightarrow$ `Valve / Solenoid Valve`
- `"طرمبة" / "مضخة"` $ightarrow$ `Pump / Hydraulic Pump`
- `"حساس" / "سنسور"` $ightarrow$ `Sensor / Transducer`
- `"كتاوت" / "ريليه"` $ightarrow$ `Relay / Contactor`
- `"وجيه" / "كازكيت"` $ightarrow$ `Gasket / O-Ring / Seal`

---

## 3. استراتيجية الاسترجاع الهجين (Hybrid Retrieval Strategy)

عندما يسأل الفني: *"هذا الصمام يسرب زيت، ما رقمه وكيف أفكه؟"*:
1. **التعرف البصري أولاً:** يحدد نموذج الرؤية اسم المعدة والمنطقة الفرعية (مثلاً: `Fuel Filter Base / Actuator`).
2. **الاستعلام المتوازي:**
   - **بحث متجه في Qdrant:** استرجاع أعلى 5 صفحات مطابقة بصرياً ودلالياً (بما في ذلك الرسومات التفجيرية).
   - **استعلام Graph في Neo4j:** جلب رقم القطعة الدقيق، قطع الغيار الاستهلاكية المرتبطة (مثل `O-Ring` مانع التسرب لأن الشكوى هي "تسريب زيت")، وقيم عزم الشد.
3. **إعادة الترتيب (Reranking):** استخدام `BGE-Reranker-v2-m3` للتحقق من تطابق رقم الموديل والرقم التسلسلي للمعدة قبل تمرير السياق للمساعد.
