"""Screen catalogs versus the unverified business-language rollout.

English, Somali, Arabic, French, and Spanish already have Workspace and
Synapse screen copy. Japanese, Korean, Greek, Russian, and German can be
saved as an account preference. They are not operational business delivery.
"""

from __future__ import annotations

VERIFIED_SCREEN = ("en", "so", "ar", "fr", "es")
ROLLOUT = ("ja", "ko", "el", "ru", "de")
SUPPORTED = VERIFIED_SCREEN + ROLLOUT

NOTICES = {
    "ja": "この言語は展開計画に含まれています。この言語での業務提供は未検証です。",
    "ko": "이 언어는 도입 계획에 있습니다. 이 언어로 하는 업무 제공은 검증되지 않았습니다.",
    "el": "Αυτή η γλώσσα είναι στο σχέδιο διάθεσης. Η επιχειρηματική παράδοση σε αυτή τη γλώσσα δεν έχει επαληθευτεί.",
    "ru": "Этот язык входит в план внедрения. Деловая работа на этом языке не проверена.",
    "de": "Diese Sprache steht im Einführungsplan. Geschäftliche Lieferung in dieser Sprache ist nicht geprüft.",
}

APPROVAL = {
    "en": {
        "approval_is_not_execution": "Approval is not execution.",
        "approve": "Approve",
        "reject": "Reject",
        "original_preserved": "Original language is preserved.",
        "unsupported_not_applied": "Unsupported translation was not applied.",
        "legal_not_translated": "Legal terms were not translated.",
        "client_approval_not_translated": "Client approval text was not translated.",
    },
    "so": {
        "approval_is_not_execution": "Ansixintu ma aha fulin.",
        "approve": "Ansixi",
        "reject": "Diid",
        "original_preserved": "Luqadda asalka waa la ilaaliyay.",
        "unsupported_not_applied": "Turjumaan aan la taageerin lama isticmaalin.",
        "legal_not_translated": "Erayada sharciga lama turjumin.",
        "client_approval_not_translated": "Qoraalka ansixinta macmiilka lama turjumin.",
    },
    "ar": {
        "approval_is_not_execution": "الموافقة ليست تنفيذًا.",
        "approve": "موافقة",
        "reject": "رفض",
        "original_preserved": "تم الحفاظ على اللغة الأصلية.",
        "unsupported_not_applied": "لم يتم تطبيق ترجمة غير مدعومة.",
        "legal_not_translated": "لم تُترجم المصطلحات القانونية.",
        "client_approval_not_translated": "لم يُترجم نص موافقة العميل.",
    },
    "fr": {
        "approval_is_not_execution": "L’approbation n’est pas une exécution.",
        "approve": "Approuver",
        "reject": "Refuser",
        "original_preserved": "La langue d’origine est conservée.",
        "unsupported_not_applied": "Une traduction non prise en charge n’a pas été appliquée.",
        "legal_not_translated": "Les termes juridiques n’ont pas été traduits.",
        "client_approval_not_translated": "Le texte d’approbation du client n’a pas été traduit.",
    },
    "es": {
        "approval_is_not_execution": "La aprobación no es una ejecución.",
        "approve": "Aprobar",
        "reject": "Rechazar",
        "original_preserved": "El idioma original se conserva.",
        "unsupported_not_applied": "No se aplicó una traducción no admitida.",
        "legal_not_translated": "Los términos legales no se tradujeron.",
        "client_approval_not_translated": "El texto de aprobación del cliente no se tradujo.",
    },
    "ja": {
        "approval_is_not_execution": "承認は実行ではありません。",
        "approve": "承認",
        "reject": "却下",
        "original_preserved": "原文の言語は保持されます。",
        "unsupported_not_applied": "未対応の翻訳は適用されていません。",
        "legal_not_translated": "法的用語は翻訳されていません。",
        "client_approval_not_translated": "顧客の承認文は翻訳されていません。",
    },
    "ko": {
        "approval_is_not_execution": "승인은 실행이 아닙니다.",
        "approve": "승인",
        "reject": "거절",
        "original_preserved": "원문 언어가 유지됩니다.",
        "unsupported_not_applied": "지원되지 않는 번역은 적용되지 않았습니다.",
        "legal_not_translated": "법률 용어는 번역되지 않았습니다.",
        "client_approval_not_translated": "고객 승인 문구는 번역되지 않았습니다.",
    },
    "el": {
        "approval_is_not_execution": "Η έγκριση δεν είναι εκτέλεση.",
        "approve": "Έγκριση",
        "reject": "Απόρριψη",
        "original_preserved": "Η αρχική γλώσσα διατηρείται.",
        "unsupported_not_applied": "Δεν εφαρμόστηκε μη υποστηριζόμενη μετάφραση.",
        "legal_not_translated": "Οι νομικοί όροι δεν μεταφράστηκαν.",
        "client_approval_not_translated": "Το κείμενο έγκρισης του πελάτη δεν μεταφράστηκε.",
    },
    "ru": {
        "approval_is_not_execution": "Согласование не является исполнением.",
        "approve": "Согласовать",
        "reject": "Отклонить",
        "original_preserved": "Исходный язык сохранён.",
        "unsupported_not_applied": "Неподдерживаемый перевод не применён.",
        "legal_not_translated": "Юридические термины не переведены.",
        "client_approval_not_translated": "Текст согласования клиента не переведён.",
    },
    "de": {
        "approval_is_not_execution": "Genehmigung ist keine Ausführung.",
        "approve": "Genehmigen",
        "reject": "Ablehnen",
        "original_preserved": "Die Ausgangssprache bleibt erhalten.",
        "unsupported_not_applied": "Eine nicht unterstützte Übersetzung wurde nicht angewendet.",
        "legal_not_translated": "Rechtliche Begriffe wurden nicht übersetzt.",
        "client_approval_not_translated": "Der Text der Kundenfreigabe wurde nicht übersetzt.",
    },
}


def status(code: str) -> dict:
    """Preference metadata. Rollout languages stay unverified."""
    verified = code in VERIFIED_SCREEN
    return {
        "screen_language": code,
        "screen_catalog_verified": verified,
        "business_delivery_operational": verified,
        "business_delivery_mode": "ai_assisted_text" if verified else "not_verified",
        "translation_verified": False,
        "operational": verified,
        "voice_interpretation": False,
        "bidirectional_text": False,
        "supported": list(SUPPORTED),
        "rollout_languages": list(ROLLOUT),
        "notice": NOTICES.get(code, ""),
        "approval_copy": APPROVAL.get(code, APPROVAL["en"]),
    }
