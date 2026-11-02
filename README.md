# Mon Espace Famille

<img src=".github/flags/gb.svg" height="14" alt="GB"> [English](#english) | <img src=".github/flags/fr.svg" height="14" alt="FR"> [Français](#français)

A Home Assistant integration for [Mon Espace Famille](https://app.monespacefamille.fr): the children's canteen, before- and after-school care and study hall in a calendar, and booking or cancelling them from Home Assistant.
Une intégration Home Assistant pour [Mon Espace Famille](https://app.monespacefamille.fr) : la cantine, l'accueil du matin et du soir et l'étude des enfants dans un calendrier, et leur réservation ou annulation depuis Home Assistant.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Le-Syl21&repository=mon_espace_famille&category=integration)

<a name="français"></a>
## <img src=".github/flags/fr.svg" height="14" alt="FR"> Français

### Ce que ça donne

Vous ajoutez votre compte Mon Espace Famille (e-mail et mot de passe de l'application). Chaque enfant inscrit à au moins un service devient un appareil ; les enfants inscrits à rien (les grands au collège) sont ignorés. Pour une enfant nommée Alice :

| Entité | Quoi | Exemple |
|---|---|---|
| `calendar.alice_periscolaire` | Un événement par jour réservé et par service, aux heures du service ; la description donne la date limite d'annulation, et pour les jours passés, présent ou absent | Cantine 11 h 30 – 13 h 30, « Réservé. Annulable jusqu'au 12/11/2026 inclus. » |
| `binary_sensor.alice_cantine_aujourd_hui` | Allumé si un repas est réservé aujourd'hui ; attributs `statut`, `annulable_jusqu_au` | Allumé |
| `binary_sensor.alice_cantine_demain` | La même chose pour demain | Éteint |
| `binary_sensor.alice_reservation_manquante` | Allumé si la semaine prochaine a un jour où la cantine est ouverte sans repas réservé ; attribut `jours` | Allumé, `["2026-11-12"]` |
| `sensor.alice_prochain_repas` | Le prochain jour avec un repas réservé ; attribut `dans_jours` | 05/11/2026 |
| `sensor.alice_repas_cette_semaine` | Nombre de jours réservés cette semaine, un capteur par service (`accueil_matin`, `accueil_soir`, `etude`…) ; attribut `jours` | 4 |

Les identifiants d'entités sont en français quelle que soit la langue de Home Assistant, pour pouvoir partager les automatisations ; les noms affichés sont traduits.

Horaires du calendrier : accueil du matin 7 h – 8 h 30, cantine 11 h 30 – 13 h 30, étude et accueil du soir 16 h 30 – 18 h 45. Un service que l'intégration ne reconnaît pas devient un événement sur la journée.

Les données sont relues toutes les 30 minutes : la semaine en cours et les 3 suivantes (*Configurer* change ce nombre).

### Réserver et annuler

Deux actions, `mon_espace_famille.reserver` et `mon_espace_famille.annuler` :

```yaml
action: mon_espace_famille.reserver
data:
  enfant: 0123456789abcdef0123456789abcdef  # l'appareil de l'enfant (ou une de ses entités)
  service: accueil_soir                     # repas, accueil_matin, accueil_soir ou etude
  dates:
    - "2026-11-12"
    - "2026-11-16"
```

Avant d'envoyer quoi que ce soit, l'intégration relit les semaines concernées et refuse, avec un message clair :
- un service auquel l'enfant n'est pas inscrit ;
- une réservation un jour où le service est fermé (vacances, jour férié, mercredi) ou après la date limite de réservation ;
- une annulation d'un jour non réservé ou après la date limite d'annulation.

Les jours déjà réservés sont simplement sautés. Mon Espace Famille répond « en file d'attente » : l'intégration relit ensuite la semaine jusqu'à voir le changement (une dizaine de secondes au plus) et signale une erreur s'il n'apparaît pas.

Exemple : prévenir le dimanche soir s'il manque un repas.

```yaml
automation:
  - alias: Repas manquant la semaine prochaine
    triggers:
      - trigger: time
        at: "19:00:00"
    conditions:
      - condition: time
        weekday: sun
      - condition: state
        entity_id: binary_sensor.alice_reservation_manquante
        state: "on"
    actions:
      - action: notify.notify
        data:
          message: >
            Pas de cantine réservée pour Alice le
            {{ state_attr('binary_sensor.alice_reservation_manquante', 'jours') | join(', ') }}
```

### Installation

1. Dans HACS, *Dépôts personnalisés* → ajoutez `https://github.com/Le-Syl21/mon_espace_famille`, catégorie *Intégration* ([ou ouvrez-la directement dans votre HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=Le-Syl21&repository=mon_espace_famille&category=integration)).
2. Installez-la, redémarrez Home Assistant.
3. *Paramètres* → *Appareils et services* → *Ajouter une intégration* → *Mon Espace Famille*.
4. Saisissez l'e-mail et le mot de passe de l'application. Si le mot de passe change, Home Assistant demande de se reconnecter.

### Limites

- Mon Espace Famille ne publie pas d'API : l'intégration parle à celle de son application web, qui peut changer sans prévenir.
- Testée avec une seule commune, où les services sont payés après coup. Une commune en prépaiement, où il faut payer pour valider le panier, n'est pas prise en charge.
- Les horaires sont ceux de cette commune et les mêmes tous les jours (ils se changent dans `const.py`).

### 💬 Communauté & support

Des questions, un bug à signaler ou juste envie d'en discuter ? Rejoignez le Discord, section *Home Assistant* :

[![Discord](https://img.shields.io/badge/Discord-Le--Syl21%20Tools-5865F2?logo=discord&logoColor=white)](https://discord.gg/T37DYHmt2j)

<a name="english"></a>
## <img src=".github/flags/gb.svg" height="14" alt="GB"> English

### What you get

You add your Mon Espace Famille account (the app's email and password). Each child registered to at least one service becomes a device; children registered to nothing (older ones in secondary school) are left out. For a child named Alice:

| Entity | What | Example |
|---|---|---|
| `calendar.alice_periscolaire` | One event per booked day and service, at the service's hours; the description gives the cancellation deadline and, for past days, whether the child attended | Cantine 11:30–13:30, "Réservé. Annulable jusqu'au 12/11/2026 inclus." |
| `binary_sensor.alice_cantine_aujourd_hui` | On when a meal is booked today; `statut`, `annulable_jusqu_au` attributes | On |
| `binary_sensor.alice_cantine_demain` | The same for tomorrow | Off |
| `binary_sensor.alice_reservation_manquante` | On when next week has a day the canteen is open with no meal booked; `jours` attribute | On, `["2026-11-12"]` |
| `sensor.alice_prochain_repas` | The next day with a meal booked; `dans_jours` attribute | 2026-11-05 |
| `sensor.alice_repas_cette_semaine` | Days booked this week, one sensor per service (`accueil_matin`, `accueil_soir`, `etude`…); `jours` attribute | 4 |

Entity ids are French and the same in every language, so automations can be shared; the displayed names are translated.

Calendar hours: morning care 7:00–8:30, canteen 11:30–13:30, study hall and evening care 16:30–18:45. A service the integration does not recognise becomes an all-day event.

The data is read every 30 minutes: the current week and the next 3 (*Configure* changes that number).

### Booking and cancelling

Two actions, `mon_espace_famille.reserver` (book) and `mon_espace_famille.annuler` (cancel), with the fields `enfant` (the child's device, or one of its entities), `service` (`repas`, `accueil_matin`, `accueil_soir` or `etude`) and `dates`.

Before sending anything the integration reads the weeks concerned again and refuses, with a clear message, a service the child is not registered to, a booking on a day the service is closed or past its booking deadline, and a cancellation of a day not booked or past its cancellation deadline. Days already booked are skipped. Mon Espace Famille answers "queued": the integration then reads the week again until the change shows (ten seconds at most) and raises an error if it does not.

### Installation

1. In HACS, *Custom repositories* → add `https://github.com/Le-Syl21/mon_espace_famille`, category *Integration* ([or open it straight in your HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=Le-Syl21&repository=mon_espace_famille&category=integration)).
2. Install it, restart Home Assistant.
3. *Settings* → *Devices & services* → *Add integration* → *Mon Espace Famille*.
4. Enter the app's email and password. If the password changes, Home Assistant asks you to log in again.

### Limits

- Mon Espace Famille publishes no API: the integration talks to its web app's one, which may change without notice.
- Tested with a single commune, where services are paid afterwards. A commune where the cart must be paid in advance is not supported.
- The hours are that commune's, the same every day (they live in `const.py`).

### 💬 Community & support

Questions, bug reports, or just want to chat? Join the Discord, *Home Assistant* section:

[![Discord](https://img.shields.io/badge/Discord-Le--Syl21%20Tools-5865F2?logo=discord&logoColor=white)](https://discord.gg/T37DYHmt2j)

## Development / Développement

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

The tests never reach the real server: a fake one answers from anonymised recordings in `tests/fixtures`.

## License / Licence

MIT. See [LICENSE](LICENSE).
