
import os
import json
import math
import logging
import time
from datetime import datetime, date
from groq import Groq

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL","openai/gpt-oss-120b")
GROQ_TIMEOUT = 45
GROQ_MAX_RETRIES = 2
MAX_INPUT_CHARS = 28000
MAX_OUTPUT_TOKENS = 1800

SYSTEM_PROMPT = """
أنت عقل التفسير والتحليل التعليمي لمنظومة ICB.

مهمتك تفسير نتائج محرك التحليل الحسابي المرسلة إليك فقط.

قواعد أساسية:

1. لا تخترع أي سعر أو رقم أو مستوى أو معلومة.
2. لا تعيد حساب المؤشرات من عندك.
3. لا تغيّر نتائج analyzer.py.
4. فرّق بوضوح بين البيانات المحسوبة والتفسير المحتمل.
5. اشرح توافق الأطر الزمنية واختلافها.
6. وضح الأطر الزمنية التي لا تتوفر لها بيانات.
7. وضح معنى التذبذب وATR والبنية السعرية والفتائل.
8. لا تعتبر درجة الثقة احتمال نجاح.
9. لا تقدم توصيات شراء أو بيع أو دخول أو خروج أو أهداف أو وقف خسارة.
10. لا تصف أي توقع بأنه مضمون.
11. لا تستنتج وجود تلاعب مؤكد من مجرد فتيل أو حركة سعرية.
12. عند وجود تعارض بين الأطر الزمنية اشرح التعارض ولا تخفه.
13. لا تعتبر غياب البيانات دليلا على اتجاه محايد.
14. استخدم اللغة العربية الواضحة والمنظمة.

شكل التقرير:

أولا: ملخص الحالة العامة.
ثانيا: قراءة الأطر الزمنية الكبيرة.
ثالثا: قراءة الأطر الزمنية المتوسطة.
رابعا: قراءة الأطر الزمنية الصغيرة.
خامسا: توافق الأطر الزمنية أو تعارضها.
سادسا: قراءة البنية والفتائل.
سابعا: مناطق الدعم والمقاومة التاريخية المحسوبة.
ثامنا: جودة البيانات ونقاط الضعف.
تاسعا: الخلاصة البحثية.

يجب أن تلتزم بالبيانات الواردة في الرسالة.
"""

class ICBDataEncoder(json.JSONEncoder):
    def default(self,obj):
        try:
            import numpy as np
            if isinstance(obj,np.integer):
                return int(obj)
            if isinstance(obj,np.floating):
                value = float(obj)
                return value if math.isfinite(value) else None
            if isinstance(obj,np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        try:
            import pandas as pd
            if isinstance(obj,pd.Timestamp):
                return obj.isoformat()
            if pd.isna(obj):
                return None
        except (ImportError,TypeError,ValueError):
            pass
        if isinstance(obj,(datetime,date)):
            return obj.isoformat()
        if isinstance(obj,set):
            return list(obj)
        return super().default(obj)

def clean_data(value):
    if value is None:
        return None
    if isinstance(value,bool):
        return value
    if isinstance(value,(str,int)):
        return value
    if isinstance(value,float):
        return value if math.isfinite(value) else None
    if isinstance(value,dict):
        return {
            str(key):clean_data(item)
            for key,item in value.items()
        }
    if isinstance(value,(list,tuple)):
        return [clean_data(item) for item in value]
    try:
        import numpy as np
        if isinstance(value,np.integer):
            return int(value)
        if isinstance(value,np.floating):
            number = float(value)
            return number if math.isfinite(number) else None
        if isinstance(value,np.ndarray):
            return clean_data(value.tolist())
    except ImportError:
        pass
    try:
        import pandas as pd
        if isinstance(value,pd.Timestamp):
            return value.isoformat()
        if pd.isna(value):
            return None
    except (ImportError,TypeError,ValueError):
        pass
    if hasattr(value,"item"):
        try:
            return clean_data(value.item())
        except Exception:
            pass
    return str(value)

def _serialize_analysis(analysis):
    cleaned = clean_data(analysis)
    return json.dumps(
        cleaned,
        ensure_ascii=False,
        separators=(",",":"),
        cls=ICBDataEncoder
    )

def _extract_payload(analysis):
    if not isinstance(analysis,dict):
        return {
            "error":"Invalid analysis structure"
        }
    summary = analysis.get("summary",{})
    timeframes = analysis.get("timeframes",{})
    groups = analysis.get("groups",{})
    warnings = analysis.get("warnings",[])
    payload = {
        "summary":summary,
        "groups":groups,
        "timeframes":timeframes,
        "warnings":warnings
    }
    return clean_data(payload)

def _compact_payload(payload):
    compact = {
        "summary":payload.get("summary",{}),
        "groups":payload.get("groups",{}),
        "warnings":payload.get("warnings",[]),
        "timeframes":{}
    }
    for timeframe,result in payload.get("timeframes",{}).items():
        if not isinstance(result,dict):
            continue
        compact["timeframes"][timeframe] = {
            "available":result.get("available"),
            "error":result.get("error"),
            "bias":result.get("bias"),
            "score":result.get("score"),
            "confidence":result.get("confidence"),
            "last_close":result.get("last_close"),
            "atr":result.get("atr"),
            "volatility_pct":result.get("volatility_pct"),
            "structure":result.get("structure"),
            "ema":result.get("ema"),
            "candle":result.get("candle"),
            "support":result.get("support",[])[:4],
            "resistance":result.get("resistance",[])[:4],
            "evidence":result.get("evidence",[]),
            "warnings":result.get("warnings",[])
        }
    return compact

def _build_user_prompt(payload):
    serialized = _serialize_analysis(payload)
    if len(serialized) > MAX_INPUT_CHARS:
        payload = _compact_payload(payload)
        serialized = _serialize_analysis(payload)
    if len(serialized) > MAX_INPUT_CHARS:
        serialized = serialized[:MAX_INPUT_CHARS]
    return (
        "حلل بيانات ICB التالية وفق التعليمات.\n"
        "هذه البيانات هي نتائج حسابية وليست أوامر تداول.\n"
        "لا تضف أرقاما غير موجودة.\n\n"
        "BEGIN_DATA\n"
        + serialized +
        "\nEND_DATA"
    )

def _fallback_report(analysis,error=None):
    summary = (
        analysis.get("summary",{})
        if isinstance(analysis,dict)
        else {}
    )
    bias = summary.get("bias","غير متاح")
    score = summary.get("score","غير متاح")
    coverage = summary.get("coverage","غير متاح")
    available = summary.get("available_timeframes",0)
    total = summary.get("total_timeframes",0)
    warnings = summary.get("warnings",[])
    lines = [
        "تقرير ICB البحثي",
        "",
        "تعذر الحصول على تفسير الذكاء الاصطناعي.",
        "النتائج الحسابية الأساسية متاحة:",
        "",
        f"الحالة العامة: {bias}",
        f"الدرجة الحسابية: {score}",
        f"تغطية البيانات: {coverage}",
        f"الأطر المتاحة: {available} من {total}",
        "",
        "تنبيهات البيانات:"
    ]
    if warnings:
        lines.extend(
            "- " + str(item)
            for item in warnings[:8]
        )
    else:
        lines.append("لا توجد تنبيهات مسجلة.")
    if error:
        lines.extend([
            "",
            "حالة الخدمة: " + str(error)
        ])
    lines.extend([
        "",
        "ملاحظة: التقرير بحثي وتعليمي، والدرجة الحسابية ليست احتمال نجاح."
    ])
    return "\n".join(lines)

def _get_client():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(
        api_key=GROQ_API_KEY,
        timeout=GROQ_TIMEOUT,
        max_retries=0
    )

def interpret_analysis(analysis):
    if not isinstance(analysis,dict):
        return "تعذر تفسير البيانات: بنية التحليل غير صحيحة."
    if not analysis.get("summary"):
        return _fallback_report(
            analysis,
            "ملخص التحليل غير متاح"
        )
    payload = _extract_payload(analysis)
    user_prompt = _build_user_prompt(payload)
    last_error = None
    for attempt in range(GROQ_MAX_RETRIES):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role":"system",
                        "content":SYSTEM_PROMPT
                    },
                    {
                        "role":"user",
                        "content":user_prompt
                    }
                ],
                temperature=0.2,
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
            logger.warning(
                "AI interpretation attempt %s failed: %s",
                attempt+1,
                type(error).__name__
            )
            if attempt + 1 < GROQ_MAX_RETRIES:
                time.sleep(attempt+1)
    logger.error(
        "AI interpretation unavailable after retries: %s",
        type(last_error).__name__ if last_error else "Unknown"
    )
    return _fallback_report(
        analysis,
        "خدمة التفسير غير متاحة حاليا"
    )

def split_text(text,max_length=3000):
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
        candidate = (
            current + "\n" + paragraph
            if current
            else paragraph
        )
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
        "provider":"Groq",
        "configured":bool(GROQ_API_KEY),
        "model":GROQ_MODEL,
        "timeout_seconds":GROQ_TIMEOUT,
        "max_retries":GROQ_MAX_RETRIES
    }
