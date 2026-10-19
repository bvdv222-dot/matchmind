# Data provenance & licences

MatchMind runs on **synthetic** match data from its own generator. No real match is replayed or shipped. Real open data was used only to calibrate the generator's distributions.

| Source | Used for | Licence | In this repo |
|---|---|---|---|
| Wyscout soccer-logs — L. Pappalardo, P. Cintia, A. Rossi, E. Massucco, P. Ferragina, D. Pedreschi, F. Giannotti, *A public data set of spatio-temporal match events in soccer competitions*, Scientific Data 6, 236 (2019); figshare collection 4415000 | Event rates, transitions, possessions, set pieces, pass completion, xG model, team-strength spread, game-state effects, final-table spread, player attribute distributions (Premier League 2017/18, 380 matches) | CC BY 4.0 | Derived parameters only: [calibration/params_wyscout_pl1718.json](../calibration/params_wyscout_pl1718.json), produced by [calibration/profile_wyscout.py](../calibration/profile_wyscout.py). Raw files are not included. |
| SkillCorner open data (github.com/SkillCorner/opendata) | Physical profiles by position (distance, sprints, top speed) behind the position frames, and the team block width / depth they are checked against | MIT | Profiling script [calibration/profile_sc.py](../calibration/profile_sc.py); no raw files. |

Player and club names in the app are generated and fictional. Wyscout's player table includes real names; only its height, weight, age and foot *distributions* are used.

To reproduce the calibration, download the Wyscout `events.zip`, `matches.zip`, `players.json` and `teams.json` from figshare into a folder outside the repo, extract `events_England.json` and `matches_England.json`, then run:

```
py -I calibration/profile_wyscout.py <that folder> calibration/params_wyscout_pl1718.json
```
