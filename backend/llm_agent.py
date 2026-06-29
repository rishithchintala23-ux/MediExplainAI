"""
llm_agent.py – LLM Integration & AI Summary Generator
======================================================
/* CHANGES */
- Feature 1: Added bn (Bengali), mr (Marathi), kn (Kannada) to LANGUAGE_MAP.
             Strengthened _language_instruction() — now placed at TOP of every prompt,
             with explicit instruction to translate medical terms and never switch to English.
- Feature 4: Rewrote _SAFETY_SYSTEM_PROMPT with warm best-friend-with-medical-background
             personality (no rigid headers, uses "you", casual connectors, celebrates
             good results, flags concerns gently).
             Rewrote generate_summary() and answer_question() user prompts to be
             conversational, personal, and flowing — not clinical or robotic.
- Feature 5: _fallback_summary() now respects the language parameter, using a per-language
             dict of pre-translated phrases for key static strings.
- No changes to safety guardrails, RAG grounding, or medical disclaimers.

Architecture Role: Layer 6 – Explanation Generator
               Layer 7 – Interactive Q&A Agent
Responsibility:
    - Generate calm, patient-friendly AI summaries of lab results (RAG-augmented)
    - Answer user questions via a RAG-limited Q&A agent
    - Enforce strict safety guardrails on every LLM call
    - Inject the required disclaimer into every response
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported Languages (12 total)
# ---------------------------------------------------------------------------
LANGUAGE_MAP = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "es": "Spanish",
    "fr": "French",
    "ar": "Arabic",
    "zh": "Chinese (Simplified)",
    "pt": "Portuguese",
    "bn": "Bengali",
    "mr": "Marathi",
}


def _language_instruction(language_code: str) -> str:
    """
    Returns a STRONG language enforcement instruction to inject at the
    TOP of every LLM prompt. For English, returns an empty string.
    """
    lang_name = LANGUAGE_MAP.get(language_code, "English")
    if language_code == "en":
        return ""
    return (
        f"CRITICAL LANGUAGE RULE: You MUST respond ENTIRELY in {lang_name}. "
        f"Every single word of your response must be in {lang_name}. "
        f"Do NOT switch to English at any point — not even for medical terms. "
        f"Translate or transliterate medical terms naturally into {lang_name}. "
        f"If you do not follow this rule, your response will be rejected.\n\n"
    )


# ---------------------------------------------------------------------------
# Fallback phrase translations (for _fallback_summary when LLM is unavailable)
# ---------------------------------------------------------------------------
_FALLBACK_PHRASES = {
    "en": {
        "stable_msg":   "Everything looks quite stable overall — that's genuinely good news! 🎉",
        "monitor_msg":  "Most things look really healthy, though a couple of values are worth keeping a gentle eye on.",
        "moderate_msg": "A few values are outside their usual range — worth a chat with your doctor soon.",
        "elevated_msg": "Several values are outside the usual range. Please reach out to your doctor soon — they'll know exactly how to help.",
        "all_normal":   "All your values are within the normal, healthy range. That's wonderful — take a moment to appreciate how well your body is doing!",
        "all_normal2":  "Of course, it's always a good idea to share your full results with your doctor just to be sure.",
        "noticed":      "💡 Something interesting I noticed:",
        "educational":  "(This is general educational context, not a diagnosis.)",
        "disclaimer":   "⚠️ *This is informational only. Please consult a healthcare professional for medical advice.*",
    },
    "hi": {
        "stable_msg":   "कुल मिलाकर सब कुछ काफी स्थिर दिख रहा है — यह सच में अच्छी खबर है! 🎉",
        "monitor_msg":  "ज़्यादातर चीज़ें बहुत अच्छी दिख रही हैं, हालांकि कुछ मान ध्यान देने योग्य हैं।",
        "moderate_msg": "कुछ मान सामान्य सीमा से थोड़े बाहर हैं — जल्द ही अपने डॉक्टर से बात करना अच्छा रहेगा।",
        "elevated_msg": "कई मान सामान्य सीमा से बाहर हैं। कृपया जल्द अपने डॉक्टर से संपर्क करें।",
        "all_normal":   "आपके सभी मान सामान्य, स्वस्थ सीमा के भीतर हैं। यह बहुत अच्छा है!",
        "all_normal2":  "अपने डॉक्टर से पूरे परिणाम साझा करना हमेशा अच्छा विचार है।",
        "noticed":      "💡 मैंने कुछ दिलचस्प नोट किया:",
        "educational":  "(यह सामान्य शैक्षिक जानकारी है, निदान नहीं।)",
        "disclaimer":   "⚠️ *यह केवल जानकारी के लिए है। चिकित्सा सलाह के लिए कृपया स्वास्थ्य पेशेवर से परामर्श लें।*",
    },
    "te": {
        "stable_msg":   "మొత్తంగా అన్నీ చాలా స్థిరంగా ఉన్నాయి — ఇది నిజంగా మంచి వార్త! 🎉",
        "monitor_msg":  "చాలా విషయాలు చాలా ఆరోగ్యంగా ఉన్నాయి, కానీ కొన్ని విలువలపై శ్రద్ధ పెట్టండి.",
        "moderate_msg": "కొన్ని విలువలు సాధారణ పరిధికి మించి ఉన్నాయి — త్వరలో డాక్టర్‌తో మాట్లాడండి.",
        "elevated_msg": "చాలా విలువలు సాధారణ పరిధి మించి ఉన్నాయి. దయచేసి డాక్టర్‌ని సంప్రదించండి.",
        "all_normal":   "మీ అన్ని విలువలు సాధారణ, ఆరోగ్యకరమైన పరిధిలో ఉన్నాయి. అద్భుతం!",
        "all_normal2":  "మీ పూర్తి ఫలితాలను డాక్టర్‌తో పంచుకోవడం మంచిది.",
        "noticed":      "💡 నేను గమనించిన ఆసక్తికరమైన విషయం:",
        "educational":  "(ఇది సాధారణ విద్యా సమాచారం, రోగ నిర్ధారణ కాదు.)",
        "disclaimer":   "⚠️ *ఇది కేవలం సమాచారం మాత్రమే. వైద్య సలహా కోసం దయచేసి వైద్య నిపుణులను సంప్రదించండి.*",
    },
    "ta": {
        "stable_msg":   "ஒட்டுமொத்தமாக எல்லாம் மிகவும் நிலையாக இருக்கிறது — இது நிஜமாகவே நல்ல செய்தி! 🎉",
        "monitor_msg":  "பெரும்பாலானவை மிகவும் ஆரோக்கியமாக இருக்கின்றன, ஆனால் சில மதிப்புகளை கவனிக்கவும்.",
        "moderate_msg": "சில மதிப்புகள் இயல்பு வரம்பைத் தாண்டியுள்ளன — விரைவில் உங்கள் மருத்துவரிடம் பேசுங்கள்.",
        "elevated_msg": "பல மதிப்புகள் இயல்பு வரம்பைத் தாண்டியுள்ளன. தயவுசெய்து விரைவில் மருத்துவரை அணுகுங்கள்.",
        "all_normal":   "உங்கள் அனைத்து மதிப்புகளும் இயல்பான, ஆரோக்கியமான வரம்பிற்குள் உள்ளன. அருமை!",
        "all_normal2":  "உங்கள் முழு முடிவுகளையும் மருத்துவரிடம் பகிர்வது நல்லது.",
        "noticed":      "💡 நான் கவனித்த சுவாரஸ்யமான விஷயம்:",
        "educational":  "(இது பொது கல்வித் தகவல், நோய் கண்டறிதல் அல்ல.)",
        "disclaimer":   "⚠️ *இது தகவல் நோக்கத்திற்காக மட்டுமே. மருத்துவ ஆலோசனைக்கு மருத்துவரை அணுகவும்.*",
    },
    "kn": {
        "stable_msg":   "ಒಟ್ಟಾರೆ ಎಲ್ಲವೂ ಸ್ಥಿರವಾಗಿದೆ — ಇದು ನಿಜವಾಗಿಯೂ ಒಳ್ಳೆಯ ಸುದ್ದಿ! 🎉",
        "monitor_msg":  "ಹೆಚ್ಚಿನ ವಿಷಯಗಳು ಆರೋಗ್ಯಕರವಾಗಿವೆ, ಆದರೆ ಕೆಲವು ಮೌಲ್ಯಗಳನ್ನು ಗಮನಿಸಬೇಕು.",
        "moderate_msg": "ಕೆಲವು ಮೌಲ್ಯಗಳು ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಯಿಂದ ಹೊರಗಿವೆ — ಶೀಘ್ರದಲ್ಲೇ ನಿಮ್ಮ ವೈದ್ಯರೊಂದಿಗೆ ಮಾತನಾಡಿ.",
        "elevated_msg": "ಅನೇಕ ಮೌಲ್ಯಗಳು ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಯ ಹೊರಗಿವೆ. ದಯವಿಟ್ಟು ತಕ್ಷಣ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
        "all_normal":   "ನಿಮ್ಮ ಎಲ್ಲಾ ಮೌಲ್ಯಗಳು ಸಾಮಾನ್ಯ, ಆರೋಗ್ಯಕರ ವ್ಯಾಪ್ತಿಯಲ್ಲಿವೆ. ಅದ್ಭುತ!",
        "all_normal2":  "ನಿಮ್ಮ ಸಂಪೂರ್ಣ ಫಲಿತಾಂಶಗಳನ್ನು ವೈದ್ಯರೊಂದಿಗೆ ಹಂಚಿಕೊಳ್ಳುವುದು ಯಾವಾಗಲೂ ಉತ್ತಮ.",
        "noticed":      "💡 ನಾನು ಗಮನಿಸಿದ ಆಸಕ್ತಿಕರ ವಿಷಯ:",
        "educational":  "(ಇದು ಸಾಮಾನ್ಯ ಶೈಕ್ಷಣಿಕ ಮಾಹಿತಿ, ರೋಗ ನಿರ್ಣಯವಲ್ಲ.)",
        "disclaimer":   "⚠️ *ಇದು ಮಾಹಿತಿ ಉದ್ದೇಶಕ್ಕಾಗಿ ಮಾತ್ರ. ವೈದ್ಯಕೀಯ ಸಲಹೆಗಾಗಿ ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ.*",
    },
    "es": {
        "stable_msg":   "En general todo se ve bastante estable — ¡esa es una muy buena noticia! 🎉",
        "monitor_msg":  "La mayoría de las cosas se ven muy bien, aunque hay un par de valores que vale la pena vigilar.",
        "moderate_msg": "Algunos valores están fuera del rango habitual — vale la pena hablar con tu médico pronto.",
        "elevated_msg": "Varios valores están fuera del rango normal. Por favor contacta a tu médico pronto.",
        "all_normal":   "¡Todos tus valores están dentro del rango normal y saludable! ¡Eso es maravilloso!",
        "all_normal2":  "Siempre es buena idea compartir tus resultados completos con tu médico.",
        "noticed":      "💡 Algo interesante que noté:",
        "educational":  "(Esta es información educativa general, no un diagnóstico.)",
        "disclaimer":   "⚠️ *Esto es solo informativo. Por favor consulta a un profesional de la salud para asesoramiento médico.*",
    },
    "fr": {
        "stable_msg":   "Dans l'ensemble, tout semble assez stable — c'est vraiment une bonne nouvelle ! 🎉",
        "monitor_msg":  "La plupart des choses sont très bonnes, bien que quelques valeurs méritent attention.",
        "moderate_msg": "Certaines valeurs sont en dehors de la plage habituelle — il vaut mieux en parler à votre médecin.",
        "elevated_msg": "Plusieurs valeurs sont en dehors de la plage normale. Veuillez consulter votre médecin rapidement.",
        "all_normal":   "Toutes vos valeurs sont dans la plage normale et saine. C'est merveilleux !",
        "all_normal2":  "Il est toujours bon de partager vos résultats complets avec votre médecin.",
        "noticed":      "💡 Quelque chose d'intéressant que j'ai remarqué :",
        "educational":  "(Ceci est une information éducative générale, pas un diagnostic.)",
        "disclaimer":   "⚠️ *Ceci est uniquement informatif. Veuillez consulter un professionnel de santé pour tout conseil médical.*",
    },
    "ar": {
        "stable_msg":   "يبدو كل شيء مستقراً بشكل عام — هذا خبر جيد حقاً! 🎉",
        "monitor_msg":  "معظم الأمور تبدو جيدة جداً، لكن بعض القيم تستحق المتابعة.",
        "moderate_msg": "بعض القيم خارج النطاق المعتاد — يُنصح بالتحدث مع طبيبك قريباً.",
        "elevated_msg": "عدة قيم خارج النطاق الطبيعي. يرجى التواصل مع طبيبك بأسرع وقت.",
        "all_normal":   "جميع قيمك ضمن النطاق الطبيعي والصحي. هذا رائع!",
        "all_normal2":  "من الجيد دائماً مشاركة نتائجك الكاملة مع طبيبك.",
        "noticed":      "💡 شيء مثير للاهتمام لاحظته:",
        "educational":  "(هذه معلومات تعليمية عامة، وليست تشخيصاً.)",
        "disclaimer":   "⚠️ *هذا للأغراض المعلوماتية فقط. يرجى استشارة متخصص رعاية صحية للحصول على المشورة الطبية.*",
    },
    "zh": {
        "stable_msg":   "总体来看，一切都相当稳定——这真是个好消息！🎉",
        "monitor_msg":  "大多数指标看起来非常健康，不过有几个数值值得留意。",
        "moderate_msg": "有几个数值超出了正常范围——最好尽快和您的医生谈谈。",
        "elevated_msg": "多项数值超出了正常范围，请尽快联系您的医生。",
        "all_normal":   "您所有的数值都在正常健康范围内，太棒了！",
        "all_normal2":  "将您的完整结果与医生分享始终是个好主意。",
        "noticed":      "💡 我注意到一个有趣的现象：",
        "educational":  "（这是一般性教育信息，不是诊断。）",
        "disclaimer":   "⚠️ *本内容仅供参考。请咨询医疗专业人员以获取医疗建议。*",
    },
    "pt": {
        "stable_msg":   "No geral, tudo está bastante estável — essa é uma ótima notícia! 🎉",
        "monitor_msg":  "A maioria das coisas parece muito saudável, mas alguns valores merecem atenção.",
        "moderate_msg": "Alguns valores estão fora do intervalo habitual — vale conversar com seu médico em breve.",
        "elevated_msg": "Vários valores estão fora do intervalo normal. Por favor, entre em contato com seu médico em breve.",
        "all_normal":   "Todos os seus valores estão dentro da faixa normal e saudável. Que ótimo!",
        "all_normal2":  "Sempre é uma boa ideia compartilhar seus resultados completos com seu médico.",
        "noticed":      "💡 Algo interessante que notei:",
        "educational":  "(Esta é uma informação educativa geral, não um diagnóstico.)",
        "disclaimer":   "⚠️ *Isto é apenas informativo. Por favor consulte um profissional de saúde para aconselhamento médico.*",
    },
    "bn": {
        "stable_msg":   "সামগ্রিকভাবে সব কিছু বেশ স্থিতিশীল — এটি সত্যিই একটি সুখবর! 🎉",
        "monitor_msg":  "বেশিরভাগ জিনিস খুব ভালো দেখাচ্ছে, তবে কিছু মান লক্ষ্য রাখার মতো।",
        "moderate_msg": "কিছু মান স্বাভাবিক পরিসরের বাইরে — শীঘ্রই আপনার ডাক্তারের সঙ্গে কথা বলুন।",
        "elevated_msg": "বেশ কিছু মান স্বাভাবিক পরিসরের বাইরে। দয়া করে দ্রুত ডাক্তারের সাথে যোগাযোগ করুন।",
        "all_normal":   "আপনার সমস্ত মান স্বাভাবিক, সুস্থ পরিসরের মধ্যে রয়েছে। অসাধারণ!",
        "all_normal2":  "আপনার সম্পূর্ণ ফলাফল ডাক্তারের সাথে ভাগ করে নেওয়া সবসময় ভালো।",
        "noticed":      "💡 আমি একটি আকর্ষণীয় বিষয় লক্ষ্য করেছি:",
        "educational":  "(এটি সাধারণ শিক্ষামূলক তথ্য, রোগ নির্ণয় নয়।)",
        "disclaimer":   "⚠️ *এটি শুধুমাত্র তথ্যমূলক। চিকিৎসা পরামর্শের জন্য দয়া করে স্বাস্থ্যসেবা পেশাদারের সাথে পরামর্শ করুন।*",
    },
    "mr": {
        "stable_msg":   "एकूणच सर्व काही बरेच स्थिर दिसत आहे — हे खरोखरच चांगली बातमी आहे! 🎉",
        "monitor_msg":  "बहुतेक गोष्टी खूप चांगल्या दिसत आहेत, पण काही मूल्यांवर लक्ष ठेवणे योग्य आहे.",
        "moderate_msg": "काही मूल्ये सामान्य मर्यादेबाहेर आहेत — लवकरच तुमच्या डॉक्टरांशी बोलणे उत्तम.",
        "elevated_msg": "अनेक मूल्ये सामान्य मर्यादेबाहेर आहेत. कृपया लवकरात लवकर डॉक्टरांशी संपर्क साधा.",
        "all_normal":   "तुमची सर्व मूल्ये सामान्य, निरोगी मर्यादेत आहेत. हे खूप छान आहे!",
        "all_normal2":  "तुमचे संपूर्ण निकाल डॉक्टरांशी शेअर करणे नेहमीच चांगले असते.",
        "noticed":      "💡 मला एक मनोरंजक गोष्ट लक्षात आली:",
        "educational":  "(हे सामान्य शैक्षणिक माहिती आहे, निदान नाही.)",
        "disclaimer":   "⚠️ *हे केवळ माहितीसाठी आहे. वैद्यकीय सल्ल्यासाठी कृपया आरोग्य व्यावसायिकाचा सल्ला घ्या.*",
    },
}


def _get_fallback_phrases(language_code: str) -> dict:
    """Return the fallback phrase dict for the given language, defaulting to English."""
    return _FALLBACK_PHRASES.get(language_code, _FALLBACK_PHRASES["en"])


# ---------------------------------------------------------------------------
# Safety System Prompt — Warm Best-Friend Persona (applied to EVERY LLM call)
# ---------------------------------------------------------------------------
_SAFETY_SYSTEM_PROMPT = """You are the user's warm, knowledgeable best friend who happens to have a medical background.

YOUR PERSONALITY:
- You speak like a real person — not a robot, not a doctor reading off a chart.
- You use "you" and "your" constantly. You notice things. You ask gentle follow-up questions sometimes.
- You use casual, human connectors naturally: "So here's the thing...", "Good news — ", "One thing worth keeping an eye on...", "Don't panic, but...", "This one's actually pretty straightforward — ", "Honestly, this looks...", "I did notice something worth mentioning...", "Here's what caught my eye..."
- You NEVER say "the patient" — always "you".
- You NEVER use rigid headers or bullet bullet lists unless absolutely necessary.
- You weave all findings into a single flowing conversation, not a checklist.
- You celebrate good results warmly: "Your hemoglobin looks great, by the way!"
- You flag concerns gently without causing panic: "One thing I'd want to keep an eye on is..."
- You end every response with an encouraging, personal sign-off, then the required disclaimer on a new line.

SAFETY RULES (NEVER break these):
✅ Always use "might", "could", "may suggest", "it's worth asking your doctor about"
✅ Always add the medical disclaimer at the end of every response
✅ Always use an empathetic, educational tone
✅ For emergency/critical values: gently but firmly urge seeing a doctor
❌ Never prescribe medication or suggest dosages
❌ Never diagnose a disease directly ("You have X")
❌ Never replace a doctor's judgment
❌ Never cause unnecessary panic

LIFESTYLE SUGGESTIONS:
When relevant, weave in 1–2 general educational lifestyle suggestions naturally (not as a list). Always frame as general health education ("Many people find that...", "General health guidance suggests...") and always note that a doctor's input is important."""


def _get_llm():
    """
    Return the LLM client.
    - Uses Groq Llama 3.3 if GROQ_API_KEY is set.
    - Raises a clear error if the key is missing.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set or invalid. "
            "Please set it in your environment or .env file."
        )
    from langchain_groq import ChatGroq
    return ChatGroq(model="llama-3.3-70b-versatile", api_key=api_key, temperature=0.4)


def _format_findings_for_prompt(results: list, risk_category: str) -> str:
    """Format test results into a readable summary for the LLM prompt."""
    lines = [f"Overall Risk Category: {risk_category}\n", "Lab Test Results:"]
    for r in results:
        if hasattr(r, '__dict__'):
            r_dict = r.__dict__
        else:
            r_dict = r
        status = r_dict.get("status", "Unknown")
        name = r_dict.get("test_name", "Unknown Test")
        value = r_dict.get("measured_value", "N/A")
        unit = r_dict.get("unit", "")
        ref = r_dict.get("reference_range", "N/A")
        is_critical = r_dict.get("is_critical", False)

        critical_flag = " (CRITICAL)" if is_critical else ""
        lines.append(f"  - {name}: {value} {unit} (Ref: {ref}) → Status: {status}{critical_flag}")
    return "\n".join(lines)


class LLMAgent:
    """
    Handles all LLM interactions with strict safety prompting.
    Uses RAGPipeline to retrieve grounded context before generation.
    """

    def __init__(self, rag_pipeline):
        self.rag = rag_pipeline
        self._llm = None  # Lazy initialisation

    def _get_client(self):
        """Lazy-load the LLM client."""
        if self._llm is None:
            self._llm = _get_llm()
        return self._llm

    # ------------------------------------------------------------------
    # Public Methods
    # ------------------------------------------------------------------

    def generate_summary(
        self,
        results: list,
        risk_score: float,
        risk_category: str,
        patterns: list,
        trends: list = None,
        language: str = "en",
    ) -> str:
        """
        Generate a warm, conversational, patient-friendly AI summary.
        Language parameter controls the response language end-to-end.
        """
        # Build a search query for RAG retrieval
        abnormal_tests = [
            r.test_name if hasattr(r, "test_name") else r.get("test_name", "")
            for r in results
            if (r.status if hasattr(r, "status") else r.get("status")) in ("Low", "High")
        ]
        rag_query = (
            f"Lab report summary: {', '.join(abnormal_tests)} abnormal results "
            f"risk category {risk_category}"
            if abnormal_tests
            else "normal lab report results patient education"
        )

        context = self.rag.retrieve(rag_query, k=4)
        findings_text = _format_findings_for_prompt(results, risk_category)

        # Build pattern text
        pattern_lines = []
        for p in patterns:
            pattern_lines.append(p.get("message", ""))
        pattern_text = "\n".join(pattern_lines) if pattern_lines else "None detected."

        # Build trend text
        trend_lines = []
        if trends:
            for t in trends:
                trend_lines.append(
                    f" - {t['test_name']}: {t['historical_value']} -> {t['current_value']} "
                    f"{t['unit']} ({t['trend_type']}, {t['percent_change']}% change)"
                )
        trend_text = "\n".join(trend_lines) if trend_lines else "No historical data or significant trends."

        # Language instruction injected at TOP of prompt (Feature 1 + 4)
        lang_instruction = _language_instruction(language)

        user_prompt = f"""{lang_instruction}You're talking to someone who just got their lab results back. Write them a warm, personal, flowing summary — like a knowledgeable best friend who genuinely cares.

{findings_text}

Patterns detected (educational context only): {pattern_text}

Historical Trends:
{trend_text}

Medical Reference Context (use ONLY this for factual grounding — do not hallucinate):
\"\"\"
{context}
\"\"\"

HOW TO WRITE THIS (follow carefully):
1. Open with a warm, personal observation about how they're doing overall — vary your opener every time. Try openers like: "So I just looked through your results and honestly...", "Okay, first things first —", "Alright, let's talk through what I see here...", "I've gone through everything and here's the honest picture..." — never start the same way twice.
2. Reference 2–3 SPECIFIC test values naturally in conversation — say the actual number and reference range: "Your LDL came in at 145 mg/dL, which is a little above the usual target of under 100..." Do this for both normal and abnormal values.
3. Mention patterns or trends as if you noticed them yourself: "I also noticed something interesting — your values look like they've shifted a bit since last time, which is worth keeping an eye on."
4. Weave in 1–2 practical lifestyle suggestions naturally — not as a list, just as friendly conversation.
5. Celebrate anything that looks good: "Your hemoglobin is sitting beautifully, by the way — that's a great sign."
6. Flag any concerns gently, without panic: "One thing I'd want to keep an eye on is..." or "Don't stress about this, but..."
7. End with one warm, personal encouraging line.
8. On its own new line at the very end, add exactly: "⚠️ *This is informational only. Please consult a healthcare professional for medical advice.*"

Write it as one flowing piece of conversation — NO rigid headers, NO bullet point lists of test results. This should feel like a warm chat, not a medical report."""

        try:
            from langchain.schema import SystemMessage, HumanMessage
            llm = self._get_client()
            response = llm.invoke([
                SystemMessage(content=_SAFETY_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            return str(response.content)
        except EnvironmentError as exc:
            logger.warning("LLM unavailable: %s", exc)
            return self._fallback_summary(results, risk_category, patterns, trends, language)
        except Exception as exc:
            logger.error("LLM summary generation failed: %s", exc)
            return self._fallback_summary(results, risk_category, patterns, trends, language)

    def answer_question(self, question: str, report_context: str = "", language: str = "en") -> str:
        """
        Answer a user question about their lab report via RAG Q&A.
        Language parameter controls the response language end-to-end.
        """
        context = self.rag.retrieve(question, k=4)

        # Language instruction injected at TOP of prompt (Feature 1 + 4)
        lang_instruction = _language_instruction(language)

        user_prompt = f"""{lang_instruction}Your friend just texted you a medical question about their lab results. Answer them like a knowledgeable, warm friend — not a doctor reading from a textbook.

Their Report Summary (for context):
\"\"\"
{report_context if report_context else "Not provided."}
\"\"\"

Medical Reference Context (use ONLY this to answer — do not hallucinate):
\"\"\"
{context}
\"\"\"

Their question: {question}

HOW TO ANSWER:
- Jump straight into the answer — no "Great question!" fluff.
- Keep it conversational and concise — short paragraphs, natural language.
- Use a helpful analogy where it really helps ("Think of LDL like delivery trucks that drop off cholesterol to your arteries...")
- If their report shows a relevant value, reference it naturally: "In your case, yours is at X, which means..."
- Bold key medical terms the first time you use them so they're easy to spot.
- Do NOT use bullet lists or rigid headers — keep it flowing.
- End with one gentle follow-up nudge: "Does that make sense? Feel free to ask me anything else about your results! 😊"
- On its own new line at the very end, add exactly: "⚠️ *This is informational only. Please consult a healthcare professional for medical advice.*"

Remember: warm, genuine, human — like a text from a friend who knows medicine."""

        try:
            from langchain.schema import SystemMessage, HumanMessage
            llm = self._get_client()
            response = llm.invoke([
                SystemMessage(content=_SAFETY_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            return str(response.content)
        except EnvironmentError as exc:
            logger.warning("LLM unavailable: %s", exc)
            return (
                "I'm sorry, the AI assistant is currently unavailable — no API key is configured. "
                "Please set your GROQ_API_KEY to enable this feature.\n\n"
                "⚠️ This is informational only. Please consult a healthcare professional for medical advice."
            )
        except Exception as exc:
            logger.error("LLM Q&A failed: %s", exc)
            return (
                "I'm sorry, I wasn't able to process that question right now. "
                "Please try again or reach out to a healthcare professional.\n\n"
                "⚠️ This is informational only. Please consult a healthcare professional for medical advice."
            )

    # ------------------------------------------------------------------
    # Fallback (no LLM available) — respects language parameter (Feature 1)
    # ------------------------------------------------------------------

    def _fallback_summary(
        self, results: list, risk_category: str, patterns: list, trends: list = None, language: str = "en"
    ) -> str:
        """
        Rule-based fallback summary when LLM is unavailable.
        Uses pre-translated phrases for the selected language.
        """
        ph = _get_fallback_phrases(language)

        category_info = {
            "Stable":           ("🟢", ph["stable_msg"]),
            "Monitor":          ("🟡", ph["monitor_msg"]),
            "Moderate Concern": ("🟠", ph["moderate_msg"]),
            "Elevated Risk":    ("🔴", ph["elevated_msg"]),
        }
        icon, category_msg = category_info.get(risk_category, ("🔵", ph["stable_msg"]))

        lines = [
            f"{icon} **Overall: {risk_category}**",
            "",
            category_msg,
            "",
        ]

        abnormal = [
            r for r in results
            if (r.status if hasattr(r, "status") else r.get("status", "Normal")) in ("Low", "High")
        ]

        if not abnormal:
            lines.append(ph["all_normal"])
            lines.append(f"\n{ph['all_normal2']}\n")
        else:
            for r in abnormal:
                name = r.test_name if hasattr(r, "test_name") else r.get("test_name", "")
                status = r.status if hasattr(r, "status") else r.get("status", "")
                desc = (
                    r.status_description if hasattr(r, "status_description")
                    else r.get("status_description", "")
                )
                lines.append(f"Your **{name}** is currently {status.lower()}. {desc}")
                lines.append("")

        if patterns:
            lines.append("")
            lines.append(ph["noticed"])
            for p in patterns:
                lines.append(f"   {p.get('message', '')}")
            lines.append(f"   *{ph['educational']}*")

        lines.extend([
            "",
            ph["disclaimer"],
        ])

        return "\n".join(lines)
