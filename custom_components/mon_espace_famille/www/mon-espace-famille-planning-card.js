/*
 * Mon Espace Famille planning card: one week at a time, a row per child, a
 * column per open day, a pastille per service (morning care, canteen,
 * evening care, study hall). Tapping a pastille edits a draft; nothing is
 * sent until the user validates and confirms. Plain ES module, no build step.
 */

const CARD_TYPE = "mon-espace-famille-planning-card";
const WS = "mon_espace_famille";
const KINDS = ["accueil_matin", "repas", "accueil_soir", "etude"];

const ICONS = {
  accueil_matin: "mdi:weather-sunset-up",
  repas: "mdi:silverware-fork-knife",
  accueil_soir: "mdi:weather-sunset-down",
  etude: "mdi:book-open-page-variant",
};
// Inline icons (24x24), so they look the same with or without <ha-icon>.
// Moon is filled, the others are strokes.
const SVG = {
  accueil_matin: { fill: false, d: "M2 18h20M6.500 18a5.500 5.500 0 0 1 11 0M12 3v6M9 6l3-3 3 3M4.500 11l2 2M19.500 11l-2 2" },
  repas: { fill: false, d: "M5 3v6a2.500 2.500 0 0 0 5 0V3M7.500 3v18M18 21V3c-2.800 1.600-3.800 4.200-3.800 7.500H18" },
  accueil_soir: { fill: true, d: "M20.500 14.500A9 9 0 0 1 9.500 3.500 9 9 0 1 0 20.500 14.500z" },
  etude: { fill: false, d: "M12 6.500C10.300 5.300 7.800 5 3.500 5v13.500c4.300 0 6.800.3 8.500 1.500 1.700-1.200 4.200-1.500 8.500-1.500V5c-4.300 0-6.800.3-8.500 1.500zM12 6.500V20" },
};
const SVG_LOCK = "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z";
const SVG_PENCIL = "M4 20l1-4L16 5l3 3L8 19zM14 7l3 3";

const TEXTS = {
  fr: {
    week: "Semaine",
    prev: "Semaine précédente",
    next: "Semaine suivante",
    today: "Aujourd'hui",
    loading: "Chargement…",
    noDay: "Aucun jour ouvert cette semaine.",
    noChild: "Aucun enfant à afficher.",
    legend: "Légende",
    short: { accueil_matin: "Matin", repas: "Midi", accueil_soir: "Soir", etude: "Étude" },
    toBooked: "→ réservé",
    toCancelled: "→ annulé",
    booked: "Vert = réservé",
    notBooked: "Rouge = non réservé",
    locked: "Grisé = verrouillé (plus modifiable)",
    changed: "Contour = modifié, pas envoyé",
    svc: {
      accueil_matin: "Accueil du matin",
      repas: "Repas",
      accueil_soir: "Accueil du soir",
      etude: "Étude",
    },
    changes: (n) => `${n} modification${n > 1 ? "s" : ""}`,
    inOtherWeeks: (n) => `dont ${n} dans d'autres semaines`,
    undo: "Annuler les modifications",
    validate: "Valider",
    cellBooked: "réservé",
    cellNotBooked: "non réservé",
    willBook: "sera réservé",
    willCancel: "sera annulé",
    lockedPast: "jour passé",
    lockedDeadline: "date limite dépassée",
    lockedAttended: "déjà pointé",
    lockedPending: "en cours de traitement par le portail",
    lockedFailing: "en défaut",
    until: (d) => `modifiable jusqu'au ${d} inclus`,
    confirmTitle: "Confirmer les modifications",
    changesBlock: "Modifications",
    costBlock: "Coût",
    riskBlock: "Risque de garde",
    back: "Retour",
    confirm: "Confirmer",
    review: "Revoir",
    close: "Fermer",
    estimating: "Estimation en cours…",
    costUnavailable: "Estimation indisponible : le portail n'a pas répondu.",
    costAmount: (a) => `Montant annoncé par le portail : ${a}.`,
    costCounts: (s) => `${s} — facturés après coup (commune à paiement différé), le portail n'annonce pas de montant.`,
    costCountsPrepaid: (s) => `${s} — le portail n'annonce pas de montant à l'avance.`,
    cancelFree: "Une annulation faite avant la date limite est gratuite.",
    countBook: (n, name) => `${n} ${name.toLowerCase()} réservé${n > 1 ? "s" : ""}`,
    countCancel: (n, name) => `${n} ${name.toLowerCase()} annulé${n > 1 ? "s" : ""}`,
    actBook: "Réserver",
    actCancel: "Annuler",
    refusedItem: (why) => `refusé : ${why}`,
    riskNone: "Aucun risque de garde dans ces modifications.",
    applying: "Application en cours, cela peut durer une dizaine de secondes…",
    done: "Modifications enregistrées sur le portail.",
    conflictTitle: "Le portail a changé entre-temps",
    conflictText:
      "Quelqu'un (l'autre parent ?) a modifié ces cases depuis que vous les avez vues. Rien n'a été envoyé. Vos autres modifications sont conservées ; vérifiez-les avant de valider à nouveau.",
    conflictItem: (was, now) => `vous voyiez « ${was} », le portail indique « ${now} »`,
    refusedTitle: "Modifications refusées",
    refusedText: "Ces modifications ne sont plus possibles. Rien n'a été envoyé.",
    partialTitle: "Certaines modifications n'ont pas abouti",
    failedTitle: "Les modifications n'ont pas abouti",
    partialText: "Ces modifications n'ont pas été confirmées par le portail :",
    resultError: "refusée par le portail",
    resultNotConfirmed: "non confirmée (réessayez dans un instant)",
    errorLoad: "Impossible de lire le portail :",
    errorAuth: "Identifiants refusés par le portail : reconnectez l'intégration.",
    errorGeneric: "Erreur :",
    reasons: {
      past: "jour passé",
      deadline: "date limite dépassée",
      not_offered: "service non proposé ce jour-là",
      not_registered: "enfant non inscrit à ce service",
      unchanged: "déjà dans l'état demandé",
      attended: "déjà pointé",
      pending: "en cours de traitement",
      failing: "en défaut",
    },
    risk: {
      cancel_accueil_soir: (c, d, h) =>
        `Pour ${c}, l'enfant n'est plus pris en charge à partir de ${h} le ${d} : il faut le récupérer à l'école.`,
      cancel_etude: (c, d, h) =>
        `Pour ${c}, plus d'étude le ${d} : l'enfant sort de classe à ${h}, il faut le récupérer à l'école.`,
      cancel_repas: (c, d, h) =>
        `Pour ${c}, pas de repas à la cantine le ${d} (à ${h}) : prévoir un repas ou venir chercher l'enfant pour le midi.`,
      cancel_accueil_matin: (c, d, h) =>
        `Pour ${c}, plus d'accueil avant la classe le ${d} : l'enfant ne peut pas être déposé avant ${h}.`,
      book_accueil_soir: (c, d, h) =>
        `Pour ${c}, l'enfant sera gardé après la classe le ${d} (jusqu'à ${h}) : annulable jusqu'à la date limite.`,
      book_etude: (c, d, h) =>
        `Pour ${c}, l'enfant ira à l'étude le ${d} (jusqu'à ${h}) : annulable jusqu'à la date limite.`,
      book_repas: (c, d) =>
        `Pour ${c}, l'enfant déjeunera à la cantine le ${d} : le repas sera dû même en cas d'absence une fois la date limite passée.`,
      book_accueil_matin: (c, d, h) =>
        `Pour ${c}, l'enfant sera accueilli dès ${h} le ${d} : annulable jusqu'à la date limite.`,
      late: "Si la date limite est dépassée, le portail refuse la réservation : vérifiez qu'elle apparaît bien ensuite.",
    },
  },
  en: {
    week: "Week",
    prev: "Previous week",
    next: "Next week",
    today: "Today",
    loading: "Loading…",
    noDay: "No open day this week.",
    noChild: "No child to show.",
    legend: "Legend",
    short: { accueil_matin: "Morning", repas: "Lunch", accueil_soir: "Evening", etude: "Study" },
    toBooked: "→ booked",
    toCancelled: "→ cancelled",
    booked: "Green = booked",
    notBooked: "Red = not booked",
    locked: "Greyed = locked (no longer editable)",
    changed: "Outline = changed, not sent",
    svc: {
      accueil_matin: "Morning care",
      repas: "Canteen",
      accueil_soir: "Evening care",
      etude: "Study hall",
    },
    changes: (n) => `${n} change${n > 1 ? "s" : ""}`,
    inOtherWeeks: (n) => `${n} in other weeks`,
    undo: "Undo changes",
    validate: "Validate",
    cellBooked: "booked",
    cellNotBooked: "not booked",
    willBook: "will be booked",
    willCancel: "will be cancelled",
    lockedPast: "past day",
    lockedDeadline: "deadline passed",
    lockedAttended: "already checked in",
    lockedPending: "being processed by the portal",
    lockedFailing: "failing",
    until: (d) => `can be changed until ${d} included`,
    confirmTitle: "Confirm the changes",
    changesBlock: "Changes",
    costBlock: "Cost",
    riskBlock: "Childcare risk",
    back: "Back",
    confirm: "Confirm",
    review: "Review",
    close: "Close",
    estimating: "Estimating…",
    costUnavailable: "Estimate unavailable: the portal did not answer.",
    costAmount: (a) => `Amount announced by the portal: ${a}.`,
    costCounts: (s) => `${s} — billed afterwards (deferred payment), the portal announces no amount.`,
    costCountsPrepaid: (s) => `${s} — the portal announces no amount in advance.`,
    cancelFree: "Cancelling before the deadline is free.",
    countBook: (n, name) => `${n} × ${name.toLowerCase()} booked`,
    countCancel: (n, name) => `${n} × ${name.toLowerCase()} cancelled`,
    actBook: "Book",
    actCancel: "Cancel",
    refusedItem: (why) => `refused: ${why}`,
    riskNone: "No childcare risk in these changes.",
    applying: "Applying, this can take about ten seconds…",
    done: "Changes saved on the portal.",
    conflictTitle: "The portal changed in the meantime",
    conflictText:
      "Someone (the other parent?) changed these cells since you saw them. Nothing was sent. Your other changes are kept; check them before validating again.",
    conflictItem: (was, now) => `you saw “${was}”, the portal says “${now}”`,
    refusedTitle: "Changes refused",
    refusedText: "These changes are no longer possible. Nothing was sent.",
    partialTitle: "Some changes did not go through",
    failedTitle: "The changes did not go through",
    partialText: "The portal did not confirm these changes:",
    resultError: "refused by the portal",
    resultNotConfirmed: "not confirmed (try again in a moment)",
    errorLoad: "Cannot read the portal:",
    errorAuth: "The portal refused the login: reconnect the integration.",
    errorGeneric: "Error:",
    reasons: {
      past: "past day",
      deadline: "deadline passed",
      not_offered: "service not offered that day",
      not_registered: "child not registered to this service",
      unchanged: "already in the requested state",
      attended: "already checked in",
      pending: "being processed",
      failing: "failing",
    },
    risk: {
      cancel_accueil_soir: (c, d, h) =>
        `${c} is no longer looked after from ${h} on ${d}: pick them up at school.`,
      cancel_etude: (c, d, h) =>
        `${c} has no study hall on ${d}: school ends at ${h}, pick them up at school.`,
      cancel_repas: (c, d, h) =>
        `${c} will have no canteen meal on ${d} (at ${h}): plan a lunch or pick them up at noon.`,
      cancel_accueil_matin: (c, d, h) =>
        `${c} is no longer looked after before class on ${d}: they cannot be dropped off before ${h}.`,
      book_accueil_soir: (c, d, h) =>
        `${c} will be looked after after class on ${d} (until ${h}): cancellable until the deadline.`,
      book_etude: (c, d, h) =>
        `${c} will attend the study hall on ${d} (until ${h}): cancellable until the deadline.`,
      book_repas: (c, d) =>
        `${c} will eat at the canteen on ${d}: the meal is due even if absent once the deadline has passed.`,
      book_accueil_matin: (c, d, h) =>
        `${c} will be looked after from ${h} on ${d}: cancellable until the deadline.`,
      late: "If the deadline has passed the portal refuses the booking: check that it shows up afterwards.",
    },
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const STYLE = `
:host { display: block; }
ha-card { padding: 12px 8px 8px; overflow: hidden; }
* { box-sizing: border-box; }
button { font: inherit; color: inherit; }
.head { display: flex; align-items: center; gap: 4px; padding: 0 4px 8px; }
.head .label { flex: 1; display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; column-gap: .4em; text-align: center; font-weight: 500; font-size: 1.05em; min-width: 0; }
.head .label span { white-space: nowrap; }
.head .label .rng { color: var(--secondary-text-color); font-weight: 400; }
@container (max-width: 520px) { .head .label .sep { display: none; } .head .label span { flex: 1 1 100%; } }
.nav { min-width: 40px; height: 40px; border: 1px solid var(--divider-color); background: transparent; border-radius: 20px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0 10px; }
.nav:hover, .nav:focus-visible { background: var(--secondary-background-color); }
.nav svg { width: 22px; height: 22px; }
.today { font-size: .85em; }
.wrap { container-type: inline-size; }
ha-card { container-type: inline-size; }
.table { display: grid; grid-template-columns: minmax(52px, max-content) repeat(var(--days), minmax(0, 1fr)); align-items: center; column-gap: 2px; row-gap: 6px; overflow-x: auto; padding: 8px 0 4px; }
.dh { text-align: center; font-size: .85em; color: var(--secondary-text-color); line-height: 1.15; padding: 2px 0 4px; border-bottom: 1px solid var(--divider-color); }
.dh b { display: block; color: var(--primary-text-color); font-size: 1.15em; }
.dh.today-col b { color: var(--primary-color); text-decoration: underline; text-underline-offset: 3px; }
.name { font-weight: 500; padding: 0 6px 0 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell { display: flex; justify-content: center; padding: 5px 2px; margin: 0 1px; border-radius: 12px; background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
.slots { display: grid; gap: 3px; }
.grid .slots { grid-template-columns: repeat(2, var(--size)); }
.row .slots { grid-template-columns: repeat(var(--kinds), var(--size)); }
.slot { width: var(--size); height: var(--size); }
.pill { position: relative; width: var(--size); height: var(--size); padding: 0; border-radius: 10px; border: 2px solid var(--success-color, #2e7d32); background: var(--success-color, #2e7d32); color: #fff; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.pill svg.ico { width: calc(var(--size) * .72); height: calc(var(--size) * .72); fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.pill svg.ico.filled { fill: currentColor; stroke-width: 1; }
.pill.off { background: color-mix(in srgb, var(--error-color, #c62828) 14%, var(--card-background-color, #fff)); border-color: var(--error-color, #c62828); color: var(--error-color, #c62828); }
.pill.locked { cursor: not-allowed; opacity: .55; filter: saturate(.55); }
.chip { position: absolute; width: calc(var(--size) * .4); height: calc(var(--size) * .4); border-radius: 50%; background: var(--card-background-color, #fff); border: 1px solid var(--divider-color); color: var(--primary-text-color); display: inline-flex; align-items: center; justify-content: center; }
.chip svg { width: 70%; height: 70%; fill: none; stroke: currentColor; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.chip.lockb { right: -3px; bottom: -3px; }
.chip.edit { right: -4px; top: -4px; background: var(--primary-color); border-color: var(--primary-color); color: #fff; }
.pill.draft { outline: 3px solid var(--primary-color); outline-offset: 2px; }
.pill:focus-visible { outline: 3px solid var(--primary-text-color); outline-offset: 2px; }
.grid { --size: 36px; }
@container (min-width: 430px) { .grid { --size: 42px; } }
.row { --size: 40px; }
@container (max-width: 560px) {
  .table { grid-template-columns: repeat(var(--days), minmax(0, 1fr)); }
  .table .corner { display: none; }
  .table .name { grid-column: 1 / -1; padding-top: 6px; }
}
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 10px 6px 4px; font-size: .8em; color: var(--primary-text-color); border-top: 1px solid var(--divider-color); margin-top: 8px; }
.legend > span { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.legend .pill { --size: 22px; cursor: default; border-radius: 6px; border-width: 2px; opacity: 1; filter: none; }
.legend .pill.locked { opacity: .55; filter: saturate(.55); }
.legend .pill.draft { outline-width: 2px; outline-offset: 1px; }
.legend + .legend { border-top: 0; margin-top: 0; padding-top: 4px; }
.mini { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 6px; background: var(--success-color, #2e7d32); border: 2px solid var(--success-color, #2e7d32); color: #fff; vertical-align: -6px; margin-right: 4px; }
.mini.off { background: color-mix(in srgb, var(--error-color, #c62828) 14%, var(--card-background-color, #fff)); border-color: var(--error-color, #c62828); color: var(--error-color, #c62828); }
.mini.neutral { background: var(--secondary-text-color); border-color: var(--secondary-text-color); color: var(--card-background-color, #fff); }
.mini svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.mini svg.filled { fill: currentColor; stroke-width: 1; }
.foot { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 6px 4px; border-top: 1px solid var(--divider-color); margin-top: 6px; }
.foot .count { flex: 1 1 100%; font-weight: 500; }
.foot .count small { color: var(--secondary-text-color); font-weight: 400; margin-left: 6px; }
.btn { min-height: 40px; padding: 0 16px; border-radius: 20px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer; font-weight: 500; }
.btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
.btn:disabled { opacity: .5; cursor: default; }
.btn:focus-visible { outline: 3px solid var(--primary-text-color); outline-offset: 2px; }
.msg { padding: 8px 10px; margin: 6px 4px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); }
.msg.err { border-color: var(--error-color, #c62828); }
.msg.ok { border-color: var(--success-color, #2e7d32); }
.empty { padding: 16px 8px; text-align: center; color: var(--secondary-text-color); }
.modal { position: fixed; inset: 0; z-index: 9; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; padding: 12px; }
.dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color); width: min(560px, 100%); max-height: calc(100vh - 24px); display: flex; flex-direction: column; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
.dialog h2 { margin: 0; padding: 16px 18px 8px; font-size: 1.2em; font-weight: 500; }
.dialog .body { padding: 0 18px 8px; overflow-y: auto; }
.dialog .actions { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px 16px; border-top: 1px solid var(--divider-color); }
.block { border: 1px solid var(--divider-color); border-radius: 10px; margin: 8px 0; padding: 8px 12px; }
.block h3 { margin: 0 0 4px; font-size: .8em; letter-spacing: .06em; text-transform: uppercase; color: var(--secondary-text-color); font-weight: 600; }
.block.risk { border-left: 4px solid var(--warning-color, #f9a825); }
.block.cost { border-left: 4px solid var(--primary-color); }
.block ul { margin: 4px 0; padding-left: 18px; }
.block li { margin: 3px 0; }
.block .child { font-weight: 500; margin-top: 6px; }
.block .week { color: var(--secondary-text-color); font-size: .85em; margin: 4px 0 0; }
.tag { display: inline-block; font-size: .78em; font-weight: 600; padding: 0 6px; border-radius: 6px; border: 1px solid currentColor; margin-right: 4px; }
.tag.book { color: var(--success-color, #2e7d32); }
.tag.cancel { color: var(--error-color, #c62828); }
.bad { color: var(--error-color, #c62828); }
.spin { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--divider-color); border-top-color: var(--primary-color); border-radius: 50%; animation: s 1s linear infinite; vertical-align: -3px; margin-right: 6px; }
@keyframes s { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
`;

function pad(n) {
  return String(n).padStart(2, "0");
}
function parseISO(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d, 12);
}
function iso(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function mondayOf(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
function addDays(d, n) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
  x.setDate(x.getDate() + n);
  return x;
}
const keyOf = (child, service, date) => `${child}|${service}|${date}`;

class MonEspaceFamillePlanningCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._plans = new Map(); // monday ISO -> plan
    this._monday = iso(mondayOf(new Date()));
    this._draft = new Map(); // key -> {child, service, date, action, base}
    this._loading = false;
    this._error = null;
    this._notice = null;
    this._modal = null;
    this._seq = 0;
    this._onKey = (ev) => {
      if (ev.key === "Escape" && this._modal && this._modal.phase !== "applying") this._closeModal();
    };
    this.shadowRoot.addEventListener("click", (ev) => this._click(ev));
  }

  static getStubConfig() {
    return { type: `custom:${CARD_TYPE}` };
  }

  setConfig(config) {
    if (config.layout && !["row", "grid"].includes(config.layout)) {
      throw new Error("layout must be 'row' or 'grid'");
    }
    this._config = { layout: "grid", ...config };
    this._render();
  }

  getCardSize() {
    return 5;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._load(true);
    }
  }

  connectedCallback() {
    document.addEventListener("keydown", this._onKey);
    this._resize = new ResizeObserver(() => this._fit());
    this._resize.observe(this);
    if (this._hass && !this._loading && !this._plans.has(this._monday)) this._load(true);
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKey);
    this._resize?.disconnect();
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").toLowerCase();
    return lang.startsWith("fr") ? TEXTS.fr : TEXTS.en;
  }

  get _lang() {
    return (this._hass?.locale?.language || this._hass?.language || "en").toLowerCase().startsWith("fr")
      ? "fr"
      : "en";
  }

  // ---- data -------------------------------------------------------------

  _wsBase() {
    const msg = {};
    if (this._config.entry_id) msg.entry_id = this._config.entry_id;
    return msg;
  }

  async _fetchPlan(monday, fresh = false) {
    const plan = await this._hass.callWS({
      type: `${WS}/planning`,
      start: monday,
      ...(fresh ? { fresh: true } : {}),
      ...this._wsBase(),
    });
    this._plans.set(plan.monday, plan);
    return plan;
  }

  async _load(fresh = true) {
    if (!this._hass) return;
    const seq = ++this._seq;
    this._loading = true;
    this._error = null;
    this._render();
    try {
      const plan = await this._fetchPlan(this._monday, fresh);
      if (seq !== this._seq) return;
      this._dropStaleDrafts(plan);
    } catch (err) {
      if (seq !== this._seq) return;
      this._error = this._errText(err);
    }
    this._loading = false;
    this._render();
  }

  _errText(err) {
    const t = this._t;
    if (err?.code === "auth_failed") return t.errorAuth;
    if (err?.code === "portal_error") return `${t.errorLoad} ${err.message}`;
    return `${t.errorGeneric} ${err?.message || err?.code || err}`;
  }

  // A draft whose cell changed on the portal since it was made is dropped.
  _dropStaleDrafts(plan) {
    for (const d of [...this._draft.values()]) {
      if (plan.monday !== iso(mondayOf(parseISO(d.date)))) continue;
      const cell = this._cell(plan, d.child, d.service, d.date);
      if (!cell || cell.booked !== d.base || cell.locked) this._draft.delete(keyOf(d.child, d.service, d.date));
    }
  }

  _cell(plan, child, service, date) {
    const c = plan.children.find((x) => x.id === child);
    return c?.cells?.[date]?.[service];
  }

  _children(plan) {
    let list = plan.children;
    const f = this._config.children;
    if (Array.isArray(f) && f.length) {
      const wanted = f.map((x) => String(x).toLowerCase());
      list = list.filter((c) => wanted.includes(String(c.id)) || wanted.includes(c.name.toLowerCase()));
    }
    return list;
  }

  // ---- formatting ---------------------------------------------------------

  _short(dateISO) {
    const d = parseISO(dateISO);
    if (this._lang === "fr") return `${d.getDate()}/${d.getMonth() + 1}`;
    return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(d);
  }

  _longDay(dateISO) {
    const d = parseISO(dateISO);
    return new Intl.DateTimeFormat(this._lang, { weekday: "long", day: "numeric", month: "long" }).format(d);
  }

  _hour(hhmm) {
    return this._lang === "fr" ? hhmm.replace(":", " h ").replace(/ h 00$/, " h") : hhmm;
  }

  _fullDate(dateISO) {
    const d = parseISO(dateISO);
    return new Intl.DateTimeFormat(this._lang === "fr" ? "fr-FR" : "en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(d);
  }

  // ---- state of a pastille --------------------------------------------------

  _view(plan, child, service, date) {
    const cell = this._cell(plan, child.id, service, date);
    if (!cell) return null;
    const draft = this._draft.get(keyOf(child.id, service, date));
    const booked = draft ? draft.action === "book" : cell.booked;
    return { cell, draft: !!draft, booked };
  }

  _label(plan, child, service, date, v) {
    const t = this._t;
    const parts = [child.name, t.svc[service], this._longDay(date)];
    let state = v.booked ? t.cellBooked : t.cellNotBooked;
    if (v.draft) state = v.booked ? t.willBook : t.willCancel;
    let text = `${parts.join(", ")} : ${state}`;
    if (v.cell.locked) {
      const why = {
        past: t.lockedPast,
        deadline: t.lockedDeadline,
        attended: t.lockedAttended,
        pending: t.lockedPending,
        failing: t.lockedFailing,
      }[v.cell.reason];
      text += ` (${why || t.locked}${v.cell.deadline && v.cell.reason === "deadline" ? `, ${this._fullDate(v.cell.deadline)}` : ""})`;
    } else if (v.cell.booked && v.cell.deadline) {
      text += ` (${t.until(this._fullDate(v.cell.deadline))})`;
    }
    return text;
  }

  // ---- rendering --------------------------------------------------------------

  _icon(kind) {
    const i = SVG[kind];
    return `<svg class="ico ${i.fill ? "filled" : ""}" viewBox="0 0 24 24" aria-hidden="true"><path d="${i.d}"/></svg>`;
  }

  _glyph(path) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
  }

  _pill(plan, child, kind, date) {
    const v = this._view(plan, child, kind, date);
    if (!v || v.cell.reason === "not_offered") return `<span class="slot"></span>`;
    const label = esc(this._label(plan, child, kind, date, v));
    const cls = ["pill", v.booked ? "on" : "off"];
    if (v.cell.locked) cls.push("locked");
    if (v.draft) cls.push("draft");
    return `<button class="${cls.join(" ")}" data-child="${child.id}" data-service="${kind}" data-date="${date}" aria-label="${label}" title="${label}" aria-pressed="${v.booked}" ${v.cell.locked ? 'aria-disabled="true"' : ""}>
      ${this._icon(kind)}
      ${v.cell.locked ? `<span class="chip lockb">${this._glyph(SVG_LOCK)}</span>` : ""}
      ${v.draft ? `<span class="chip edit">${this._glyph(SVG_PENCIL)}</span>` : ""}
    </button>`;
  }

  _table(plan) {
    const t = this._t;
    const children = this._children(plan);
    if (!children.length) return `<div class="empty">${t.noChild}</div>`;
    if (!plan.days.length) return `<div class="empty">${t.noDay}</div>`;
    const kinds = KINDS.filter((k) => children.some((c) => c.services.includes(k)));
    const layout = this._config.layout === "row" ? "row" : "grid";
    const narrow = new Intl.DateTimeFormat(this._lang, { weekday: "narrow" });
    let html = `<div class="wrap"><div class="table ${layout}" style="--days:${plan.days.length};--kinds:${kinds.length}" role="table">`;
    html += `<div class="corner"></div>`;
    for (const d of plan.days) {
      const date = parseISO(d.date);
      html += `<div class="dh ${d.date === plan.today ? "today-col" : ""}" role="columnheader" aria-label="${esc(this._longDay(d.date))}">${esc(narrow.format(date))}<b>${date.getDate()}</b></div>`;
    }
    for (const child of children) {
      html += `<div class="name" role="rowheader">${esc(child.name)}</div>`;
      for (const d of plan.days) {
        html += `<div class="cell" role="cell"><div class="slots">${kinds.map((k) => (child.services.includes(k) ? this._pill(plan, child, k, d.date) : `<span class="slot"></span>`)).join("")}</div></div>`;
      }
    }
    return html + `</div></div>`;
  }

  _legend(plan) {
    const t = this._t;
    const kinds = KINDS.filter((k) => this._children(plan).some((c) => c.services.includes(k)));
    const tile = (cls, extra = "") => `<span class="pill ${cls}" aria-hidden="true">${extra}</span>`;
    const lock = `<span class="chip lockb">${this._glyph(SVG_LOCK)}</span>`;
    return `<div class="legend" aria-label="${t.legend}">
      ${kinds.map((k) => `<span><span class="mini neutral">${this._icon(k)}</span>${esc(t.short[k])} ${esc(this._hour(plan.services[k].start))}–${esc(this._hour(plan.services[k].end))}</span>`).join("")}
    </div><div class="legend">
      <span>${tile("on")}${t.booked}</span>
      <span>${tile("off")}${t.notBooked}</span>
      <span>${tile("on locked", lock)}${tile("off locked", lock)}${t.locked}</span>
      <span>${tile("on draft")}${t.changed}</span>
    </div>`;
  }

  _footer(plan) {
    const t = this._t;
    const n = this._draft.size;
    if (!n) return "";
    const here = [...this._draft.values()].filter((d) => iso(mondayOf(parseISO(d.date))) === plan.monday).length;
    const other = n - here;
    return `<div class="foot">
      <div class="count" role="status">${t.changes(n)}${other ? `<small>(${t.inOtherWeeks(other)})</small>` : ""}</div>
      <button class="btn" data-act="undo">${t.undo}</button>
      <button class="btn primary" data-act="validate">${t.validate}</button>
    </div>`;
  }

  _render() {
    const t = this._t;
    const plan = this._plans.get(this._monday);
    const monday = parseISO(this._monday);
    let label = `${t.week} ${plan ? plan.week : this._isoWeek(monday)}`;
    let sub = "";
    if (plan && plan.first_day) {
      sub = `${this._short(plan.first_day)} → ${this._short(plan.last_day)}`;
    } else {
      sub = `${this._short(this._monday)} → ${this._short(iso(addDays(monday, 4)))}`;
    }
    const chevron = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
    let body;
    if (this._error) body = `<div class="msg err" role="alert">${esc(this._error)}</div>`;
    else if (!plan) body = `<div class="empty">${t.loading}</div>`;
    else body = this._table(plan);
    const title = this._config.title ? `<div class="msg" style="border:0;background:none;font-weight:500">${esc(this._config.title)}</div>` : "";
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        ${title}
        <div class="head">
          <button class="nav" data-act="prev" aria-label="${t.prev}">${chevron("M15 5l-7 7 7 7")}</button>
          <div class="label" aria-live="polite" ${this._loading ? 'aria-busy="true"' : ""}><span>${label}</span><span class="sep" aria-hidden="true">·</span><span class="rng">${sub}</span></div>
          <button class="nav today" data-act="today">${t.today}</button>
          <button class="nav" data-act="next" aria-label="${t.next}">${chevron("M9 5l7 7-7 7")}</button>
        </div>
        ${this._notice ? `<div class="msg ${this._notice.kind}" role="status">${esc(this._notice.text)}</div>` : ""}
        ${body}
        ${plan && !this._error ? this._legend(plan) : ""}
        ${plan ? this._footer(plan) : ""}
      </ha-card>
      ${this._modal ? this._modalHtml() : ""}`;
    this._fit();
    if (this._modal && this._modal.focus !== false) {
      const target = this.shadowRoot.querySelector(".dialog [data-modal-primary]") || this.shadowRoot.querySelector(".dialog button");
      if (target && !this._modal.focused) {
        target.focus();
        this._modal.focused = this._modal.phase;
      }
    }
  }

  // The one-line layout needs room: where the card is too narrow for it (a
  // phone), fall back to the 2 x 2 grid instead of letting pastilles overlap.
  _fit() {
    const table = this.shadowRoot.querySelector(".table");
    if (!table || this._config.layout !== "row") return;
    const days = Number(table.style.getPropertyValue("--days"));
    const kinds = Number(table.style.getPropertyValue("--kinds"));
    const wide = table.clientWidth > 560;
    const fits = days * (kinds * 44 + 12) <= table.clientWidth - (wide ? 72 : 0);
    table.classList.toggle("row", fits);
    table.classList.toggle("grid", !fits);
  }

  _isoWeek(d) {
    const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const day = x.getUTCDay() || 7;
    x.setUTCDate(x.getUTCDate() + 4 - day);
    const y = new Date(Date.UTC(x.getUTCFullYear(), 0, 1));
    return Math.ceil(((x - y) / 86400000 + 1) / 7);
  }

  // ---- interaction ------------------------------------------------------------

  _click(ev) {
    const pill = ev.target.closest(".pill[data-child]");
    if (pill) return this._toggle(pill);
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "prev" || act === "next" || act === "today") {
      const cur = parseISO(this._monday);
      const next = act === "today" ? mondayOf(new Date()) : addDays(cur, act === "prev" ? -7 : 7);
      this._monday = iso(next);
      this._notice = null;
      this._load();
    } else if (act === "undo") {
      this._draft.clear();
      this._render();
    } else if (act === "validate") {
      this._openConfirm();
    } else if (act === "back" || act === "close") {
      this._closeModal();
    } else if (act === "confirm") {
      this._apply();
    } else if (act === "review") {
      this._closeModal();
      this._load(true);
    }
  }

  _toggle(pill) {
    const plan = this._plans.get(this._monday);
    if (!plan) return;
    const child = Number(pill.dataset.child);
    const { service, date } = pill.dataset;
    const cell = this._cell(plan, child, service, date);
    if (!cell || cell.locked) return;
    const key = keyOf(child, service, date);
    if (this._draft.has(key)) this._draft.delete(key);
    else this._draft.set(key, { child, service, date, action: cell.booked ? "cancel" : "book", base: cell.booked });
    this._notice = null;
    this._render();
    this.shadowRoot.querySelector(`.pill[data-child="${child}"][data-service="${service}"][data-date="${date}"]`)?.focus();
  }

  _changes() {
    return [...this._draft.values()].sort((a, b) => a.date.localeCompare(b.date) || a.child - b.child);
  }

  _childName(id) {
    for (const plan of this._plans.values()) {
      const c = plan.children.find((x) => x.id === id);
      if (c) return c.name;
    }
    return `#${id}`;
  }

  _hours() {
    for (const plan of this._plans.values()) return plan.services;
    return {};
  }

  async _openConfirm() {
    const changes = this._changes();
    if (!changes.length) return;
    this._modal = { phase: "confirm", changes, quote: null, quoteError: false };
    this._render();
    const modal = this._modal;
    try {
      const quote = await this._hass.callWS({
        type: `${WS}/quote`,
        changes: changes.map(({ child, service, date, action }) => ({ child, service, date, action })),
        ...this._wsBase(),
      });
      if (this._modal !== modal) return;
      modal.quote = quote;
    } catch (err) {
      if (this._modal !== modal) return;
      modal.quoteError = true;
    }
    modal.focus = false;
    this._render();
  }

  _closeModal() {
    this._modal = null;
    this._render();
  }

  async _apply() {
    const modal = this._modal;
    if (!modal || modal.phase !== "confirm") return;
    modal.phase = "applying";
    this._render();
    const changes = modal.changes;
    try {
      const res = await this._hass.callWS({
        type: `${WS}/apply`,
        changes: changes.map(({ child, service, date, action }) => ({ child, service, date, action })),
        base: changes.map(({ child, service, date, base }) => ({ child, service, date, booked: base })),
        ...this._wsBase(),
      });
      modal.result = res;
      if (res.status === "applied") {
        for (const c of changes) this._draft.delete(keyOf(c.child, c.service, c.date));
        this._modal = null;
        this._notice = { kind: "ok", text: this._t.done };
      } else {
        if (res.status === "conflict") {
          for (const c of res.conflicts) this._draft.delete(keyOf(c.child, c.service, c.date));
        } else if (res.status === "partial" || res.status === "failed") {
          for (const r of res.results) if (r.result === "applied") this._draft.delete(keyOf(r.child, r.service, r.date));
        }
        modal.phase = res.status;
      }
    } catch (err) {
      modal.phase = "error";
      modal.error = this._errText(err);
    }
    this._plans.clear();
    this._render();
    await this._load(true);
  }

  // ---- the dialog -----------------------------------------------------------------

  _item(c, plan) {
    const t = this._t;
    const v = (this._hours()[c.service]) || { start: "", end: "" };
    return `<li><span class="tag ${c.action}">${c.action === "book" ? t.actBook : t.actCancel}</span>${esc(t.svc[c.service])}, ${esc(this._longDay(c.date))}</li>`;
  }

  _groupedChanges(changes, quote) {
    const t = this._t;
    const items = new Map((quote?.items || []).map((i) => [keyOf(i.child, i.service, i.date), i]));
    const byChild = new Map();
    for (const c of changes) {
      const weeks = byChild.get(c.child) || new Map();
      const monday = iso(mondayOf(parseISO(c.date)));
      weeks.set(monday, [...(weeks.get(monday) || []), c]);
      byChild.set(c.child, weeks);
    }
    let html = "";
    for (const [child, weeks] of byChild) {
      html += `<div class="child">${esc(this._childName(child))}</div>`;
      for (const [monday, list] of [...weeks.entries()].sort()) {
        const first = this._short(monday);
        const last = this._short(iso(addDays(parseISO(monday), 4)));
        html += `<div class="week">${t.week} ${this._isoWeek(parseISO(monday))} · ${first} → ${last}</div><ul>`;
        for (const c of list) {
          const q = items.get(keyOf(c.child, c.service, c.date));
          const bad = q && !q.valid;
          html += `<li><span class="mini ${c.action === "book" ? "on" : "off"}">${this._icon(c.service)}</span>${esc(t.svc[c.service])}, ${esc(this._longDay(c.date))} <b>${c.action === "book" ? t.toBooked : t.toCancelled}</b>${bad ? ` <span class="bad">— ${esc(t.refusedItem(t.reasons[q.reason] || q.reason || "?"))}</span>` : ""}</li>`;
        }
        html += `</ul>`;
      }
    }
    return html;
  }

  _costHtml(modal) {
    const t = this._t;
    if (modal.quoteError) return `<p>${t.costUnavailable}</p>`;
    if (!modal.quote) return `<p><span class="spin"></span>${t.estimating}</p>`;
    const cost = modal.quote.cost;
    let html;
    if (cost.mode === "amount") {
      const money = new Intl.NumberFormat(this._lang === "fr" ? "fr-FR" : "en-GB", { style: "currency", currency: cost.currency || "EUR" }).format(cost.amount);
      html = `<p>${t.costAmount(money)}</p>`;
    } else {
      const parts = [];
      for (const c of cost.counts) {
        if (c.book) parts.push(t.countBook(c.book, t.svc[c.service] || c.name));
        if (c.cancel) parts.push(t.countCancel(c.cancel, t.svc[c.service] || c.name));
      }
      const text = parts.join(", ") || "—";
      html = `<p>${esc(cost.post_paid ? t.costCounts(text) : t.costCountsPrepaid(text))}</p>`;
    }
    if (modal.changes.some((c) => c.action === "cancel")) html += `<p>${t.cancelFree}</p>`;
    return html;
  }

  _riskHtml(modal) {
    const t = this._t;
    const hours = this._hours();
    const lines = [];
    // What would leave a child without care comes first.
    const ordered = [...modal.changes].sort((a, b) => (a.action === b.action ? 0 : a.action === "cancel" ? -1 : 1));
    for (const c of ordered) {
      const fn = t.risk[`${c.action}_${c.service}`];
      if (!fn) continue;
      const h = hours[c.service] || { start: "", end: "" };
      // The hour that matters: when the care starts to be missing (cancel) or ends (book).
      const hour = c.action === "cancel" ? (c.service === "accueil_matin" ? h.end : h.start) : c.service === "accueil_matin" ? h.start : h.end;
      lines.push(`<li>${esc(fn(this._childName(c.child), this._longDay(c.date), this._hour(hour)))}</li>`);
    }
    const late = modal.quote && modal.quote.items.some((i) => !i.valid) ? `<p class="bad">${esc(t.risk.late)}</p>` : "";
    return `${lines.length ? `<ul>${lines.join("")}</ul>` : `<p>${t.riskNone}</p>`}${late}`;
  }

  _modalHtml() {
    const t = this._t;
    const m = this._modal;
    let title = t.confirmTitle;
    let body = "";
    let actions = "";
    if (m.phase === "confirm" || m.phase === "applying") {
      const blocked = m.quote && (!m.quote.valid || m.quote.items.some((i) => !i.valid));
      body = `<div class="block"><h3>${t.changesBlock}</h3>${this._groupedChanges(m.changes, m.quote)}</div>
        <div class="block cost"><h3>1 · ${t.costBlock}</h3>${this._costHtml(m)}</div>
        <div class="block risk"><h3>2 · ${t.riskBlock}</h3>${this._riskHtml(m)}</div>
        ${m.phase === "applying" ? `<p role="status"><span class="spin"></span>${t.applying}</p>` : ""}`;
      actions = `<button class="btn" data-act="back" ${m.phase === "applying" ? "disabled" : ""}>${t.back}</button>
        <button class="btn primary" data-act="confirm" data-modal-primary ${m.phase === "applying" || !m.quote && !m.quoteError || blocked ? "disabled" : ""}>${t.confirm}</button>`;
    } else if (m.phase === "conflict") {
      title = t.conflictTitle;
      const rows = m.result.conflicts
        .map((c) => {
          const was = c.expected ? t.cellBooked : t.cellNotBooked;
          const now = c.actual ? t.cellBooked : t.cellNotBooked;
          return `<li>${esc(this._childName(c.child))}, ${esc(t.svc[c.service])}, ${esc(this._longDay(c.date))} : ${esc(t.conflictItem(was, now))}</li>`;
        })
        .join("");
      body = `<p>${t.conflictText}</p><div class="block"><ul>${rows}</ul></div>`;
      actions = `<button class="btn primary" data-act="review" data-modal-primary>${t.review}</button>`;
    } else if (m.phase === "refused") {
      title = t.refusedTitle;
      const rows = m.result.refused
        .map((c) => `<li>${esc(this._childName(c.child))}, ${esc(t.svc[c.service] || c.service)}, ${esc(this._longDay(c.date))} : ${esc(t.reasons[c.reason] || c.reason)}</li>`)
        .join("");
      body = `<p>${t.refusedText}</p><div class="block"><ul>${rows}</ul></div>`;
      actions = `<button class="btn primary" data-act="review" data-modal-primary>${t.review}</button>`;
    } else if (m.phase === "partial" || m.phase === "failed") {
      title = m.phase === "partial" ? t.partialTitle : t.failedTitle;
      const rows = m.result.results
        .filter((r) => r.result !== "applied")
        .map((r) => `<li>${esc(this._childName(r.child))}, ${esc(t.svc[r.service])}, ${esc(this._longDay(r.date))} : ${esc(r.result === "error" ? t.resultError : t.resultNotConfirmed)}</li>`)
        .join("");
      body = `<p>${t.partialText}</p><div class="block"><ul>${rows}</ul></div>`;
      actions = `<button class="btn primary" data-act="review" data-modal-primary>${t.review}</button>`;
    } else {
      title = t.errorGeneric;
      body = `<p class="bad">${esc(m.error)}</p>`;
      actions = `<button class="btn primary" data-act="close" data-modal-primary>${t.close}</button>`;
    }
    return `<div class="modal"><div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h2>${esc(title)}</h2><div class="body">${body}</div><div class="actions">${actions}</div></div></div>`;
  }
}

// Home Assistant installs a custom-elements registry polyfill while it boots, and
// modules added with add_extra_js_url run before that: an element defined too
// early is invisible to `customElements.get`, so the dashboard reports "Custom
// element doesn't exist". Wait for the app, then define the card.
function register() {
  if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, MonEspaceFamillePlanningCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Mon Espace Famille",
      description: "Weekly planning of the children's canteen and care, editable.",
      preview: false,
    });
  }
}
customElements.whenDefined("home-assistant").then(register);
