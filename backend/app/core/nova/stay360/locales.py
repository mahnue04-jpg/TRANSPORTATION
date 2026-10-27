"""Static Stay360 locale catalogs. No translation API is called."""

from __future__ import annotations

from .constants import BLUEPRINT_NOTE, DESCRIPTOR, PRODUCT_NAME, SUPPORTED_LOCALES

_SCOPE_EN = (
    "This slice covers privacy-safe guest prearrival, reservation lookup, "
    "mock flight and road arrivals, housekeeping, room readiness, and eligible "
    "mobile check-in simulation. " + BLUEPRINT_NOTE
)
_SCOPE_ES = (
    "Esta sección cubre la prellegada del huésped con privacidad, la consulta de reservas, "
    "llegadas simuladas por vuelo y carretera, limpieza, disponibilidad de la habitación "
    "y la simulación del registro móvil. "
    "La asignación de estacionamiento está incluida. "
    "No están implementados: concierge, guest services, inventory safeguards, "
    "family/events, marketing, itinerary. "
    + BLUEPRINT_NOTE
)
_SCOPE_FR = (
    "Cette tranche couvre la préarrivée protégée, la consultation de réservation, "
    "les arrivées simulées par vol et par route, le housekeeping, la disponibilité "
    "de la chambre et la simulation d'enregistrement mobile. "
    "L'affectation du stationnement est incluse. "
    "Ne sont pas implémentés : concierge, guest services, inventory safeguards, "
    "family/events, marketing, itinerary. "
    + BLUEPRINT_NOTE
)

_EN: dict[str, str] = {
    "product.name": PRODUCT_NAME,
    "product.descriptor": DESCRIPTOR,
    "nav.locale": "Language",
    "nav.dashboard": "Hotel dashboard",
    "nav.arrivals": "Arrivals",
    "nav.rooms": "Rooms",
    "nav.checkin": "Mobile check-in",
    "nav.lookup": "Reservation lookup",
    "privacy.list_notice": "Staff lists show a display label and reservation reference. Raw identity, contact, and payment fields stay off the list.",
    "arrivals.title": "Prearrival board",
    "arrivals.refresh": "Apply mock arrival update",
    "arrivals.empty": "No reservations are on this board.",
    "rooms.title": "Housekeeping and room readiness",
    "rooms.update": "Update housekeeping",
    "housekeeping.dirty": "Dirty",
    "housekeeping.in_progress": "In progress",
    "housekeeping.inspected": "Inspected",
    "housekeeping.out_of_order": "Out of order",
    "readiness.ready": "Ready",
    "readiness.cleaning": "Cleaning",
    "readiness.not_ready": "Not ready",
    "readiness.blocked": "Blocked",
    "checkin.title": "Eligible mobile check-in simulation",
    "checkin.simulate": "Simulate check-in",
    "checkin.reference": "Reservation reference",
    "checkin.confirmation": "Confirmation code",
    "checkin.no_door_access": "No door code, mobile key, or physical access is issued.",
    "checkin.no_payment": "No payment is captured.",
    "lookup.title": "Lookup by reservation reference",
    "lookup.reference": "Reservation reference",
    "lookup.submit": "Look up",
    "session.token": "Platform access token",
    "session.load": "Load hotel dashboard",
    "session.signout": "Clear token",
    "errors.not_found": "That reservation reference was not found for this hotel.",
    "errors.forbidden": "This role cannot open that Stay360 action.",
    "errors.not_eligible": "Mobile check-in is not eligible yet.",
    "errors.generic": "Stay360 could not complete that action.",
    "slice.scope_note": _SCOPE_EN,
    "slice.synthetic_notice": "Synthetic fixtures only. No live hotel, airline, map, or payment provider is contacted.",
    "meta.fixture_date": "Fixture date",
    "dashboard.counts": "Operational counts",
    "dashboard.hotel": "Hotel",
    "dashboard.rooms_not_ready": "Not ready, cleaning, or blocked",
    "blueprint.citation": "Blueprint document: Hospitality & Travel Master Blueprint, version 1.1. This is not the product title.",
    "table.reference": "Reference",
    "table.guest": "Guest label",
    "table.room": "Room",
    "table.arrival": "Arrival",
    "table.readiness": "Readiness",
    "table.eligibility": "Check-in",
    "parking.title": "Parking assignment",
    "parking.no_gate": "No gate code, barrier command, or payment is issued.",
    "parking.empty": "No stall is assigned on this board.",
    "parking.update": "Update stall",
    "parking.stall": "Stall code",
    "table.stall": "Stall",
    "table.vehicle": "Vehicle label",
    "parking.assigned": "Assigned",
    "parking.occupied": "Occupied",
    "parking.released": "Released",
}

_ES: dict[str, str] = {
    "product.name": PRODUCT_NAME,
    "product.descriptor": "Operaciones hoteleras inteligentes",
    "nav.locale": "Idioma",
    "nav.dashboard": "Panel del hotel",
    "nav.arrivals": "Llegadas",
    "nav.rooms": "Habitaciones",
    "nav.checkin": "Registro móvil",
    "nav.lookup": "Consulta de reserva",
    "privacy.list_notice": "Las listas del personal muestran una etiqueta y la referencia de reserva. Identidad, contacto y pago en bruto quedan fuera de la lista.",
    "arrivals.title": "Tablero de prellegada",
    "arrivals.refresh": "Aplicar actualización de llegada simulada",
    "arrivals.empty": "No hay reservas en este tablero.",
    "rooms.title": "Limpieza y disponibilidad",
    "rooms.update": "Actualizar limpieza",
    "housekeeping.dirty": "Sucia",
    "housekeeping.in_progress": "En curso",
    "housekeeping.inspected": "Inspeccionada",
    "housekeeping.out_of_order": "Fuera de servicio",
    "readiness.ready": "Lista",
    "readiness.cleaning": "En limpieza",
    "readiness.not_ready": "No lista",
    "readiness.blocked": "Bloqueada",
    "checkin.title": "Simulación de registro móvil elegible",
    "checkin.simulate": "Simular registro",
    "checkin.reference": "Referencia de reserva",
    "checkin.confirmation": "Código de confirmación",
    "checkin.no_door_access": "No se emite código de puerta, llave móvil ni acceso físico.",
    "checkin.no_payment": "No se captura ningún pago.",
    "lookup.title": "Consulta por referencia de reserva",
    "lookup.reference": "Referencia de reserva",
    "lookup.submit": "Consultar",
    "session.token": "Token de acceso de la plataforma",
    "session.load": "Cargar panel del hotel",
    "session.signout": "Borrar token",
    "errors.not_found": "Esa referencia de reserva no se encontró para este hotel.",
    "errors.forbidden": "Este rol no puede abrir esa acción de Stay360.",
    "errors.not_eligible": "El registro móvil todavía no es elegible.",
    "errors.generic": "Stay360 no pudo completar esa acción.",
    "slice.scope_note": _SCOPE_ES,
    "slice.synthetic_notice": "Solo datos sintéticos. No se contacta ningún proveedor real de hotel, aerolínea, mapa o pago.",
    "meta.fixture_date": "Fecha del escenario",
    "dashboard.counts": "Conteos operativos",
    "dashboard.hotel": "Hotel",
    "dashboard.rooms_not_ready": "No listas, en limpieza o bloqueadas",
    "blueprint.citation": "Documento del plano: Hospitality & Travel Master Blueprint, versión 1.1. Este no es el título del producto.",
    "table.reference": "Referencia",
    "table.guest": "Etiqueta del huésped",
    "table.room": "Habitación",
    "table.arrival": "Llegada",
    "table.readiness": "Disponibilidad",
    "table.eligibility": "Registro",
    "parking.title": "Asignación de estacionamiento",
    "parking.no_gate": "No se emite código de barrera, comando de acceso ni pago.",
    "parking.empty": "No hay un lugar asignado en este tablero.",
    "parking.update": "Actualizar lugar",
    "parking.stall": "Código de lugar",
    "table.stall": "Lugar",
    "table.vehicle": "Etiqueta del vehículo",
    "parking.assigned": "Asignado",
    "parking.occupied": "Ocupado",
    "parking.released": "Liberado",
}

_FR: dict[str, str] = {
    "product.name": PRODUCT_NAME,
    "product.descriptor": "Exploitation hôtelière intelligente",
    "nav.locale": "Langue",
    "nav.dashboard": "Tableau de l'hôtel",
    "nav.arrivals": "Arrivées",
    "nav.rooms": "Chambres",
    "nav.checkin": "Enregistrement mobile",
    "nav.lookup": "Consultation de réservation",
    "privacy.list_notice": "Les listes du personnel affichent une étiquette et la référence de réservation. Identité, contact et paiement bruts restent hors liste.",
    "arrivals.title": "Tableau de préarrivée",
    "arrivals.refresh": "Appliquer la mise à jour d'arrivée simulée",
    "arrivals.empty": "Aucune réservation sur ce tableau.",
    "rooms.title": "Housekeeping et disponibilité",
    "rooms.update": "Mettre à jour le housekeeping",
    "housekeeping.dirty": "Sale",
    "housekeeping.in_progress": "En cours",
    "housekeeping.inspected": "Inspectée",
    "housekeeping.out_of_order": "Hors service",
    "readiness.ready": "Prête",
    "readiness.cleaning": "En nettoyage",
    "readiness.not_ready": "Pas prête",
    "readiness.blocked": "Bloquée",
    "checkin.title": "Simulation d'enregistrement mobile éligible",
    "checkin.simulate": "Simuler l'enregistrement",
    "checkin.reference": "Référence de réservation",
    "checkin.confirmation": "Code de confirmation",
    "checkin.no_door_access": "Aucun code de porte, clé mobile ou accès physique n'est émis.",
    "checkin.no_payment": "Aucun paiement n'est capturé.",
    "lookup.title": "Consultation par référence de réservation",
    "lookup.reference": "Référence de réservation",
    "lookup.submit": "Consulter",
    "session.token": "Jeton d'accès de la plateforme",
    "session.load": "Charger le tableau de l'hôtel",
    "session.signout": "Effacer le jeton",
    "errors.not_found": "Cette référence de réservation est introuvable pour cet hôtel.",
    "errors.forbidden": "Ce rôle ne peut pas ouvrir cette action Stay360.",
    "errors.not_eligible": "L'enregistrement mobile n'est pas encore éligible.",
    "errors.generic": "Stay360 n'a pas pu terminer cette action.",
    "slice.scope_note": _SCOPE_FR,
    "slice.synthetic_notice": "Données synthétiques uniquement. Aucun fournisseur réel d'hôtel, de vol, de carte ou de paiement n'est contacté.",
    "meta.fixture_date": "Date du scénario",
    "dashboard.counts": "Compteurs opérationnels",
    "dashboard.hotel": "Hôtel",
    "dashboard.rooms_not_ready": "Pas prêtes, en nettoyage ou bloquées",
    "blueprint.citation": "Document de référence : Hospitality & Travel Master Blueprint, version 1.1. Ce n'est pas le titre du produit.",
    "table.reference": "Référence",
    "table.guest": "Étiquette du client",
    "table.room": "Chambre",
    "table.arrival": "Arrivée",
    "table.readiness": "Disponibilité",
    "table.eligibility": "Enregistrement",
    "parking.title": "Affectation du stationnement",
    "parking.no_gate": "Aucun code de barrière, commande d'accès ou paiement n'est émis.",
    "parking.empty": "Aucune place n'est affectée sur ce tableau.",
    "parking.update": "Mettre à jour la place",
    "parking.stall": "Code de place",
    "table.stall": "Place",
    "table.vehicle": "Étiquette du véhicule",
    "parking.assigned": "Affectée",
    "parking.occupied": "Occupée",
    "parking.released": "Libérée",
}

CATALOGS: dict[str, dict[str, str]] = {"en": _EN, "es": _ES, "fr": _FR}


def locale_keys() -> frozenset[str]:
    return frozenset(_EN)


def catalog(code: str) -> dict[str, str]:
    normalized = str(code or "").strip().lower()
    if normalized not in CATALOGS:
        from .errors import Stay360Error

        raise Stay360Error(404, "locale_not_supported", "That Stay360 locale is not in the catalog.")
    return dict(CATALOGS[normalized])


def _keys_match() -> None:
    expected = set(_EN)
    for code in SUPPORTED_LOCALES:
        if set(CATALOGS[code]) != expected:
            missing = expected.symmetric_difference(CATALOGS[code])
            raise RuntimeError(f"Stay360 locale {code} key mismatch: {sorted(missing)}")
        if CATALOGS[code]["product.name"] != PRODUCT_NAME:
            raise RuntimeError("Stay360 product name must stay stable across locales")


_keys_match()
