# تجربة استخراج بيانات الفواتير

وحدة استخراج محلية، آخر تحديث 14 سبتمبر 2026. ترتبط بالموقع `0.19.0` عن طريق عامل الخادم وطابور PostgreSQL. الوحدة نفسها لا تكتب في قاعدة البيانات؛ تعيد اقتراحات، والعامل يحفظها مستقلة عن الفاتورة حتى يراجعها المستخدم. [ربط الموقع وتشغيله](../../../02_Requirements/Use_Cases/INVOICE_EXTRACTION_AR.md)، [تحسين OCR](../../../06_Testing_Evaluation/Results/OCR_QUALITY_V2_RESULTS_AR.md) و[نتائج QR/XML](../../../06_Testing_Evaluation/Results/STRUCTURED_SOURCES_V1_RESULTS_AR.md).

## ما يعمل

- في `0.19.0`: قراءة المناطق من دقة الأصل، وتقسيم الجداول مع عناوينها، ومصنف اتجاه محلي وتسوية انحناء محدودة، وعرض أدلة التعارض. [السلوك الحالي وحدوده](../../../02_Requirements/Use_Cases/GUIDED_INVOICE_READING_AR.md). مهلة عامل الموقع أصبحت 420 ثانية وميزانية القارئ 380 ثانية؛ الحدود الزمنية الواردة أدناه تصف الإصدارات السابقة.

- فهم بصري محلي بـ`qwen3-vl:8b-instruct` عبر Ollama ضمن دالة القارئ نفسها. تربط كل إضافة بمقاطع النص، وتظهر التعارضات دون تعديل الفاتورة. [المواصفات والتشغيل والحدود](../../../02_Requirements/Use_Cases/LOCAL_INVOICE_UNDERSTANDING_AR.md).
- تصحيح منظور صور الكاميرا عند ظهور حدود ورقة موثوقة، مع إعادة الإحداثيات إلى الأصل، وقراءات بديلة لست قصاصات ضعيفة كحد أقصى. بقاء الصورة دون تصحيح عند الشك سلوك مقصود.

- قراءة PDF النصي مباشرة بـPyMuPDF، والتحول إلى PaddleOCR لكل صفحة ممسوحة أو ذات نص تالف أو تعذر استخراجه. يستمر PaddleOCR للصور. [تفاصيل الاختيار والنتائج](../../../02_Requirements/Use_Cases/HYBRID_TEXT_EXTRACTION_AR.md).
- قراءة ZATCA TLV من QR في الصور وصفحات PDF بواسطة OpenCV، للحقول 1–5، مع الاحتفاظ بموضع الرمز ودون عرض بيانات التوقيع والمفتاح في الحقول 6–9.
- قراءة UBL XML عند رفعه مباشرة أو إرفاقه داخل PDF بواسطة pypdf، واستخراج الرأس والإجماليات والبنود المتاحة. تمنع DTD والكيانات ويحد الحجم وعدد العناصر.
- نماذج PP-OCRv5 المحمولة للكشف والتعرف العربي والإنجليزي، تعمل على CPU، مع تحديد اللغة يدويًا.
- اقتراح المورد ورقم الفاتورة والتاريخ والعملة والمجموع والضريبة والإجمالي، واستخراج البنود من أعمدة معنونة.
- حفظ مصدر الاقتراح ونص الدليل ورقم الصفحة وموقعه ودرجة المحرك إن وجدت. درجة المحرك ليست احتمال صحة الحقل؛ كل النتائج تتطلب مراجعة بشرية.
- ترك الحقول الغائبة والتواريخ الملتبسة والقيم المتعارضة دون تخمين. لا تنفذ تعليمات مكتوبة في المستند ولا تعتمد أي فاتورة.
- تصحيح ميل بسيط بين 0.3 و7 درجات عند وجود خطوط طويلة متفقة، مع زيادة حد دقة كشف النص إلى 2200 بكسل. يعاد موقع الدليل إلى الصورة الأصلية؛ لا يتغير الملف.
- قراءة إنجليزية ثانية لقصاصة عنوان عربي فقد قيمة رقم الفاتورة أو التاريخ أو العملة. تبقى القراءتان في `recognition_reads`، ويظهر تحذير `SECOND_READING_*`؛ لا تستبدل قيمة موجودة بهذه الآلية.
- قبول فرق حرف واحد في عنوان عربي طويل مع تحذير `APPROXIMATE_LABEL_*` أو `APPROXIMATE_COLUMN_*`. القيم نفسها لا تصحح بهذه القاعدة. لا يتحول حقل نسبة مئوية إلى مبلغ خصم.

الحدود الحالية: حتى 3 صفحات PDF و20 مليون بكسل للصورة و2500 مقطع نصي و80 ألف حرف. XML حتى 2 MiB و20 ألف عنصر، وQR حتى 700 حرف Base64. عامل الموقع يفرض مهلة 180 ثانية لكل عملية؛ أوامر CLI التالية لا تضيف مهلة بمفردها. هذه ليست بيئة عزل إنتاجية. تصحيح الميل يتطلب خطوطًا طويلة؛ الصور المنظورية أو المقلوبة أو قليلة الدقة غير مضمونة. القراءة المختلطة محدودة بثلاثة حقول وبحد أقصى 20 قصاصة لكل صفحة؛ عتبة درجة المحرك 0.75 للقراءة الثانية ليست دقة معايرة. التواريخ غير ISO والجداول الممتدة دون عناوين أعمدة متكررة تحتاج تطويرًا. اختيار النص المباشر يفحص صلاحيته ومساحة الصور؛ هذا لا يثبت مطابقته للصورة الظاهرة. لا تتحقق الوحدة من توقيع ZATCA أو الشهادة أو التخليص، ولا تنفذ XSD/Schematron كاملًا.

## التشغيل من PowerShell

نفذت الأوامر الأساسية على Windows باستخدام Python 3.13، في بيئة مستقلة عن الخادم. الإعداد الأول يحمل المكتبات والنماذج؛ القراءة اللاحقة تستخدم النماذج المحلية. لم تختبر إعادة الإعداد على جهاز جديد بالكامل.

```powershell
Set-Location 'C:\path\to\Graduation-Project'
py -3.13 -m venv .local/ocr-venv
& .local/ocr-venv/Scripts/python.exe -m pip install -r 04_Source_Code/ai/document_intelligence/requirements.lock.txt
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/run_extraction.py --prepare-models
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/create_benchmark.py
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/evaluate_benchmark.py
```

على الجهاز الحالي اكتمل الإعداد؛ لا حاجة لإعادة تثبيت البيئة. مولد العينات يستخدم خط Arial المثبت في Windows؛ يمكن تمرير `--font` لمسار خط عربي آخر، لكن تغيير الخط يغير مجموعة القياس. ملفات PDF والصور مصطنعة وموسومة بوضوح وليست مطالبات مالية.

قراءة ملف واحد:

```powershell
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/run_extraction.py --input 05_Data/Sample_Invoices/Synthetic_OCR_v1/ar-01-scan.png --output 05_Data/Processed_Data/extraction-example.json --language ar
```

النتيجة JSON فيها `fields` و`items` و`warnings` و`tokens` و`text` و`page_routes` و`structured_sources`، وكل اقتراح يحتوي `value` و`source` و`evidence` و`recognition_reads` و`page` و`bbox` و`confidence` و`needs_review`. XML يعيد مسار الحقل مع `page` و`bbox` خاليين. إحداثيات الأدلة المرئية نسبية للصورة الأصلية بعد توجيه EXIF، بينما `layout_bbox` داخل المقاطع يخص الصورة المصححة ويستخدم لترتيب النص فقط. القراءة الثانية قد تجمع عنوانًا وقيمة من نموذجي اللغة داخل PaddleOCR؛ `recognition_reads` يحفظ النصين الفعليين. لا يُملأ نموذج الموقع من هذا الملف تلقائيًا.

اختبار ظروف صورة إضافية، من جذر المشروع:

```powershell
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/create_stress_benchmark.py
& .local/ocr-venv/Scripts/python.exe 04_Source_Code/ai/document_intelligence/evaluate_benchmark.py --manifest 05_Data/Sample_Invoices/Synthetic_OCR_stress_v2/manifest.json --output 06_Testing_Evaluation/Results/OCR_STRESS_V2.json
```

ينشئ أربع صور JPEG مشتقة من تنسيق مصطنع معروف: ميلان سالب 3.5 درجات أو تصغير إلى 45% وضغط JPEG. ليست فواتير مستقلة. مرّر اسم نتيجة جديدًا عبر `--output`؛ المقيم الافتراضي يكتب `OCR_BENCHMARK_V2.json`، ويحفظ المقاطع تحت `05_Data/Processed_Data/<اسم التقرير>` حتى لا يخلط الجولات. تقرير V1 محفوظ للمقارنة.

## التحقق والملفات

```powershell
Set-Location 'C:\path\to\Graduation-Project\04_Source_Code\ai\document_intelligence'
& ../../../.local/ocr-venv/Scripts/python.exe -m unittest discover -s tests -v
& ../../../.local/ocr-venv/Scripts/python.exe -m pip check
```

`requirements.lock.txt` يسجل النسخ المثبتة. `model_hashes.json` يسجل SHA-256 لملفات النماذج التي جرى القياس عليها؛ ليس تحققًا تلقائيًا وقت التشغيل. النماذج في `.local/ocr-cache`، والعينات والنتائج التفصيلية في `05_Data`، وكلها مستبعدة من Git. تقرير القياس المجمع يحفظ مع الكود دون فواتير حقيقية أو بيانات حسابات.

مراجع التنفيذ: [واجهة PaddleOCR ونماذجها](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)، [تحويلات OpenCV](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html)، [معيار الخصائص الأمنية وQR الرسمي](https://www.zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards_vF.pdf)، و[معيار UBL XML الرسمي](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vTrack.pdf). تستخدم البيئة PaddleOCR 3.7.0 وPaddlePaddle 3.3.1 وPaddleX 3.7.2 وPyMuPDF 1.28.2 وOpenCV 4.10.0 وpypdf 6.18.0، مع نماذج v5 المحددة في الكود.

آخر إصلاح: `pymupdf-paddle-hybrid-v5` و`labels-and-columns-v4` للصور المائلة والعناوين المختلطة والجداول متعددة السطور. [نتائج الإصلاح](../../../06_Testing_Evaluation/Results/PHOTO_INVOICE_EXTRACTION_RESULTS_AR.md).
