# ربط بيانات المعدات الثقيلة بمصادر OEM الرسمية

**آخر تحديث:** 20 نوفمبر 2026

---

## 1. ما تم ربطه فعليًا

أُضيف سجل مصادر OEM في:

```text
data/catalog/oem_registry.json
```

ويحتوي حاليًا على **31 شركة** من كبرى شركات المعدات الثقيلة، و**126 عائلة موديلات**، مع:

- الاسم العربي والإنجليزي.
- بلد المنشأ.
- الموقع الرسمي.
- بوابة الخدمة/القطع إن كانت معلنة.
- طريقة الوصول إلى بيانات الصيانة: `public_catalog` أو `dealer_portal` أو `subscription` أو `manual_required`.
- ملاحظة عربية عن طريقة الوصول.
- تاريخ تجميع السجل.

الشركات المشمولة:

| # | الشركة | # | الشركة | # | الشركة |
| --- | --- | --- | --- | --- | --- |
| 1 | Caterpillar | 12 | JCB | 23 | Ammann |
| 2 | Komatsu | 13 | SANY | 24 | Kubota |
| 3 | Volvo CE | 14 | XCMG | 25 | Yanmar |
| 4 | Hitachi | 15 | Zoomlion | 26 | Takeuchi |
| 5 | Liebherr | 16 | LiuGong | 27 | Bobcat |
| 6 | John Deere | 17 | Shantui | 28 | Mecalac |
| 7 | Case CE | 18 | Tadano | 29 | Hidromek |
| 8 | New Holland | 19 | Manitowoc | 30 | Dressta |
| 9 | Develon | 20 | Terex | 31 | Bell Equipment |
| 10 | Hyundai CE | 21 | BOMAG | | |
| 11 | Kobelco | 22 | Wirtgen | | |

يُعرض السجل من الـ API:

```text
GET /api/v1/manufacturers
GET /api/v1/manufacturers/{id}
GET /api/v1/manufacturers?q=PC200
```

ومن المحادثة:

```text
ما الشركات المتاحة؟
هل البيانات حقيقية؟
```

---

## 2. حدود مهمة يجب فهمها

وجود الشركة والرابط والموديل في السجل **لا يعني** أن التطبيق يملك كتيب الصيانة الخاص بها.

قيم العزم، وخطوات الفك والتركيب، وبنود LOTO، وأرقام القطع الداخلية هي **بيانات مملوكة للمصنّع**، وغالبًا تكون خلف:

- اشتراك خدمة مثل Cat SIS أو Volvo Impact أو Komatsu Service Information.
- بوابة وكيل معتمد.
- كتيب PDF مرخّص لا يُسمح بإعادة توزيعه.

لذلك:

- قاعدة الصيانة الحالية في `data/kb/` ما زالت **تجريبية** (`data_status: sample`).
- لا يخترع المساعد أي عزم أو خطوة أو بند عزل.
- أي سؤال عن عزم أو فك أو LOTO لم يُستورد بعد يُرفض بأمان.
- سجل OEM الحقيقي هو **دليل مصادر**، وليس بديلًا عن الكتيب.

---

## 3. استيراد بيانات حقيقية من كتيب OEM

### 3.1 الصيغة المطلوبة

أنشئ ملف JSON مثل:

```json
{
  "equipment_family": "Caterpillar 320",
  "manufacturer": "Caterpillar",
  "source_document_id": "SENR0000-00",
  "source_page": 142,
  "verified_from_manual": true,
  "verified_by": "اسم المهندس المسؤول",
  "verified_at": "2026-11-20",
  "components": [
    {
      "part_number": "000-0000",
      "english_name": "Example Component",
      "arabic_name": "اسم القطعة بالعربية",
      "equipment_models": ["Caterpillar 320"],
      "manual_doc_id": "SENR0000-00",
      "manual_page": 142,
      "section_title": "Disassembly and Assembly",
      "torque_nm": 45.0,
      "tightening_sequence": "الخطوة 1: 20 نيوتن·م، الخطوة 2: 45 نيوتن·م.",
      "symptoms": ["leak"],
      "symptoms_ar": ["تسريب"],
      "safety": {
        "loto_required": true,
        "severity": "CRITICAL",
        "warnings_ar": ["تحذير من الكتيب الرسمي."],
        "checklist": [
          {"id": "battery_disconnected", "label_ar": "فصلت مفتاح البطارية"}
        ]
      },
      "steps": [
        {
          "step_number": 1,
          "instruction_ar": "نص الخطوة من الكتيب.",
          "tool_required_ar": "الأداة المطلوبة.",
          "requires_torque": false,
          "cue": {"cue_type": "HIGHLIGHT_MESH", "color_hex": "#F59E0B"}
        }
      ],
      "verification_status": "verified"
    }
  ]
}
```

### 3.2 التحقق ثم الكتابة

```powershell
# تحقق فقط (dry run)
.\.venv\Scripts\python.exe scripts\import_oem_data.py --input .\oem_exports\cat_320.json

# كتابة الملف بعد نجاح التحقق
.\.venv\Scripts\python.exe scripts\import_oem_data.py --input .\oem_exports\cat_320.json --apply

# تحديد مسار الهدف
.\.venv\Scripts\python.exe scripts\import_oem_data.py --input .\oem_exports\cat_320.json --output data\kb\cat_320_verified.json --apply
```

ثم أعد تشغيل الخادم. سيُظهر `/health` عدد القطع والمعدات المحدّث.

### 3.3 قواعد يرفضها المستورد

- `verified_from_manual` غير موجود أو ليس `true`.
- `source_document_id` فارغ.
- `source_page` أقل من 1.
- `components` فارغة.
- قطعة تحمل مستندًا مختلفًا عن المستند المصرح به.
- خطوة تطلب عزمًا دون قيمة عزم موثقة.
- أي ملف لا يطابق مخطط `EquipmentFile` (تسلسل الخطوات، بنود LOTO، إلخ).

---

## 4. كيف تحصل على البيانات الرسمية؟

1. **اشتراك OEM:** Cat SIS 2.0، Volvo Impact، Komatsu Service Information، John Deere Service ADVISOR، وغيرها.
2. **وكيل معتمد:** يزوّدك بالإجراءات وأرقام القطع وقيم العزم لوحداتك.
3. **كتيب مالك/خدمة مرخّص:** استخدمه للاستيراد الداخلي فقط وفق ترخيصه.
4. **بيانات أسطولك:** إذا كانت لديك سجلات صيانة داخلية موثقة، يمكن اعتمادها كمصدر داخلي بدل OEM.

---

## 5. ما لم يتم فعله بعد

- لم تُستورد أي كتيبات OEM فعلية، لأن ذلك يتطلب اشتراكًا أو ملفات مرخّصة منك.
- لم تُختبر قيم عزم حقيقية على معدات ميدانية.
- لم يُبنَ موصل تلقائي إلى Cat SIS أو Volvo Impact، لأنه يتطلب بيانات اعتماد وعقود وصول.
- إذا زوّدتني بملفات OEM مرخّصة أو حساب وصول رسمي، يمكن استكمال الاستيراد والتحقق قطعةً قطعة.

---

## 6. المراجع

- سجل المصادر: `data/catalog/oem_registry.json`
- مستورد البيانات: `scripts/import_oem_data.py`
- مخطط قاعدة المعرفة: `backend/app/domain/kb.py`
- التقرير: `docs/TEST_RESULTS.md`
