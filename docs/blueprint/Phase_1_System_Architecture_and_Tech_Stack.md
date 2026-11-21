# المرحلة 1: المعمارية الشاملة واختيار التقنيات (System Architecture & Tech Stack)

## 1. المخطط المعماري الشامل (End-to-End Architecture)

```text
+---------------------------------------------------------------------------------------------------+
|                             الجهاز الميداني (Mobile / Smart Glasses - Edge)                        |
|  [كاميرا RGB + LiDAR/Depth] ----> [SLAM & 6DoF Tracker (ARKit/ARCore)] ----> [طبقة العرض AR HUD]  |
|  [ميكروفون مزدوج] --------> [عزل الضجيج المحلي (RNNoise / WebRTC VAD)]                              |
+------------------------------------+---------------------------------------+----------------------+
                                     | WebRTC / Secure WebSocket (Binary)    ^ JSON + Audio Stream
                                     v                                       |
+---------------------------------------------------------------------------------------------------+
|                                بوابة البث اللحظي (Real-Time Media Gateway)                        |
|                      LiveKit / FastAPI WebSocket Server + Frame Keyframe Sampler                  |
+-----------------+----------------------------------+----------------------------------------------+
                  | الصوت المنقى (16kHz PCM)         | إطارات الفيديو + إحداثيات الكاميرا (Pose)
                  v                                  v
+-----------------------------------+  +------------------------------------------------------------+
| مسار الصوت واللهجات العربية       |  | مسار الرؤية الحاسوبية والاسترجاع الهندسي (Multimodal Core) |
| 1. Whisper-v3 Fine-tuned (Arabic) |  | 1. VLM Grounding (Qwen2.5-VL-72B / Florence-2)             |
| 2. تطبيع المصطلحات التقنية         |  | 2. قناع التحديد الدقيق (SAM-2 Segmentation)                |
|    (Code-Switching Normalizer)    |  | 3. محرك الاسترجاع الهجين (Hybrid RAG):                   |
| 3. إدارة حالة الحوار (FSM)        |  |    - Qdrant (Dense + ColPali Visual Embeddings)            |
+-----------------+-----------------+  |    - Neo4j (Component -> PartNo -> Torque -> LOTO Graph)   |
                  |                    +-----------------------------+------------------------------+
                  | النص والمقصد (Intent)                            | البيانات الهندسية الخام
                  +------------------------+-------------------------+
                                           v
+---------------------------------------------------------------------------------------------------+
|                     طبقة التحقق الصارمة ومنع الهلوسة (Zero-Hallucination Safety Guard)             |
|  - مطابقة رقم القطعة (Part Number Checksum)  |  - التحقق من حدود عزم الشد (Torque Range Guard)    |
|  - حقن تحذيرات العزل (Mandatory LOTO Injection) |  - توليد الرد العربي الموطن + إحداثيات الأسهم 3D  |
+------------------------------------+--------------------------------------------------------------+
                                     |
                                     v
                    [توليد الصوت العربي منخفض التأخير (Arabic Neural TTS)]
```

---

## 2. حزمة التقنيات المعتمدة (Recommended Tech Stack)

| الطبقة (Layer) | التقنية المختارة | مبرر الاختيار الهندسي |
| :--- | :--- | :--- |
| **تطبيق الموبايل والواقع المعزز** | React Native + TypeScript + `react-native-vision-camera` + ViroReact / Native ARKit & ARCore Bridge | أداء قريب من Native مع دعم كامل للواجهات العربية RTL وسهولة الصيانة. |
| **البث اللحظي (Streaming)** | LiveKit (WebRTC) أو FastAPI WebSockets | نقل الصوت والإطارات بزمن تأخير أقل من 80ms مع التكيف مع ضعف الشبكة. |
| **عزل الضوضاء والتعرف الصوتي** | DeepFilterNet3 + Whisper-large-v3 (مُحسّن للهجات العربية والمصطلحات الميكانيكية) | يتفوق في البيئات الصناعية (> 85 dB) ويفهم التبديل اللغوي (مثل: "فك الـ Solenoid Valve"). |
| **الرؤية المكانية والتحديد** | Qwen2.5-VL + SAM-2 + OpenCV PnP / ARCore Anchors | يربط الوصف اللغوي ("هذا الصمام") بالقناع البصري ثنائي الأبعاد ثم يحوله لمرساة ثلاثية الأبعاد. |
| **قواعد البيانات والاسترجاع** | Qdrant (Vector DB) + Neo4j (Knowledge Graph) + ColPali | ColPali يفهرس صفحات الكتيبات والمخططات كصور عالية الدقة دون فقدان الجداول. |
| **طبقة التحقق والسلامة** | Pydantic v2 + قواعد حتمية (Deterministic Rule Engine) | يمنع النموذج اللغوي من تخمين أي رقم قطعة أو قيمة عزم شد غير موجودة في المصدر. |
| **توليد الصوت العربي (TTS)** | XTTS-v2 / ElevenLabs Flash / Fish-Speech (Arabic Fine-tuned) | زمن توليد أول مقطع صوتي (TTFA) أقل من 250ms بنبرة عربية واضحة. |

---

## 3. ميزانية زمن الاستجابة المستهدفة (Latency Budget)

لضمان تجربة طبيعية للفني في الميدان دون ملل أو ارتباك:
- **التقاط الصوت وعزل الضجيج + ASR:** `180 ms - 250 ms`
- **تحليل الإطار البصري (VLM Grounding + SAM-2):** `220 ms - 300 ms` (يعمل بالتوازي مع ASR)
- **البحث في RAG الهجين والتحقق من السلامة:** `80 ms - 120 ms`
- **توليد الرد العربي وبدء البث الصوتي (TTFA):** `200 ms - 250 ms`
- **إجمالي زمن الاستجابة الكلي (End-to-End):** **`~650 ms - 850 ms`** (أقل من ثانية واحدة).

---

## 4. هيكل البيانات الموحد للاستجابة (Unified AR Response JSON Schema)

```json
{
  "session_id": "maint-2026-9841",
  "equipment_model": "Caterpillar C15 ACERT",
  "identified_component": {
    "part_number": "312-5620",
    "english_name": "Fuel Injection Actuator Control Valve",
    "arabic_name": "صمام التحكم في مشغل حقن الوقود",
    "confidence_score": 0.96,
    "bounding_box_2d": [0.42, 0.35, 0.58, 0.51],
    "anchor_3d_offset": {"x": 0.02, "y": -0.05, "z": 0.0}
  },
  "safety_lockout": {
    "severity": "CRITICAL",
    "loto_required": true,
    "warnings_ar": [
      "تحذير حرج: افصل مفتاح البطاريات الرئيسي وانتظر 10 دقائق لتفريغ ضغط الوقود العالي قبل الفك."
    ]
  },
  "current_step": {
    "step_number": 1,
    "total_steps": 4,
    "instruction_ar": "افصل الفيش الكهربائي الرباعي من أعلى الصمام بالضغط على لسان التثبيت المعدني.",
    "tool_required_ar": "مفك عادي صغير أو باليد",
    "torque_spec": null,
    "ar_visual_cue": {
      "type": "PULL_ARROW",
      "direction": "UP",
      "color": "#F59E0B"
    }
  },
  "manual_reference": {
    "document_id": "SENR9834-08",
    "page": 142
  }
}
```
