# تشغيل مِسبار كنموذج سحابي أولي على Railway

## ما الذي ستنشره؟

هذا المستودع يحتوي خدمتين منفصلتين:

1. **Backend**: FastAPI على Dockerfile الموجود في جذر المستودع.
2. **Frontend**: React/Vite + Nginx في مجلد `web/`.

الواجهة ترسل طلبات `/api/*` و`/health` و`/ws/*` إلى Backend عبر Nginx، لذلك لا يحتاج المتصفح إلى الاتصال بمنفذ Backend منفصل ولا يحتاج كشف Backend على الإنترنت.

> **تحذير استخدام:** هذه نسخة عرض أولية. قطع المعرفة التسع في قاعدة البيانات موسومة `sample`، فلا تستخدم أي عزم أو خطوة صيانة لاتخاذ قرار صناعي حقيقي. يبقى بحث الكتيبات معطلاً، والمحادثة الذكية الخارجية معطلة افتراضياً في إعداد العرض أدناه.

## قبل النشر

- حساب Railway متصل بحساب GitHub.
- صلاحية الوصول إلى مستودع `Alooosh123/Masbar`.
- إنشاء مشروع واحد في Railway وبيئة واحدة تحتوي الخدمتين.
- لا ترفع مفاتيح API إلى GitHub؛ أضفها فقط في Variables على المنصة عند الحاجة.

## 1. إنشاء Backend

في Railway:

1. أنشئ خدمة جديدة من GitHub Repo وحدد `Alooosh123/Masbar` والفرع `main`.
2. اجعل Root Directory هو جذر المستودع.
3. اضبط Dockerfile Path على `/Dockerfile`.
4. اضبط متغيرات الخدمة التالية:

| المتغير | القيمة الأولية |
|---|---|
| `ENVIRONMENT` | `production` |
| `PORT` | `8000` |
| `CORS_ORIGINS` | عنوان الواجهة بعد إنشائه، مثل `https://<frontend-domain>` |
| `VISION_PROVIDER` | `mock` |
| `CHAT_PROVIDER` | `off` |
| `DEMO_MODE` | `true` |
| `MANUAL_SEARCH_ENABLED` | `false` |
| `SESSION_DB_PATH` | `/app/data/sessions/sessions.sqlite3` |

5. اجعل Healthcheck Path هو `/health`.
6. اترك Backend على الشبكة الخاصة للمشروع؛ لا تنشئ له نطاقاً عاماً في النموذج الأولي.

**ملاحظة التخزين:** Dockerfile يحفظ قاعدة SQLite محلياً. من دون Volume دائم، قد تفقد الجلسات عند إعادة النشر أو استبدال الحاوية. أضف Volume إلى المسار `/app/data/sessions` بعد التحقق من صلاحيات الكتابة للـUID 10001 على المنصة؛ لا تغيّر الحاوية إلى root فقط لتجاوز مشكلة الصلاحيات دون مراجعة أمنية. للنسخة الإنتاجية، الأفضل نقل الجلسات إلى قاعدة بيانات مشتركة مدارة.

## 2. إنشاء Frontend

1. أضف خدمة GitHub Repo جديدة من المستودع نفسه وعلى الفرع `main`.
2. اجعل Root Directory هو `/web`.
3. Dockerfile Path هو `/web/Dockerfile` إذا كان الحقل يطلب المسار من جذر المستودع، أو `Dockerfile` إذا كان نسبياً إلى Root Directory.
4. أضف المتغير التالي:

```env
BACKEND_UPSTREAM=http://<backend-private-domain>:8000
```

استخدم نطاق Backend الخاص داخل Railway، بالشكل `<service-name>.railway.internal`. لا تستخدم النطاق العام للـBackend في هذا المتغير.

5. لا تضبط `VITE_API_URL`؛ الواجهة الإنتاجية تستخدم نطاقها الحالي وترسل الطلبات إلى Nginx، وهو يمررها داخلياً إلى Backend.
6. أنشئ Public Domain لخدمة Frontend، ثم ضع هذا النطاق في `CORS_ORIGINS` بخدمة Backend.

## 3. فحص النشر

تحقق من التالي بعد اكتمال الخدمتين:

- فتح نطاق Frontend يعرض صفحة مِسبار.
- `https://<frontend-domain>/health` يعرض `status=online`.
- `https://<frontend-domain>/api/v1/equipment` يعيد قائمة المعدات.
- ابدأ جلسة عرض لمعدة موجودة، مثل `Caterpillar C15 ACERT`.
- تأكد أن البيانات تظهر على أنها `sample` ولا تعرض قيمة عزم على أنها معتمدة.

## 4. ماذا لا نفعّل في العرض؟

- لا تفعّل `MANUAL_SEARCH_ENABLED=true` على خدمة عامة.
- لا تحوّل قيم قاعدة المعرفة التجريبية إلى `verified` لمجرد إكمال الواجهة.
- لا تضف بيانات اعتماد/كلمات مرور أو مفاتيح إلى ملفات Git.
- لا توصل صور معدات العملاء إلى مزود ذكاء اصطناعي قبل مراجعة سياسة الخصوصية والموافقة.
- لا تستخدم العرض لتوجيه أعمال الفك أو التشغيل أو العزم في معدات حقيقية.

## 5. قيود Railway التي يجب معرفتها

- كل خدمة نشر مستقلة؛ لا تُشغّل Railway ملف Compose مباشرة. أنشئ Backend وFrontend كخدمتين من المستودع نفسه.
- استخدم Private Networking للمرور بين الواجهة والخادم.
- خدمات Railway لا تحصل بالضرورة على نطاق عام تلقائياً؛ أنشئ نطاقاً لخدمة Frontend بعد النشر.
- إعداد Config-as-Code القديم `railway.toml/json` أصبح قديماً للخدمات الجديدة؛ استخدم إعدادات الخدمة من لوحة Railway أو البنية التحتية المعتمدة لديها.

روابط مرجعية:
- https://docs.railway.com/deployments/monorepo
- https://docs.railway.com/networking/domains/working-with-domains
- https://docs.railway.com/networking/private-networking
- https://docs.railway.com/volumes
