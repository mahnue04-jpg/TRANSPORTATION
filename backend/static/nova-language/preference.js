/* Shared Nova screen-language preference. Account value wins when signed in.
   Japanese, Korean, Greek, Russian, and German are a rollout preference only. */
(function () {
  "use strict";
  var KEY = "amicor_nova_screen_language";
  var verified = ["en", "so", "ar", "fr", "es"];
  var rollout = ["ja", "ko", "el", "ru", "de"];
  var supported = verified.concat(rollout);
  var notices = {
    ja: "この言語は展開計画に含まれています。この言語での業務提供は未検証です。",
    ko: "이 언어는 도입 계획에 있습니다. 이 언어로 하는 업무 제공은 검증되지 않았습니다.",
    el: "Αυτή η γλώσσα είναι στο σχέδιο διάθεσης. Η επιχειρηματική παράδοση σε αυτή τη γλώσσα δεν έχει επαληθευτεί.",
    ru: "Этот язык входит в план внедрения. Деловая работа на этом языке не проверена.",
    de: "Diese Sprache steht im Einführungsplan. Geschäftliche Lieferung in dieser Sprache ist nicht geprüft."
  };
  var approval = {
    en: {approval_is_not_execution: "Approval is not execution.", approve: "Approve", reject: "Reject", original_preserved: "Original language is preserved.", unsupported_not_applied: "Unsupported translation was not applied.", legal_not_translated: "Legal terms were not translated.", client_approval_not_translated: "Client approval text was not translated."},
    so: {approval_is_not_execution: "Ansixintu ma aha fulin.", approve: "Ansixi", reject: "Diid", original_preserved: "Luqadda asalka waa la ilaaliyay.", unsupported_not_applied: "Turjumaan aan la taageerin lama isticmaalin.", legal_not_translated: "Erayada sharciga lama turjumin.", client_approval_not_translated: "Qoraalka ansixinta macmiilka lama turjumin."},
    ar: {approval_is_not_execution: "الموافقة ليست تنفيذًا.", approve: "موافقة", reject: "رفض", original_preserved: "تم الحفاظ على اللغة الأصلية.", unsupported_not_applied: "لم يتم تطبيق ترجمة غير مدعومة.", legal_not_translated: "لم تُترجم المصطلحات القانونية.", client_approval_not_translated: "لم يُترجم نص موافقة العميل."},
    fr: {approval_is_not_execution: "L’approbation n’est pas une exécution.", approve: "Approuver", reject: "Refuser", original_preserved: "La langue d’origine est conservée.", unsupported_not_applied: "Une traduction non prise en charge n’a pas été appliquée.", legal_not_translated: "Les termes juridiques n’ont pas été traduits.", client_approval_not_translated: "Le texte d’approbation du client n’a pas été traduit."},
    es: {approval_is_not_execution: "La aprobación no es una ejecución.", approve: "Aprobar", reject: "Rechazar", original_preserved: "El idioma original se conserva.", unsupported_not_applied: "No se aplicó una traducción no admitida.", legal_not_translated: "Los términos legales no se tradujeron.", client_approval_not_translated: "El texto de aprobación del cliente no se tradujo."},
    ja: {approval_is_not_execution: "承認は実行ではありません。", approve: "承認", reject: "却下", original_preserved: "原文の言語は保持されます。", unsupported_not_applied: "未対応の翻訳は適用されていません。", legal_not_translated: "法的用語は翻訳されていません。", client_approval_not_translated: "顧客の承認文は翻訳されていません。"},
    ko: {approval_is_not_execution: "승인은 실행이 아닙니다.", approve: "승인", reject: "거절", original_preserved: "원문 언어가 유지됩니다.", unsupported_not_applied: "지원되지 않는 번역은 적용되지 않았습니다.", legal_not_translated: "법률 용어는 번역되지 않았습니다.", client_approval_not_translated: "고객 승인 문구는 번역되지 않았습니다."},
    el: {approval_is_not_execution: "Η έγκριση δεν είναι εκτέλεση.", approve: "Έγκριση", reject: "Απόρριψη", original_preserved: "Η αρχική γλώσσα διατηρείται.", unsupported_not_applied: "Δεν εφαρμόστηκε μη υποστηριζόμενη μετάφραση.", legal_not_translated: "Οι νομικοί όροι δεν μεταφράστηκαν.", client_approval_not_translated: "Το κείμενο έγκρισης του πελάτη δεν μεταφράστηκε."},
    ru: {approval_is_not_execution: "Согласование не является исполнением.", approve: "Согласовать", reject: "Отклонить", original_preserved: "Исходный язык сохранён.", unsupported_not_applied: "Неподдерживаемый перевод не применён.", legal_not_translated: "Юридические термины не переведены.", client_approval_not_translated: "Текст согласования клиента не переведён."},
    de: {approval_is_not_execution: "Genehmigung ist keine Ausführung.", approve: "Genehmigen", reject: "Ablehnen", original_preserved: "Die Ausgangssprache bleibt erhalten.", unsupported_not_applied: "Eine nicht unterstützte Übersetzung wurde nicht angewendet.", legal_not_translated: "Rechtliche Begriffe wurden nicht übersetzt.", client_approval_not_translated: "Der Text der Kundenfreigabe wurde nicht übersetzt."}
  };

  function read() {
    try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; }
  }

  function write(code) {
    if (supported.indexOf(code) < 0) code = "en";
    try { localStorage.setItem(KEY, code); } catch (_) {}
    return code;
  }

  function session() {
    return window.AmiCorSession;
  }

  function token() {
    return session() && session().getAccessToken && session().getAccessToken();
  }

  function overclaims(body) {
    if (!body) return false;
    if (body.voice_interpretation || body.bidirectional_text) return true;
    if (rollout.indexOf(body.screen_language) >= 0 && (body.operational === true || body.business_delivery_operational === true || body.translation_verified === true)) return true;
    return false;
  }

  function sourceLanguage(text) {
    var sample = String(text || "");
    if (/[\u3040-\u30ff]/.test(sample)) return "ja";
    if (/[\uac00-\ud7af]/.test(sample)) return "ko";
    if (/[\u0370-\u03ff]/.test(sample)) return "el";
    if (/[\u0400-\u04ff]/.test(sample)) return "ru";
    if (/[äöüÄÖÜß]/.test(sample)) return "de";
    return sample.trim() ? "en" : "unspecified";
  }

  function guardTask(text, requestedLanguage) {
    var requested = supported.indexOf(requestedLanguage) >= 0 ? requestedLanguage : String(requestedLanguage || "").toLowerCase();
    var known = supported.indexOf(requested) >= 0;
    var planned = rollout.indexOf(requested) >= 0;
    var sample = String(text || "");
    var legal = /governing law|liabilit|indemnif|terms and conditions|non-disclosure|\bnda\b|jurisdiction|warrant(?:y|ies)|force majeure/i.test(sample);
    var clientApproval = /client approval|approved by the client|authorization to submit|owner approval|\bi approve\b|please approve/i.test(sample);
    var copy = approval[known ? requested : "en"];
    return {
      input_text: sample,
      output_text: sample,
      source_language: sourceLanguage(sample),
      requested_language: requested,
      output_language: sourceLanguage(sample),
      translation_applied: false,
      legal_terms_present: legal,
      legal_terms_translated: false,
      client_approval_present: clientApproval,
      client_approval_translated: false,
      unsupported_translation_refused: planned || !known,
      business_delivery_operational: known && !planned,
      operational: known && !planned,
      approval_copy: copy,
      notice: notices[requested] || ""
    };
  }

  function applyNotice(el, code) {
    if (!el) return;
    var text = notices[code] || "";
    el.textContent = text;
    el.hidden = !text;
  }

  function approvalCopy(code) {
    return approval[supported.indexOf(code) >= 0 ? code : "en"];
  }

  async function pull() {
    if (!token()) return read();
    var response = await fetch("/api/nova/language", {
      headers: session().getAuthHeaders(),
      cache: "no-store"
    });
    if (!response.ok) return read();
    var body = await response.json();
    if (!body || supported.indexOf(body.screen_language) < 0) return read();
    if (overclaims(body)) return read();
    return write(body.screen_language);
  }

  async function push(code) {
    code = write(code);
    var planned = rollout.indexOf(code) >= 0;
    if (!token()) {
      return {
        screen_language: code,
        persisted: false,
        operational: !planned,
        business_delivery_operational: !planned,
        translation_verified: false,
        voice_interpretation: false,
        bidirectional_text: false
      };
    }
    var headers = {"Content-Type": "application/json"};
    var auth = session().getAuthHeaders();
    Object.keys(auth).forEach(function (name) { headers[name] = auth[name]; });
    var response = await fetch("/api/nova/language", {
      method: "PUT",
      headers: headers,
      body: JSON.stringify({screen_language: code})
    });
    if (!response.ok) {
      return {screen_language: code, persisted: false, voice_interpretation: false, bidirectional_text: false};
    }
    var body = await response.json();
    if (overclaims(body)) return {screen_language: read(), persisted: false, voice_interpretation: false, bidirectional_text: false};
    return body;
  }

  window.AmiCorLanguage = {
    key: KEY,
    supported: supported,
    workspace: verified,
    rollout: rollout,
    notices: notices,
    read: read,
    write: write,
    pull: pull,
    push: push,
    guardTask: guardTask,
    applyNotice: applyNotice,
    approvalCopy: approvalCopy
  };
})();
