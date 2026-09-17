# Pesk Ebrel — suivi satellite

Carte de la position du voilier **Pesk Ebrel** (MMSI `227314800`), mise à jour à partir des positions satellite quotidiennes.

**➡️ [Carte](https://natim.github.io/pesk_ebrel_map/)**

La carte est une page statique : Leaflet, tuiles OpenStreetMap / OpenSeaMap, CSV lu par le navigateur. Même principe que [france-ga-pilot-maps](https://github.com/Natim/france-ga-pilot-maps) pour les prix : **éditer le CSV suffit**, GitHub Pages le sert tel quel.

## Mettre à jour la position

Chaque relevé satellite est une ligne dans [`docs/positions.csv`](docs/positions.csv) :

```csv
observed_at,latitude,longitude,speed_kn,course_deg,alarms,note
2026-09-17T09:31:44Z,36°16'43.05 N,17°35'49.68 W,6.48,174,,
```

| Colonne | Contenu |
| --- | --- |
| `observed_at` | Horodatage UTC (`2026-09-17T09:31:44Z` ou `2026-09-17 09:31:44 UTC`) |
| `latitude` / `longitude` | Degrés décimaux (`36.278625`) ou DMS (`36°16'43.05 N`, `17°35'49.68 W`) |
| `speed_kn` | Vitesse en nœuds, facultative |
| `course_deg` | Cap vrai 0–360°, facultatif |
| `alarms` | Texte d'alarme, vide = aucun |
| `note` | Commentaire libre |

Pour coller les secondes avec le symbole `"` (`36°16'43.05" N`), entourez le champ de guillemets CSV.

Ajoutez la ligne, ouvrez une pull request ou poussez sur `main`. La CI lance `python3 validate_positions.py docs/positions.csv`. Une fois mergée, GitHub Pages republie la carte **sans régénération**.

Prévisualisation locale :

```bash
python3 -m http.server --directory docs 8000
```

Puis [http://127.0.0.1:8000/](http://127.0.0.1:8000/). `file://` bloque le `fetch()` du CSV.

## Déploiement

GitHub Pages, dossier `docs/`, workflow Actions. **Settings → Pages → Source : GitHub Actions**.

## Licence

MIT, voir [LICENSE](LICENSE).
