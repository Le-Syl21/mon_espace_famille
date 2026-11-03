"""Constants for Mon Espace Famille."""

from __future__ import annotations

import os
from datetime import time, timedelta
from typing import Final

DOMAIN: Final = "mon_espace_famille"

# Development only: MEF_API_BASE points the client at a stand-in portal (a base
# URL ending with "/"). Unset in production, which uses the real portal.
API_BASE: Final = os.environ.get("MEF_API_BASE") or "https://app.monespacefamille.fr/api/v2/"
# The web app's public client id (it ships in its JavaScript bundle).
CLIENT_ID: Final = "963568d5-b3ca-4d91-8a73-9eebda59822b"
USER_AGENT: Final = "mon_espace_famille (+https://github.com/Le-Syl21/mon_espace_famille)"

UPDATE_INTERVAL: Final = timedelta(minutes=30)

CONF_WEEKS: Final = "semaines"
WEEKS_DEFAULT: Final = 3
WEEKS_MAX: Final = 8

# After a booking or a cancellation the server answers {"status": "queued"}
# and applies it shortly after: read the week again this many times.
VERIFY_ATTEMPTS: Final = 5
VERIFY_DELAY: Final = 2.0  # seconds

# Service kinds, the values of the actions' `service` field.
KIND_REPAS: Final = "repas"
KIND_ACCUEIL_MATIN: Final = "accueil_matin"
KIND_ACCUEIL_SOIR: Final = "accueil_soir"
KIND_ETUDE: Final = "etude"
KINDS: Final = (KIND_REPAS, KIND_ACCUEIL_MATIN, KIND_ACCUEIL_SOIR, KIND_ETUDE)

# Words of the commune's service labels (upper case, accents removed) that
# tell the kind, tried in this order: "ÉTUDE", "ACCUEIL SOIR", "REPAS PERMANENT"…
KIND_KEYWORDS: Final = (
    (KIND_ETUDE, ("ETUDE",)),
    (KIND_ACCUEIL_MATIN, ("MATIN",)),
    (KIND_ACCUEIL_SOIR, ("SOIR",)),
    (KIND_REPAS, ("REPAS", "CANTINE", "RESTAURATION", "DEJEUNER", "MIDI")),
)

# The commune's day, which the calendar and the "at home" sensors share:
# périscolaire from 7:00 to 18:45, classes 8:30–11:30 and 13:30–16:30.
MORNING_CARE_START: Final = time(7, 0)
SCHOOL_START: Final = time(8, 30)
SCHOOL_END: Final = time(16, 30)
EVENING_SERVICE_END: Final = time(18, 45)
# The child leaves home at the first time when a morning care is booked, and
# at the second one otherwise (a little before the school's doors open).
DEPARTURE_MORNING_CARE: Final = time(7, 0)
DEPARTURE_SCHOOL: Final = time(8, 10)
# Added to the end of school or of the evening service to get the arrival home.
TRAVEL_MARGIN: Final = timedelta(minutes=10)
# Evening services, the first one booked wins when both are.
EVENING_KINDS: Final = (KIND_ACCUEIL_SOIR, KIND_ETUDE)

# Calendar names and hours of each kind.
# A service of unknown kind becomes an all-day event.
KIND_NAMES: Final = {
    KIND_REPAS: "Cantine",
    KIND_ACCUEIL_MATIN: "Accueil du matin",
    KIND_ACCUEIL_SOIR: "Accueil du soir",
    KIND_ETUDE: "Étude",
}
KIND_HOURS: Final = {
    KIND_ACCUEIL_MATIN: (MORNING_CARE_START, SCHOOL_START),
    KIND_REPAS: (time(11, 30), time(13, 30)),
    KIND_ETUDE: (SCHOOL_END, EVENING_SERVICE_END),
    KIND_ACCUEIL_SOIR: (SCHOOL_END, EVENING_SERVICE_END),
}

# What a day of a service can be, as the API lists it. French values: they
# show up in attributes, which automations read.
STATUS_BOOKED: Final = "reserve"
STATUS_BOOKING_PENDING: Final = "reservation_en_attente"
STATUS_CANCEL_PENDING: Final = "annulation_en_attente"
STATUS_PRESENT: Final = "present"
STATUS_PRESENT_UNBOOKED: Final = "present_sans_reservation"
STATUS_ABSENT: Final = "absent"
STATUS_ABSENT_JUSTIFIED: Final = "absence_justifiee"
STATUS_FAILING: Final = "en_defaut"

# API list -> status, later lists win over earlier ones for the same day (the
# web app's own order: a day both validated and attended is attended).
STATUS_LISTS: Final = (
    ("failing", STATUS_FAILING),
    ("validated", STATUS_BOOKED),
    ("pendingRequest", STATUS_BOOKING_PENDING),
    ("pendingCancel", STATUS_CANCEL_PENDING),
    ("attendances", STATUS_PRESENT),
    ("attendancesWithoutResa", STATUS_PRESENT_UNBOOKED),
    ("absences", STATUS_ABSENT),
    ("absencesJutified", STATUS_ABSENT_JUSTIFIED),  # sic, the API's spelling
    ("absencesJustified", STATUS_ABSENT_JUSTIFIED),
)
# Days the child has (or had) a place for.
RESERVED_STATUSES: Final = frozenset(
    {STATUS_BOOKED, STATUS_BOOKING_PENDING, STATUS_PRESENT, STATUS_PRESENT_UNBOOKED}
)
# Days that can be cancelled, deadline permitting.
CANCELLABLE_STATUSES: Final = frozenset({STATUS_BOOKED})

ATTR_CHILD: Final = "enfant"
ATTR_SERVICE: Final = "service"
ATTR_DATES: Final = "dates"
SERVICE_BOOK: Final = "reserver"
SERVICE_CANCEL: Final = "annuler"

# Order of the services in the planning card, and the planning's cache.
PLANNING_ORDER: Final = (KIND_ACCUEIL_MATIN, KIND_REPAS, KIND_ACCUEIL_SOIR, KIND_ETUDE)
PLANNING_CACHE_SECONDS: Final = 15.0

# The planning card, served from the integration.
CARD_FILE: Final = "mon-espace-famille-planning-card.js"
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILE}"
