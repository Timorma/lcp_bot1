import os
import json
import math
import logging
import time
from datetime import datetime, date
from groq import Groq

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_TIMEOUT = 45
GROQ_MAX_RETRIES = 2
MAX_INPUT_CHARS = 12000
MAX_OUTPUT_TOKENS = 900

SYSTEM_PROMPT = """
أنت محلل أسواق محترف داخل منظومة ICB.
مهمتك تحويل نتائج التحليل الحسابي إلى صفقة واضحة وصارمة بأسلوب قنوات التوصيات القوية.

قواعد صارمة جداً:
1. لا تخترع أي سعر أو مستوى غير موجود في البيانات المرسلة.
2. اعتمد بشكل أساسي على:
   - هيكل السوق (BOS / CHoCH)
   - Order Blocks و Fair Value Gaps إن وجدت
   - Candle Range Theory (Accumulation / Manipulation / Distribution)
   - مناطق السيولة والدعم والمقاومة المحسوبة
3. الإطار المرجعي الأساسي هو 4 ساعات.
4. قدم صفقة واحدة فقط.
5. استخدم اسم الأداة الموجود في البيانات (مثل XAUUSD أو BTCUSDT أو GOLD).
6. الصفقة يجب أن تحتوي على:
   - الاتجاه (شراء أو بيع)
   - منطقة الدخول أو سعر الدخول
   - وقف الخسارة
   - الهدف 1
   - الهدف 2
7. نسبة المخاطرة للعائد لا تقل عن 1:2.
8. كن مختصرًا وحازمًا جداً. ممنوع الكلام الإنشائي الطويل.
9. إذا كانت الظروف غير واضحة أو متعارضة بقوة، اكتب فقط:
   "لا توجد صفقة واضحة حالياً"
10. لا تستخدم كلمات مثل "موصى به" أو "ادخل الآن". استخدم "صفقة بحثية مقترحة".

شكل الرد المطلوب بالضبط (لا تغيره):

📊 ICB | صفقة بحثية

الأداة: [اسم الأداة من البيانات]
الاتجاه: [شراء / بيع]
الإطار: 4H

📍 الدخول: [المنطقة أو السعر]
🛑 الوقف: [السعر]
🎯 الهدف 1: [السعر]
🎯 الهدف 2: [السعر]

📌 السبب:
• [سبب مختصر 1]
• [سبب مختصر 2]
• [سبب مختصر 3]

⚠️ ملاحظة: صفقة بحثية تعليمية مبنية على الهيكل الحالي.
"""

class ICBDataEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                value = float(obj)
                return value if math.isfinite(value) else None
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        try:
            import pandas as pd
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            if pd.isna(obj):
                return None
        except (ImportError, TypeError, ValueError):
            pass
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)

def clean_data(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): clean_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_data(item) for item in value]
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            number = float(value)
            return number if math.isfinite(number) else None
        if isinstance(value, np.ndarray):
            return clean_data(value.tolist())
    except ImportError:
        pass
    try:
        import pandas as pd
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return clean_data(value.item())
        except Exception:
            pass
    return str(value)

def _serialize_analysis(analysis):
    cleaned = clean_data(analysis)
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), cls=ICBDataEncoder)

def _extract_payload(analysis):
    if not isinstance(analysis, dict):
        return {"error": "Invalid analysis structure"}
    return clean_data({
        "summary": analysis.get("summary", {}),
        "groups": analysis.get("groups", {}),
        "timeframes": analysis.get("timeframes", {}),
        "warnings": analysis.get("warnings", [])
    })

def _safe_list(value, limit=None):
    if not isinstance(value, (list, tuple)):
        return []
    result = list(value)
    return result if limit is None else result[:limit]

def _compact_payload(payload):
    compact = {
        "summary": payload.get("summary", {}),
        "groups": payload.get("groups", {}),
        "warnings": _safe_list(payload.get("warnings", []), 10),
        "timeframes": {}
    }
    for timeframe, result in payload.get("timeframes", {}).items():
        if not isinstance(result, dict):
            continue
        compact["timeframes"][timeframe] = {
            "available": result.get("available"),
            "error": result.get("error"),
            "bias": result.get("bias"),
            "score": result.get("score"),
            "confidence": result.get("confidence"),
            "last_close": result.get("last_close"),
            "atr": result.get("atr"),
            "structure": result.get("structure"),
            "ema": result.get("ema"),
            "support": _safe_list(result.get("support", []), 4),
            "resistance": _safe_list(result.get("resistance", []), 4),
            "evidence": _safe_list(result.get("evidence", []), 5),
            "warnings": _safe_list(result.get("warnings", []), 3)
        }
    return compact

def _minimal_payload(payload):
    minimal = {
        "summary": payload.get("summary", {}),
        "groups": payload.get("groups", {}),
        "warnings": _safe_list(payload.get("warnings", []), 8),
        "timeframes": {}
    }
    for timeframe, result in payload.get("timeframes", {}).items():
        if not isinstance(result, dict):
            continue
        minimal["timeframes"][timeframe] = {
            "available": result.get("available"),
            "bias": result.get("bias"),
            "score": result.get("score"),
            "last_close": result.get("last_close"),
            "atr": result.get("atr"),
            "structure": result.get("structure")
        }
    return minimal

def _build_user_prompt(payload):
    stages = [payload, _compact_payload(payload), _minimal_payload(payload)]
    for index, candidate in enumerate(stages):
        serialized = _serialize_analysis(candidate)
        if len(serialized) <= MAX_INPUT_CHARS:
            logger.info("AI payload prepared: stage=%s chars=%s", index + 1, len(serialized))
            return (
                "حلل البيانات التالية وقدم صفقة بحثية واضحة حسب التعليمات.\n"
                "الإطار الأساسي المطلوب: 4 ساعات.\n"
                "BEGIN_DATA\n" + serialized + "\nEND_DATA"
            )
    raise ValueError("AI payload exceeds the configured size limit")

def _fallback_report(analysis, error=None):
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}
    bias = summary.get("bias", "غير متاح")
    score = summary.get("score", "غير متاح")
    lines = [
        "📊 ICB | صفقة بحثية",
        "",
        "تعذر الحصول على تفسير الذكاء الاصطناعي حالياً.",
        f"الحالة العامة: {bias}",
        f"الدرجة: {score}",
        "",
        "لا توجد صفقة واضحة حالياً."
    ]
    if error:
        lines.append(f"السبب: {error}")
    return "\n".join(lines)

def _get_client():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=GROQ_API_KEY, timeout=GROQ_TIMEOUT, max_retries=0)

def _get_status_code(error):
    return getattr(error, "status_code", None)

def interpret_analysis(analysis):
    if not isinstance(analysis, dict):
        return "تعذر تفسير البيانات: بنية التحليل غير صحيحة."
    if not analysis.get("summary"):
        return _fallback_report(analysis, "ملخص التحليل غير متاح")

    try:
        payload = _extract_payload(analysis)
        user_prompt = _build_user_prompt(payload)
    except Exception as error:
        logger.error("AI payload preparation failed: %s", type(error).__name__)
        return _fallback_report(analysis, "تعذر تجهيز بيانات التفسير")

    last_error = None
    for attempt in range(GROQ_MAX_RETRIES):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.15,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                top_p=1,
                stream=False
            )
            if not response.choices:
                raise RuntimeError("Groq returned no choices")
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise RuntimeError("Groq returned empty response")
            return content.strip()
        except Exception as error:
            last_error = error
            status_code = _get_status_code(error)
            logger.warning(
                "AI interpretation attempt %s failed: type=%s status=%s",
                attempt + 1, type(error).__name__, status_code
            )
            if status_code == 413:
                break
            if attempt + 1 < GROQ_MAX_RETRIES:
                time.sleep(attempt + 1)

    logger.error("AI interpretation unavailable: %s", type(last_error).__name__ if last_error else "Unknown")
    return _fallback_report(analysis, "خدمة التفسير غير متاحة حاليا")

def split_text(text, max_length=3000):
    if not text:
        return []
    text = str(text).strip()
    if not text:
        return []
    chunks = []
    current = ""
    paragraphs = text.splitlines()
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            candidate = current + "\n"
            if len(candidate) <= max_length:
                current = candidate
            continue
        while len(paragraph) > max_length:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(paragraph[:max_length])
            paragraph = paragraph[max_length:]
        candidate = current + "\n" + paragraph if current else paragraph
        if len(candidate) > max_length:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks

def get_ai_status():
    return {
        "provider": "Groq",
        "configured": bool(GROQ_API_KEY),
        "model": GROQ_MODEL,
        "timeout_seconds": GROQ_TIMEOUT,
        "max_retries": GROQ_MAX_RETRIES,
        "max_input_chars": MAX_INPUT_CHARS,
        "max_output_tokens": MAX_OUTPUT_TOKENS
    }