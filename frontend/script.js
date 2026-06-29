// script.js - MediExplain AI Frontend Controller (v3.0)
// CHANGES:
// Feature 1: getCurrentLanguage() helper added. Language sent in every /analyze and /ask call.
//            On language change: localStorage updated, ongoing speech cancelled, recognition.lang updated.
//            Added bn, mr, kn to LANG_STT_MAP, LANG_TTS_MAP, and T translations.
// Feature 2: speakText(text, lang) now accepts optional lang param for per-call language override.
//            Summary TTS uses lastAnalysisLanguage (not currentLang) so it matches the generated content.
//            stripMarkdown() now strips ---, HTML tags, warning symbols, *, # cleanly.
// Feature 3: LANG_STT_MAP expanded to 12 languages. recognition.lang updates on setLanguage().
// Feature 4: No frontend changes - personality rewrite is in llm_agent.py.
// Feature 5: lastAnalysisLanguage stored on every /analyze call.
//            appendBubble() sets data-lang on bot bubbles. Bubble TTS reads data-lang from the bubble.
"use strict";

const API_BASE = "";

// ── STATE ──────────────────────────────────────────────────
let uploadedTests = [], historicalTests = [], analysisResults = null, reportContext = "";
let currentLang = localStorage.getItem("medi_lang") || "en";
let lastAnalysisLanguage = currentLang; // Feature 5: tracks language used at /analyze time
let isSpeaking = false, speechUtterance = null;

// ── AUTH HELPERS ────────────────────────────────────────────
function getToken() { return sessionStorage.getItem("medi_token"); }
function getUserEmail() { return sessionStorage.getItem("medi_email") || ""; }
function isLoggedIn() { return !!getToken(); }

/** Feature 1: canonical language accessor used by all API calls */
function getCurrentLanguage() { return currentLang; }

function authHeaders(extra = {}) {
    const h = { "Content-Type": "application/json", ...extra };
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
}

async function authFetch(url, opts = {}) {
    opts.headers = authHeaders(opts.headers || {});
    const res = await fetch(url, opts);
    if (res.status === 401 && getToken()) {
        sessionStorage.removeItem("medi_token");
        sessionStorage.removeItem("medi_email");
        window.location.href = "auth.html";
        throw new Error("Session expired");
    }
    return res;
}

function logout() {
    sessionStorage.removeItem("medi_token");
    sessionStorage.removeItem("medi_email");
    window.location.href = "auth.html";
}

function initAuthUI() {
    const ub = document.getElementById("user-block");
    const lb = document.getElementById("btn-login-header");
    if (isLoggedIn()) {
        ub.classList.remove("hidden");
        lb.classList.add("hidden");
        const av = document.getElementById("user-avatar");
        av.title = getUserEmail();
    } else {
        ub.classList.add("hidden");
        lb.classList.remove("hidden");
    }
    document.getElementById("btn-logout")?.addEventListener("click", logout);
    document.getElementById("btn-history")?.addEventListener("click", openSidebar);
    document.getElementById("sidebar-close")?.addEventListener("click", closeSidebar);
    document.getElementById("sidebar-overlay")?.addEventListener("click", closeSidebar);
}

// ── HISTORY SIDEBAR ────────────────────────────────────────
function openSidebar() {
    document.getElementById("history-sidebar").classList.add("open");
    document.getElementById("sidebar-overlay").classList.remove("hidden");
    loadHistory();
}
function closeSidebar() {
    document.getElementById("history-sidebar").classList.remove("open");
    document.getElementById("sidebar-overlay").classList.add("hidden");
}

async function loadHistory() {
    if (!isLoggedIn()) return;
    const list = document.getElementById("history-list");
    const empty = document.getElementById("history-empty");
    try {
        const res = await authFetch(`${API_BASE}/history`);
        const data = await res.json();
        if (!data.history || data.history.length === 0) {
            empty.style.display = "block"; return;
        }
        empty.style.display = "none";
        list.innerHTML = "";
        data.history.forEach(h => {
            const d = new Date(h.uploaded_at);
            const el = document.createElement("div");
            el.className = "history-item";
            el.innerHTML = `
        <div class="hi-top">
          <span class="hi-date">${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          <span class="hi-risk risk-${(h.risk_category || '').toLowerCase().replace(/\s+/g, '-')}">${escHtml(h.risk_category || '—')}</span>
        </div>
        <div class="hi-name">${escHtml(h.filename || 'Report')}</div>
        <div class="hi-score">Score: ${h.risk_score != null ? h.risk_score.toFixed(1) : '—'}</div>
        <div class="hi-actions">
          <button class="hi-load" data-id="${h.id}" title="Load"><i class="fa-solid fa-arrow-rotate-left"></i> Load</button>
          <button class="hi-delete" data-id="${h.id}" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
        </div>`;
            list.appendChild(el);
        });
        list.querySelectorAll(".hi-load").forEach(b => b.addEventListener("click", () => loadHistoryReport(b.dataset.id)));
        list.querySelectorAll(".hi-delete").forEach(b => b.addEventListener("click", () => deleteHistoryReport(b.dataset.id)));
    } catch { empty.style.display = "block"; }
}

async function loadHistoryReport(id) {
    try {
        const res = await authFetch(`${API_BASE}/history/${id}`);
        const data = await res.json();
        if (!data.success) { showToast("Could not load report.", "error"); return; }
        closeSidebar();
        uploadedTests = data.results || [];
        renderResultsTable(uploadedTests);
        sectionTable.classList.remove("hidden");
        const abnormal = uploadedTests.filter(r => r.status !== "Normal").length;
        renderRiskGauge(data.risk_score, data.risk_category, abnormal, uploadedTests.length);
        sectionRisk.classList.remove("hidden");
        renderSummary(data.ai_summary);
        sectionSummary.classList.remove("hidden");
        buildDynamicChips(data.results);
        sectionChat.classList.remove("hidden");
        reportContext = buildReportContext({ ...data, abnormal_count: abnormal, total_count: uploadedTests.length });
        sectionRisk.scrollIntoView({ behavior: "smooth" });
        showToast("Report loaded from history.", "success");
    } catch { showToast("Failed to load report.", "error"); }
}

async function deleteHistoryReport(id) {
    if (!confirm("Delete this report from your history?")) return;
    try {
        await authFetch(`${API_BASE}/history/${id}`, { method: "DELETE" });
        showToast("Report deleted.", "info");
        loadHistory();
    } catch { showToast("Failed to delete.", "error"); }
}

// ── i18n TRANSLATIONS ──────────────────────────────────────
const T = {
    en: { heroTitle: "Understand Your<br><span class='gradient-text'>Lab Report</span>", heroSub: "Upload your medical report and get a calm, plain-language explanation — powered by AI and grounded in verified medical education content.", disclaimerStrip: "This tool is for <strong>educational purposes only</strong>. Not a diagnostic or clinical decision system. Always consult a qualified healthcare professional.", uploadReport: "Upload Report", uploadPDF: "📄 Upload PDF", enterManually: "✍️ Enter Manually", currentReport: "Current Report", dropOrBrowse: "Drop PDF here or <span class='dz-link'>browse</span>", browse: "browse", previousReport: "Previous Report", optional: "Optional", forTrend: "For trend comparison", analyseReport: "Analyse Report", extractingPDF: "Extracting values from PDF…", extractedValues: "Extracted Lab Values", testName: "Test Name", yourValue: "Your Value", value: "Value", unit: "Unit", refRange: "Reference Range", status: "Status", generateAnalysis: "Generate AI Analysis", runningAnalysis: "Running analysis — generating insights…", riskOverview: "Risk Overview", score: "Score", stable: "Stable", monitor: "Monitor", moderate: "Moderate", elevated: "Elevated", testsReviewed: "Tests Reviewed", outsideRange: "Outside Range", observedPatterns: "Observed Patterns", educationalOnly: "Educational only", trendAnalysis: "Trend Analysis", vsPrev: "vs. previous report", aiSummary: "AI Summary", patientSafe: "Patient-Safe", readAloud: "🔊 Read Aloud", exportPDF: "📄 Export Report", askReport: "Ask Your Report", chatWelcome: "Ask me anything about your lab report.<br>I explain everything in simple, calm language.", chatDisclaimer: "AI answers are educational only — never a diagnosis or prescription.", urgentTitle: "Urgent: Seek Medical Attention", urgentDesc: "One or more critical values were detected. Please contact a healthcare provider immediately.", footerCopy: "Educational use only · Not a clinical tool", login: "Log In", myReports: "My Reports", educationalTool: "Educational Tool", addRow: "Add Row", analyseManual: "Analyse Entries", chatPlaceholder: "Type your question…" },
    hi: { heroTitle: "अपनी<br><span class='gradient-text'>लैब रिपोर्ट</span> समझें", heroSub: "अपनी मेडिकल रिपोर्ट अपलोड करें और AI द्वारा सरल भाषा में स्पष्टीकरण प्राप्त करें।", disclaimerStrip: "यह उपकरण केवल <strong>शैक्षिक उद्देश्यों</strong> के लिए है। हमेशा स्वास्थ्य पेशेवर से सलाह लें।", uploadReport: "रिपोर्ट अपलोड करें", uploadPDF: "📄 PDF अपलोड", enterManually: "✍️ मैन्युअल दर्ज करें", currentReport: "वर्तमान रिपोर्ट", dropOrBrowse: "PDF यहाँ ड्रॉप करें या <span class='dz-link'>ब्राउज़ करें</span>", previousReport: "पिछली रिपोर्ट", optional: "वैकल्पिक", forTrend: "ट्रेंड तुलना के लिए", analyseReport: "रिपोर्ट विश्लेषण करें", extractingPDF: "PDF से मान निकाले जा रहे हैं…", extractedValues: "निकाले गए लैब मान", testName: "परीक्षण का नाम", yourValue: "आपका मान", value: "मान", unit: "इकाई", refRange: "संदर्भ सीमा", status: "स्थिति", generateAnalysis: "AI विश्लेषण बनाएं", runningAnalysis: "विश्लेषण चल रहा है…", riskOverview: "जोखिम अवलोकन", score: "स्कोर", stable: "स्थिर", monitor: "निगरानी", moderate: "मध्यम", elevated: "उच्च", testsReviewed: "समीक्षित परीक्षण", outsideRange: "सीमा से बाहर", observedPatterns: "देखे गए पैटर्न", educationalOnly: "केवल शैक्षिक", trendAnalysis: "ट्रेंड विश्लेषण", vsPrev: "पिछली रिपोर्ट बनाम", aiSummary: "AI सारांश", patientSafe: "रोगी-सुरक्षित", readAloud: "🔊 ज़ोर से पढ़ें", exportPDF: "📄 रिपोर्ट निर्यात", askReport: "अपनी रिपोर्ट से पूछें", chatWelcome: "अपनी लैब रिपोर्ट के बारे में कुछ भी पूछें।<br>मैं सब कुछ सरल भाषा में समझाता हूँ।", chatDisclaimer: "AI उत्तर केवल शैक्षिक हैं — कभी निदान या नुस्खा नहीं।", urgentTitle: "तत्काल: चिकित्सा ध्यान लें", urgentDesc: "एक या अधिक गंभीर मान पाए गए। कृपया तुरंत स्वास्थ्य प्रदाता से संपर्क करें।", footerCopy: "केवल शैक्षिक उपयोग · क्लिनिकल टूल नहीं", login: "लॉग इन", myReports: "मेरी रिपोर्ट", educationalTool: "शैक्षिक उपकरण", addRow: "पंक्ति जोड़ें", analyseManual: "प्रविष्टियाँ विश्लेषण करें", chatPlaceholder: "अपना प्रश्न टाइप करें…" },
    te: { heroTitle: "మీ<br><span class='gradient-text'>ల్యాబ్ రిపోర్ట్</span> అర్థం చేసుకోండి", heroSub: "మీ వైద్య రిపోర్ట్‌ను అప్‌లోడ్ చేయండి మరియు AI ద్వారా స్పష్టమైన వివరణ పొందండి.", disclaimerStrip: "ఈ సాధనం <strong>విద్యా ప్రయోజనాల</strong> కోసం మాత్రమే. ఎల్లప్పుడూ వైద్య నిపుణులను సంప్రదించండి.", uploadReport: "రిపోర్ట్ అప్‌లోడ్", uploadPDF: "📄 PDF అప్‌లోడ్", enterManually: "✍️ మాన్యువల్‌గా నమోదు", currentReport: "ప్రస్తుత రిపోర్ట్", analyseReport: "రిపోర్ట్ విశ్లేషించు", testName: "పరీక్ష పేరు", value: "విలువ", unit: "యూనిట్", refRange: "సూచన పరిధి", status: "స్థితి", generateAnalysis: "AI విశ్లేషణ", aiSummary: "AI సారాంశం", readAloud: "🔊 చదవండి", exportPDF: "📄 ఎగుమతి", askReport: "రిపోర్ట్ అడగండి", login: "లాగిన్", myReports: "నా రిపోర్ట్‌లు", chatPlaceholder: "మీ ప్రశ్న టైప్ చేయండి…" },
    ta: { heroTitle: "உங்கள்<br><span class='gradient-text'>லேப் அறிக்கை</span> புரிந்துகொள்ளுங்கள்", heroSub: "AI மூலம் எளிய விளக்கம் பெற உங்கள் மருத்துவ அறிக்கையை பதிவேற்றுங்கள்.", disclaimerStrip: "இந்த கருவி <strong>கல்வி நோக்கங்களுக்கு</strong> மட்டுமே. எப்போதும் மருத்துவரை அணுகுங்கள்.", uploadReport: "அறிக்கை பதிவேற்றம்", analyseReport: "பகுப்பாய்வு", testName: "சோதனை பெயர்", aiSummary: "AI சுருக்கம்", readAloud: "🔊 படிக்கவும்", exportPDF: "📄 ஏற்றுமதி", askReport: "கேளுங்கள்", login: "உள்நுழை", myReports: "என் அறிக்கைகள்", chatPlaceholder: "உங்கள் கேள்வியை தட்டச்சு செய்யவும்…" },
    kn: { heroTitle: "ನಿಮ್ಮ<br><span class='gradient-text'>ಲ್ಯಾಬ್ ವರದಿ</span> ಅರ್ಥ ಮಾಡಿಕೊಳ್ಳಿ", heroSub: "ನಿಮ್ಮ ವೈದ್ಯಕೀಯ ವರದಿಯನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ ಮತ್ತು AI ಮೂಲಕ ಸ್ಪಷ್ಟ ವಿವರಣೆ ಪಡೆಯಿರಿ.", disclaimerStrip: "ಈ ಸಾಧನ <strong>ಶೈಕ್ಷಣಿಕ ಉದ್ದೇಶಗಳಿಗೆ</strong> ಮಾತ್ರ. ಯಾವಾಗಲೂ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ.", uploadReport: "ವರದಿ ಅಪ್‌ಲೋಡ್", analyseReport: "ವಿಶ್ಲೇಷಿಸಿ", testName: "ಪರೀಕ್ಷೆಯ ಹೆಸರು", aiSummary: "AI ಸಾರಾಂಶ", readAloud: "🔊 ಓದಿ", exportPDF: "📄 ರಫ್ತು", askReport: "ಪ್ರಶ್ನಿಸಿ", login: "ಲಾಗಿನ್", myReports: "ನನ್ನ ವರದಿಗಳು", chatPlaceholder: "ನಿಮ್ಮ ಪ್ರಶ್ನೆ ಟೈಪ್ ಮಾಡಿ…" },
    bn: { heroTitle: "আপনার<br><span class='gradient-text'>ল্যাব রিপোর্ট</span> বুঝুন", heroSub: "আপনার মেডিকেল রিপোর্ট আপলোড করুন এবং AI-চালিত সহজ ব্যাখ্যা পান।", disclaimerStrip: "এই সরঞ্জামটি শুধুমাত্র <strong>শিক্ষামূলক উদ্দেশ্যে</strong>। সর্বদা স্বাস্থ্য পেশাদারের সাথে পরামর্শ করুন।", uploadReport: "রিপোর্ট আপলোড", analyseReport: "বিশ্লেষণ", testName: "পরীক্ষার নাম", aiSummary: "AI সারাংশ", readAloud: "🔊 পড়ুন", exportPDF: "📄 রপ্তানি", askReport: "জিজ্ঞাসা করুন", login: "লগ ইন", myReports: "আমার রিপোর্ট", chatPlaceholder: "আপনার প্রশ্ন টাইপ করুন…" },
    mr: { heroTitle: "तुमचा<br><span class='gradient-text'>लॅब रिपोर्ट</span> समजून घ्या", heroSub: "तुमचा वैद्यकीय रिपोर्ट अपलोड करा आणि AI द्वारे सोप्या भाषेत स्पष्टीकरण मिळवा.", disclaimerStrip: "हे साधन फक्त <strong>शैक्षणिक हेतूंसाठी</strong> आहे. नेहमी आरोग्य व्यावसायिकाचा सल्ला घ्या.", uploadReport: "रिपोर्ट अपलोड", analyseReport: "विश्लेषण करा", testName: "चाचणीचे नाव", aiSummary: "AI सारांश", readAloud: "🔊 वाचा", exportPDF: "📄 निर्यात", askReport: "विचारा", login: "लॉग इन", myReports: "माझे रिपोर्ट", chatPlaceholder: "तुमचा प्रश्न टाइप करा…" },
    es: { heroTitle: "Comprende tu<br><span class='gradient-text'>Informe de Lab</span>", heroSub: "Sube tu informe médico y obtén una explicación clara impulsada por IA.", disclaimerStrip: "Esta herramienta es solo para <strong>fines educativos</strong>. Consulta siempre a un profesional de la salud.", uploadReport: "Subir Informe", analyseReport: "Analizar", testName: "Nombre del Test", aiSummary: "Resumen IA", readAloud: "🔊 Leer en voz alta", exportPDF: "📄 Exportar", askReport: "Pregunta a tu Informe", login: "Iniciar sesión", myReports: "Mis Informes", chatPlaceholder: "Escribe tu pregunta…" },
    fr: { heroTitle: "Comprenez votre<br><span class='gradient-text'>Bilan Sanguin</span>", heroSub: "Téléchargez votre rapport médical et obtenez une explication claire par IA.", disclaimerStrip: "Cet outil est <strong>à des fins éducatives uniquement</strong>. Consultez toujours un professionnel de santé.", uploadReport: "Télécharger", analyseReport: "Analyser", testName: "Nom du test", aiSummary: "Résumé IA", readAloud: "🔊 Lire à voix haute", exportPDF: "📄 Exporter", askReport: "Posez vos questions", login: "Connexion", myReports: "Mes Rapports", chatPlaceholder: "Tapez votre question…" },
    ar: { heroTitle: "افهم<br><span class='gradient-text'>تقرير المختبر</span>", heroSub: "ارفع تقريرك الطبي واحصل على شرح واضح بالذكاء الاصطناعي.", disclaimerStrip: "هذه الأداة <strong>لأغراض تعليمية فقط</strong>. استشر طبيبك دائماً.", uploadReport: "رفع التقرير", analyseReport: "تحليل", testName: "اسم الفحص", aiSummary: "ملخص AI", readAloud: "🔊 اقرأ بصوت عالٍ", exportPDF: "📄 تصدير", askReport: "اسأل تقريرك", login: "تسجيل الدخول", myReports: "تقاريري", chatPlaceholder: "اكتب سؤالك…" },
    zh: { heroTitle: "了解您的<br><span class='gradient-text'>检验报告</span>", heroSub: "上传您的医疗报告，获取AI驱动的清晰解释。", disclaimerStrip: "本工具<strong>仅供教育目的</strong>。请始终咨询医疗专业人员。", uploadReport: "上传报告", analyseReport: "分析", testName: "检测名称", aiSummary: "AI总结", readAloud: "🔊 朗读", exportPDF: "📄 导出报告", askReport: "询问报告", login: "登录", myReports: "我的报告", chatPlaceholder: "输入您的问题…" },
    pt: { heroTitle: "Entenda seu<br><span class='gradient-text'>Exame de Lab</span>", heroSub: "Envie seu relatório médico e obtenha uma explicação clara com IA.", disclaimerStrip: "Esta ferramenta é apenas para <strong>fins educacionais</strong>. Consulte sempre um profissional de saúde.", uploadReport: "Enviar Relatório", analyseReport: "Analisar", testName: "Nome do Teste", aiSummary: "Resumo IA", readAloud: "🔊 Ler em voz alta", exportPDF: "📄 Exportar", askReport: "Pergunte ao Relatório", login: "Entrar", myReports: "Meus Relatórios", chatPlaceholder: "Digite sua pergunta…" }
};

function setLanguage(code) {
    currentLang = code;
    localStorage.setItem("medi_lang", code);
    document.getElementById("lang-select").value = code;
    applyTranslations();

    // Feature 2: cancel any ongoing speech when language changes
    if (window.speechSynthesis && isSpeaking) {
        window.speechSynthesis.cancel();
        isSpeaking = false;
        document.querySelectorAll(".btn-tts-bubble, #btn-tts-summary").forEach(b => b.classList.remove("speaking"));
    }

    // Feature 3: update voice recognition language immediately
    if (recognition) {
        recognition.lang = LANG_STT_MAP[code] || "en-US";
    }
}

function applyTranslations() {
    const dict = { ...T.en, ...(T[currentLang] || {}) };
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (dict[key]) el.innerHTML = dict[key];
    });
    const ci = document.getElementById("chat-input");
    if (ci && dict.chatPlaceholder) ci.placeholder = dict.chatPlaceholder;
}

// ── DOM REFS ───────────────────────────────────────────────
const uploadZone = document.getElementById("upload-zone");
const fileInput = document.getElementById("file-input");
const uploadFilename = document.getElementById("upload-filename");
const filenameText = document.getElementById("filename-text");
const btnUpload = document.getElementById("btn-upload");
const uploadLoader = document.getElementById("upload-loader");
const uploadZoneHistorical = document.getElementById("upload-zone-historical");
const fileInputHistorical = document.getElementById("file-input-historical");
const uploadFilenameHistorical = document.getElementById("upload-filename-historical");
const filenameTextHistorical = document.getElementById("filename-text-historical");
const sectionTable = document.getElementById("section-table");
const resultsTbody = document.getElementById("results-tbody");
const testCountBadge = document.getElementById("test-count-badge");
const btnAnalyze = document.getElementById("btn-analyze");
const analyzeLoader = document.getElementById("analyze-loader");
const sectionRisk = document.getElementById("section-risk");
const riskCatBadge = document.getElementById("risk-category-badge");
const gaugeArc = document.getElementById("gauge-arc");
const gaugeDot = document.getElementById("gauge-dot");
const riskScoreText = document.getElementById("risk-score-text");
const statTotal = document.getElementById("stat-total");
const statAbnormal = document.getElementById("stat-abnormal");
const patternsSection = document.getElementById("patterns-section");
const patternsList = document.getElementById("patterns-list");
const trendsSection = document.getElementById("trends-section");
const trendsList = document.getElementById("trends-list");
const emergencyAlert = document.getElementById("emergency-alert");
const sectionSummary = document.getElementById("section-summary");
const aiSummaryText = document.getElementById("ai-summary-text");
const sectionChat = document.getElementById("section-chat");
const chatChips = document.getElementById("chat-chips");
const chatWindow = document.getElementById("chat-window");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");

// ── UPLOAD / MANUAL TABS ───────────────────────────────────
document.getElementById("tab-upload")?.addEventListener("click", () => {
    document.getElementById("tab-upload").classList.add("active");
    document.getElementById("tab-manual").classList.remove("active");
    document.getElementById("panel-upload-pdf").classList.remove("hidden");
    document.getElementById("panel-manual").classList.add("hidden");
});
document.getElementById("tab-manual")?.addEventListener("click", () => {
    document.getElementById("tab-manual").classList.add("active");
    document.getElementById("tab-upload").classList.remove("active");
    document.getElementById("panel-manual").classList.remove("hidden");
    document.getElementById("panel-upload-pdf").classList.add("hidden");
    if (document.getElementById("manual-tbody").children.length === 0) addManualRow();
});

// ── FILE UPLOAD ────────────────────────────────────────────
uploadZone.addEventListener("dragover", e => { e.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone.addEventListener("drop", e => { e.preventDefault(); uploadZone.classList.remove("drag-over"); if (e.dataTransfer.files[0]) handleFileSelected(e.dataTransfer.files[0]); });
uploadZone.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") fileInput.click(); });
fileInput.addEventListener("change", () => { if (fileInput.files[0]) handleFileSelected(fileInput.files[0]); });
uploadZoneHistorical.addEventListener("dragover", e => { e.preventDefault(); uploadZoneHistorical.classList.add("drag-over"); });
uploadZoneHistorical.addEventListener("dragleave", () => uploadZoneHistorical.classList.remove("drag-over"));
uploadZoneHistorical.addEventListener("drop", e => { e.preventDefault(); uploadZoneHistorical.classList.remove("drag-over"); if (e.dataTransfer.files[0]) handleFileSelectedHistorical(e.dataTransfer.files[0]); });
uploadZoneHistorical.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") fileInputHistorical.click(); });
fileInputHistorical.addEventListener("change", () => { if (fileInputHistorical.files[0]) handleFileSelectedHistorical(fileInputHistorical.files[0]); });

function handleFileSelected(file) {
    if (!file.name.toLowerCase().endsWith(".pdf")) { showToast("Please upload a PDF file.", "warning"); return; }
    filenameText.textContent = file.name;
    uploadFilename.classList.remove("hidden");
    btnUpload.disabled = false;
}
function handleFileSelectedHistorical(file) {
    if (!file.name.toLowerCase().endsWith(".pdf")) { showToast("Please upload a PDF file.", "warning"); return; }
    filenameTextHistorical.textContent = file.name;
    uploadFilenameHistorical.classList.remove("hidden");
}

let _uploadedFilename = "uploaded_report.pdf";

btnUpload.addEventListener("click", async () => {
    const file = fileInput.files[0]; if (!file) return;
    _uploadedFilename = file.name;
    setLoading(btnUpload, uploadLoader, true);
    sectionTable.classList.add("hidden"); sectionRisk.classList.add("hidden");
    sectionSummary.classList.add("hidden"); sectionChat.classList.add("hidden");
    analysisResults = null; reportContext = ""; resetChatWindow();
    try {
        const fd = new FormData(); fd.append("file", file);
        const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
        const data = await handleResponse(res);
        if (!data.tests || data.tests.length === 0) { showToast("No lab values extracted.", "warning"); return; }
        uploadedTests = data.tests;
        renderResultsTable(uploadedTests);
        const fH = fileInputHistorical.files[0];
        if (fH) {
            const fd2 = new FormData(); fd2.append("file", fH);
            const rH = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd2 });
            const dH = await handleResponse(rH);
            if (dH.tests && dH.tests.length > 0) { historicalTests = dH.tests; showToast(`${dH.count} historical test(s) loaded.`, "info"); }
        }
        sectionTable.classList.remove("hidden");
        sectionTable.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast(`${data.count} lab test(s) extracted.`, "success");
    } catch (err) { showToast(`Upload failed: ${err.message}`, "error"); }
    finally { setLoading(btnUpload, uploadLoader, false); }
});

// ── RESULTS TABLE ──────────────────────────────────────────
function renderResultsTable(tests) {
    resultsTbody.innerHTML = "";
    testCountBadge.textContent = `${tests.length} tests`;
    tests.forEach(t => {
        const tr = document.createElement("tr");
        tr.dataset.name = t.test_name;
        tr.innerHTML = `<td><strong>${escHtml(t.test_name)}</strong></td><td>${escHtml(String(t.measured_value))}</td><td style="color:var(--text-secondary)">${escHtml(t.unit || "—")}</td><td style="color:var(--text-secondary)">${escHtml(t.reference_range || "—")}</td><td class="status-cell"><span class="status-pill ${escHtml(t.status || 'Unknown')}">${escHtml(t.status || 'Unknown')}</span></td>`;
        resultsTbody.appendChild(tr);
    });
}

function updateTableWithStatus(results) {
    results.forEach(r => {
        const row = Array.from(resultsTbody.querySelectorAll("tr")).find(c => c.dataset.name === r.test_name);
        if (!row) return;
        if (r.is_critical) row.classList.add("critical-row");
        const sc = row.querySelector(".status-cell");
        let html = `<span class="status-pill ${escHtml(r.status)}">${escHtml(r.status)}`;
        if (r.is_critical) html += ` <i class="fa-solid fa-triangle-exclamation" style="margin-left:3px;font-size:0.7em"></i>`;
        html += `</span>`;
        if (r.is_critical) html += `<span class="status-pill critical-badge" style="margin-left:6px">🚨 CRITICAL</span>`;
        if (r.status !== "Normal") { const desc = r.status_description || r.description || ""; if (desc) html += `<div class="result-desc">${escHtml(desc)}</div>`; }
        sc.innerHTML = html;
    });
}

// ── ANALYZE ────────────────────────────────────────────────
btnAnalyze.addEventListener("click", () => doAnalyze(uploadedTests, historicalTests));

async function doAnalyze(tests, hist) {
    if (!tests.length) return;
    setLoading(btnAnalyze, analyzeLoader, true);

    // Feature 5: capture the language being used for this analysis
    lastAnalysisLanguage = getCurrentLanguage();

    try {
        const payload = { tests, language: getCurrentLanguage(), filename: _uploadedFilename };
        if (hist && hist.length > 0) payload.historical_tests = hist;
        const res = await authFetch(`${API_BASE}/analyze`, { method: "POST", body: JSON.stringify(payload) });
        const data = await handleResponse(res);
        analysisResults = data;
        updateTableWithStatus(data.results);
        reportContext = buildReportContext(data);
        renderRiskGauge(data.risk_score, data.risk_category, data.abnormal_count, data.total_count);
        sectionRisk.classList.remove("hidden");
        if (data.patterns && data.patterns.length > 0) { renderPatterns(data.patterns); patternsSection.classList.remove("hidden"); } else patternsSection.classList.add("hidden");
        if (data.trends && data.trends.length > 0) { renderTrends(data.trends); trendsSection.classList.remove("hidden"); } else trendsSection.classList.add("hidden");
        const hasCritical = (data.results || []).some(r => r.is_critical);
        if (hasCritical) emergencyAlert.classList.remove("hidden"); else emergencyAlert.classList.add("hidden");
        renderSummary(data.ai_summary);
        sectionSummary.classList.remove("hidden");
        buildDynamicChips(data.results);
        sectionChat.classList.remove("hidden");
        sectionRisk.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast("Analysis complete!", "success");
    } catch (err) { showToast(`Analysis failed: ${err.message}`, "error"); }
    finally { setLoading(btnAnalyze, analyzeLoader, false); }
}

// ── RISK GAUGE ─────────────────────────────────────────────
const RISK_CONFIG = {
    "Stable": { pct: 0.08, color: "#00E5A0" }, "Monitor": { pct: 0.35, color: "#FFAB40" },
    "Moderate Concern": { pct: 0.65, color: "#FF7043" }, "Elevated Risk": { pct: 0.92, color: "#FF4D6D" }
};
const ARC_LENGTH = Math.PI * 80;

function renderRiskGauge(score, category, abnormal, total) {
    const cfg = RISK_CONFIG[category] || RISK_CONFIG["Stable"];
    const offset = ARC_LENGTH * (1 - cfg.pct);
    if (gaugeArc) { gaugeArc.style.stroke = cfg.color; gaugeArc.style.strokeDashoffset = offset; }
    if (gaugeDot) gaugeDot.style.fill = cfg.color;
    riskCatBadge.textContent = category; riskCatBadge.style.color = cfg.color;
    riskScoreText.textContent = score.toFixed(1);
    statTotal.textContent = total; statAbnormal.textContent = abnormal;
}

function renderPatterns(patterns) { patternsList.innerHTML = ""; patterns.forEach(p => { const d = document.createElement("div"); d.className = "insight-item"; d.textContent = p.message; patternsList.appendChild(d); }); }
function renderTrends(trends) { trendsList.innerHTML = ""; trends.forEach(t => { const d = document.createElement("div"); const isUp = t.percent_change > 5, isDown = t.percent_change < -5; d.className = `insight-item ${isUp ? "trend-up" : isDown ? "trend-down" : "trend-stable"}`; const arrow = isUp ? "↗" : isDown ? "↘" : "→"; const sign = t.percent_change > 0 ? "+" : ""; d.innerHTML = `<strong>${escHtml(t.test_name)}</strong> &nbsp;${arrow} ${escHtml(t.trend_type)} (${sign}${t.percent_change}%)<div class="trend-meta">Previous: ${t.historical_value} ${t.unit} &nbsp;→&nbsp; Current: ${t.current_value} ${t.unit}</div>`; trendsList.appendChild(d); }); }
function renderSummary(text) { aiSummaryText.innerHTML = markdownToHtml(text || "No summary generated."); }
function buildDynamicChips(results) {
    if (!results || !results.length) return;
    const abn = results.filter(r => r.status !== "Normal").slice(0, 4);
    if (!abn.length) return;
    chatChips.innerHTML = "";
    abn.forEach(r => { const b = document.createElement("button"); b.className = "chip"; b.dataset.q = `What does ${r.status.toLowerCase()} ${r.test_name} mean?`; b.textContent = `${r.status} ${r.test_name}?`; chatChips.appendChild(b); });
    chatChips.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => { chatInput.value = c.dataset.q; chatInput.focus(); }));
}

// ── CHAT Q&A ───────────────────────────────────────────────
document.querySelectorAll(".chip").forEach(chip => chip.addEventListener("click", () => { chatInput.value = chip.dataset.q; chatInput.focus(); }));
btnSend.addEventListener("click", sendQuestion);
chatInput.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); } });

async function sendQuestion() {
    const q = chatInput.value.trim(); if (!q) return;
    chatInput.value = ""; btnSend.disabled = true;
    const welcome = chatWindow.querySelector(".chat-welcome"); if (welcome) welcome.remove();
    appendBubble(q, "user");
    const thinking = appendThinking();

    // Feature 1: use getCurrentLanguage() for /ask
    const questionLang = getCurrentLanguage();
    try {
        const res = await authFetch(`${API_BASE}/ask`, { method: "POST", body: JSON.stringify({ question: q, report_context: reportContext, language: questionLang }) });
        const data = await handleResponse(res);
        thinking.remove();
        // Feature 5: pass the language used for this Q&A to the bubble
        appendBubble(data.answer || "Unexpected response.", "bot", questionLang);
    } catch (err) { thinking.remove(); appendBubble(`Sorry: ${err.message}`, "bot", questionLang); }
    finally { btnSend.disabled = false; chatInput.focus(); }
}

/**
 * Feature 5: appendBubble now accepts optional lang param.
 * Bot bubbles get data-lang set so their TTS button can use the correct language.
 */
function appendBubble(text, type, lang) {
    const div = document.createElement("div");
    div.className = `chat-bubble chat-bubble-${type}`;
    if (type === "bot") {
        const bubbleLang = lang || getCurrentLanguage();
        div.dataset.lang = bubbleLang; // Feature 5: store lang for TTS retrieval
        try { div.innerHTML = markdownToHtml(text); } catch { div.textContent = text; }
        // TTS button on each bot bubble — reads data-lang from the bubble
        const ttsBtn = document.createElement("button");
        ttsBtn.className = "btn-tts-bubble"; ttsBtn.title = "Read aloud"; ttsBtn.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
        ttsBtn.addEventListener("click", () => speakText(text, div.dataset.lang));
        div.appendChild(ttsBtn);
    } else { div.textContent = text; }
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return div;
}
function appendThinking() { const d = document.createElement("div"); d.className = "chat-bubble chat-bubble-thinking"; d.innerHTML = `<div class="thinking-dots"><span></span><span></span><span></span></div>Thinking…`; chatWindow.appendChild(d); chatWindow.scrollTop = chatWindow.scrollHeight; return d; }
function resetChatWindow() { chatWindow.innerHTML = `<div class="chat-welcome" id="chat-welcome"><div class="chat-welcome-icon"><i class="fa-regular fa-message-medical"></i></div><p data-i18n="chatWelcome">Ask me anything about your lab report.<br>I explain everything in simple, calm language.</p></div>`; applyTranslations(); }

// ── MANUAL ENTRY ───────────────────────────────────────────
document.getElementById("btn-add-row")?.addEventListener("click", addManualRow);
document.getElementById("btn-manual-analyze")?.addEventListener("click", submitManualEntry);

function addManualRow() {
    const tbody = document.getElementById("manual-tbody");
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><input type="text" class="manual-input" list="test-suggestions" placeholder="e.g. Hemoglobin"></td><td><input type="number" class="manual-input" step="any" placeholder="e.g. 13.5"></td><td><input type="text" class="manual-input" placeholder="e.g. g/dL"></td><td><input type="text" class="manual-input" placeholder="e.g. 12.0-17.5"></td><td><button class="btn-remove-row" title="Remove"><i class="fa-solid fa-xmark"></i></button></td>`;
    tbody.appendChild(tr);
    tr.querySelector(".btn-remove-row").addEventListener("click", () => { tr.remove(); checkManualValid(); });
    tr.querySelectorAll(".manual-input").forEach(i => i.addEventListener("input", checkManualValid));
    checkManualValid();
}

function checkManualValid() {
    const rows = document.querySelectorAll("#manual-tbody tr");
    let valid = false;
    rows.forEach(r => {
        const inputs = r.querySelectorAll(".manual-input");
        if (inputs[0].value.trim() && inputs[1].value.trim()) valid = true;
    });
    const btn = document.getElementById("btn-manual-analyze");
    if (btn) btn.disabled = !valid;
}

async function submitManualEntry() {
    const rows = document.querySelectorAll("#manual-tbody tr");
    const tests = [];
    rows.forEach(r => {
        const inputs = r.querySelectorAll(".manual-input");
        const name = inputs[0].value.trim(), val = parseFloat(inputs[1].value);
        if (name && !isNaN(val)) tests.push({ test_name: name, measured_value: val, unit: inputs[2].value.trim(), reference_range: inputs[3].value.trim() });
    });
    if (!tests.length) { showToast("Add at least one valid test.", "warning"); return; }
    uploadedTests = tests;
    _uploadedFilename = "manual_entry";
    renderResultsTable(tests);
    sectionTable.classList.remove("hidden");
    sectionTable.scrollIntoView({ behavior: "smooth" });
    doAnalyze(tests, []);
}

// ── VOICE INPUT (STT) — Feature 3 ─────────────────────────
// Feature 3: expanded to 12 languages including bn, mr, kn
const LANG_STT_MAP = {
    en: "en-US", hi: "hi-IN", te: "te-IN", ta: "ta-IN", kn: "kn-IN",
    es: "es-ES", fr: "fr-FR", ar: "ar-SA", zh: "zh-CN",
    pt: "pt-BR", bn: "bn-IN", mr: "mr-IN"
};
let recognition = null;

function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        // Feature 3: hide mic button entirely if not supported
        const micBtn = document.getElementById("btn-mic");
        if (micBtn) micBtn.style.display = "none";
        return;
    }
    recognition = new SpeechRecognition();
    recognition.continuous = false; recognition.interimResults = true;
    recognition.lang = LANG_STT_MAP[currentLang] || "en-US";
    recognition.onresult = e => { let t = ""; for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; chatInput.value = t; };
    recognition.onend = () => stopRecording();
    recognition.onerror = () => stopRecording();
}

function startRecording() {
    if (!recognition) { showToast("Voice input not supported in this browser.", "warning"); return; }
    recognition.lang = LANG_STT_MAP[getCurrentLanguage()] || "en-US";
    recognition.start();
    document.getElementById("btn-mic").classList.add("recording");
    document.getElementById("mic-indicator")?.classList.remove("hidden");
}
function stopRecording() {
    try { recognition?.stop(); } catch { }
    document.getElementById("btn-mic")?.classList.remove("recording");
    document.getElementById("mic-indicator")?.classList.add("hidden");
    chatInput.focus();
}
document.getElementById("btn-mic")?.addEventListener("click", () => {
    if (document.getElementById("btn-mic").classList.contains("recording")) stopRecording();
    else startRecording();
});

// ── VOICE OUTPUT (TTS) — Features 2 & 5 ───────────────────
// Feature 2: expanded to 12 languages including bn, mr, kn
const LANG_TTS_MAP = {
    en: "en-US", hi: "hi-IN", te: "te-IN", ta: "ta-IN", kn: "kn-IN",
    es: "es-ES", fr: "fr-FR", ar: "ar-SA", zh: "zh-CN",
    pt: "pt-BR", bn: "bn-IN", mr: "mr-IN"
};

/**
 * Feature 2: strip markdown, HTML tags, emoji noise, and formatting
 * so the spoken text sounds like natural speech.
 */
function stripMarkdown(t) {
    return t
        .replace(/<[^>]*>/g, " ")           // strip HTML tags
        .replace(/⚠️/g, "")                 // strip warning emoji
        .replace(/#{1,6}\s?/g, "")          // strip ## headers
        .replace(/\*\*(.*?)\*\*/g, "$1")    // strip bold **
        .replace(/\*(.*?)\*/g, "$1")        // strip italic *
        .replace(/^---+$/gm, "")            // strip --- dividers
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // strip [text](url)
        .replace(/\n{2,}/g, ". ")           // double newlines → sentence break
        .replace(/\n/g, " ")                // single newlines → space
        .replace(/\s{2,}/g, " ")            // collapse whitespace
        .trim();
}

/**
 * Feature 2 & 5: speakText now accepts an optional `lang` param.
 * Summary TTS passes lastAnalysisLanguage; bubble TTS passes data-lang.
 * Falls back to currentLang if no lang provided.
 */
function speakText(text, lang) {
    if (!window.speechSynthesis) return; // Feature 2: silently skip if unsupported

    if (isSpeaking) {
        window.speechSynthesis.cancel();
        isSpeaking = false;
        document.querySelectorAll(".btn-tts-bubble, #btn-tts-summary").forEach(b => b.classList.remove("speaking"));
        return;
    }

    const effectiveLang = lang || getCurrentLanguage();
    const u = new SpeechSynthesisUtterance(stripMarkdown(text));
    u.lang = LANG_TTS_MAP[effectiveLang] || "en-US";

    // Try to find the best matching voice for the target language
    const voices = window.speechSynthesis.getVoices();
    const langPrefix = u.lang.split("-")[0];
    const exactMatch = voices.find(v => v.lang === u.lang);
    const prefixMatch = voices.find(v => v.lang.startsWith(langPrefix));
    if (exactMatch) u.voice = exactMatch;
    else if (prefixMatch) u.voice = prefixMatch;
    // else: fallback to browser default voice

    u.onend = () => {
        isSpeaking = false;
        document.querySelectorAll(".btn-tts-bubble, #btn-tts-summary").forEach(b => b.classList.remove("speaking"));
    };
    u.onerror = () => {
        isSpeaking = false;
        document.querySelectorAll(".btn-tts-bubble, #btn-tts-summary").forEach(b => b.classList.remove("speaking"));
    };

    isSpeaking = true;
    document.querySelectorAll(".btn-tts-bubble, #btn-tts-summary").forEach(b => b.classList.add("speaking"));
    window.speechSynthesis.speak(u);
}

// Feature 5: Summary TTS uses lastAnalysisLanguage, not currentLang
document.getElementById("btn-tts-summary")?.addEventListener("click", () => {
    const raw = aiSummaryText?.innerText || "";
    if (raw) speakText(raw, lastAnalysisLanguage);
});

// ── PDF EXPORT ─────────────────────────────────────────────
document.getElementById("btn-export")?.addEventListener("click", () => {
    const pd = document.getElementById("print-date");
    if (pd) pd.textContent = new Date().toLocaleString();
    window.print();
});

// ── HELPERS ────────────────────────────────────────────────
function setLoading(btn, loader, on) { btn.disabled = on; loader.classList.toggle("hidden", !on); }
async function handleResponse(res) {
    if (!res.ok) { let m = `Server error: ${res.status}`; try { const e = await res.json(); m = e.detail || m; } catch { } throw new Error(m); }
    try { return await res.json(); } catch { throw new Error("Invalid response format."); }
}
function escHtml(s) { if (s == null) return "—"; return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function markdownToHtml(md) {
    if (!md) return "";
    let h = md.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    h = h.replace(/^##\s+(.+)$/gm, '<strong style="font-size:1.02em;display:block;margin:12px 0 5px">$1</strong>');
    h = h.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:16px 0">');
    h = h.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/([^\*]|^)\*([^\*]+)\*([^\*]|$)/g, '$1<em>$2</em>$3');
    h = h.replace(/^[\-•]\s+(.+)$/gm, '<div style="padding-left:14px;margin:4px 0;color:var(--text-secondary)">• $1</div>');
    h = h.replace(/\n\n/g, '<br><br>'); h = h.replace(/\n/g, '<br>');
    h = h.replace(/⚠️([\s\S]*?)\*(.*?)\*/gi, (_, _p1, p2) => `<div class="safety-card"><strong>⚠️ Note:</strong> ${p2}</div>`);
    return h;
}
function buildReportContext(data) {
    const l = [`Risk Category: ${data.risk_category} (Score: ${data.risk_score})`, `Tests Outside Range: ${data.abnormal_count} of ${data.total_count}`, "", "Test Results:"];
    (data.results || []).forEach(r => l.push(`  ${r.test_name}: ${r.measured_value} ${r.unit} [Ref: ${r.reference_range}] → ${r.status}`));
    return l.join("\n");
}
function showToast(message, type = "info") {
    const c = document.getElementById("toast-container"), t = document.createElement("div");
    t.className = `toast toast-${type}`; t.textContent = message; c.appendChild(t);
    setTimeout(() => { t.style.transition = "opacity 0.3s,transform 0.3s"; t.style.opacity = "0"; t.style.transform = "translateY(8px)"; setTimeout(() => t.remove(), 320); }, 4000);
}

// ── INIT ───────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    initAuthUI();
    setLanguage(currentLang);
    initSpeechRecognition();
    // Pre-load voices so they're available immediately when TTS is called
    if (window.speechSynthesis) {
        window.speechSynthesis.getVoices();
        // Chrome loads voices asynchronously — trigger again after a moment
        window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
    }
    document.getElementById("lang-select")?.addEventListener("change", e => setLanguage(e.target.value));
    addManualRow(); addManualRow(); addManualRow();
});
