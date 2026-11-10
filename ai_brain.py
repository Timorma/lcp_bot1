
import os
import json
import logging
import math
from groq import Groq

logger = logging.getLogger("ICB_AI")

MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
API_KEY = os.getenv("GROQ_API_KEY", "")

SYSTEM_PROMPT = """
أنت طبقة التفسير البحثي في نظام ICB.

مهمتك تفسير بيانات التحليل الفني المقدمة لك فقط.

قواعد صارمة:
1. لا تخترع أسعارا أو مستويات أو بيانات.
2. لا تدّع أن مدرسة تحليلية فُحصت ما لم توجد أدلة فعلية عليها في المدخلات.
3. افصل بين الحقائق المحسوبة والفرضيات التفسيرية.
4. اشرح توافق وتعارض الأطر الزمنية.
5. وضح الأدلة المؤيدة والمعارضة لكل قراءة.
6. اذكر البيانات الناقصة التي تمنع الوصول إلى استنتاج.
7. لا تحول درجة الثقة الداخلية إلى احتمال نجاح.
8. لا تقدم توصيات شراء أو بيع أو دخول أو خروج أو أهداف أو وقف خسارة.
9. لا تستخدم لغة الجزم أو ضمان النتائج.
10. اكتب باللغة العربية الواضحة والمنظمة.

هيكل التقرير:
- قراءة عامة للبيانات.
- الأدلة المؤيدة للاتجاه الرئيسي.
- الأدلة المعارضة.
- تفسير اختلاف الأطر الزمنية.
- قراءة الدعم والمقاومة المحسوبة.
- ما لا يستطيع النظام إثباته حاليا.
- خلاصة بحثية محايدة.
"""


def clean_data(value):
    if isinstance(value, dict):
        return {
            str(key): clean_data(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [clean_data(item) for item in value]

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, 6)

    if hasattr(value, "item"):
        try:
            return clean_data(value.item())
        except Exception:
            return str(value)

    if value is None or isinstance(value, (str, int, bool)):
        return value

    return str(value)


def build_ai_payload(symbol, analysis):
    summary = analysis.get("summary", {})
    frames = analysis.get("timeframes", {})

    selected_frames = {}

    for timeframe, result in frames.items():
        if not isinstance(result, dict):
            continue

        selected_frames[timeframe] = {
            "bias": result.get("bias"),
            "confidence": result.get("confidence"),
            "signed_strength": result.get("signed_strength"),
            "last_close": result.get("last_close"),
            "atr": result.get("atr"),
            "volatility_pct": result.get("volatility_pct"),
            "evidence": result.get("evidence", [])
        }

    payload = {
        "symbol": symbol,
        "summary": summary,
        "timeframes": selected_frames,
        "warnings": analysis.get("warnings", [])
    }

    return clean_data(payload)


def interpret_analysis(symbol, analysis):
    if not API_KEY:
        return "⚠️ مفتاح GROQ_API_KEY غير موجود في إعدادات التشغيل."

    if not isinstance(analysis, dict):
        return "تعذر إرسال نتائج التحليل إلى عقل ICB."

    try:
        client = Groq(
            api_key=API_KEY,
            timeout=45.0,
            max_retries=1
        )

        payload = build_ai_payload(symbol, analysis)

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":")
                    )
                }
            ],
            temperature=0.2,
            max_completion_tokens=1400
        )

        result = response.choices[0].message.content

        if not result:
            return "لم يُرجع Groq تفسيرًا لهذه البيانات."

        return result.strip()

    except Exception:
        logger.exception("Groq interpretation failed")
        return (
            "⚠️ تعذر الحصول على تفسير الذكاء الاصطناعي. "
            "نتائج المحرك الحسابي ما زالت متاحة."
        )
