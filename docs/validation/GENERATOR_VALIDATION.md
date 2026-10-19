# Generator validation (v1)

`python -m generator.validate --seasons 3 --frames 8` on 2026-10-19: three synthetic leagues, each playing its full 38-round fixture list (1,140 matches), compared with the Wyscout Premier League 2017/18 targets. Position frames are built for 8 matches and checked against each player's SkillCorner-based physical profile and the SkillCorner team-shape medians.

CI runs the same check at 2 seasons + 4 framed matches on every push (`.github/workflows/ci.yml`). Before committing, the 2-season check was also run on seeds 3000, 4100, 5200 and 6300 to make sure the bands aren't tuned to one seed.

```
1140 matches in 44.8 s

metric                          synthetic     target     band  
goals_per_match                     2.736      2.679    0.150  ok
home_goals                          1.626      1.532    0.150  ok
away_goals                          1.110      1.147    0.150  ok
home_win                            0.474      0.455    0.050  ok
draw                                0.234      0.261    0.050  ok
away_win                            0.292      0.284    0.050  ok
shots_per_match                    23.939     23.370    2.000  ok
open_play_conversion                0.112      0.108    0.015  ok
on_target_share                     0.359      0.353    0.040  ok
header_share                        0.191      0.156    0.040  ok
second_half_goal_share              0.569      0.580    0.040  ok
passes_per_match                  903.100    864.890   60.000  ok
pass_completion_open_play           0.805      0.825    0.030  ok
possessions_per_match             162.365    156.100   15.000  ok
corners_per_match                   9.309     10.290    1.500  ok
throw_ins_per_match                50.139     44.870    7.000  ok
goal_kicks_per_match               13.564     15.950    3.000  ok
free_kicks_per_match               28.086     24.540    4.000  ok
fouls_per_match                    23.733     21.420    3.000  ok
yellows_per_match                   3.117      3.105    0.600  ok
reds_per_match                      0.111      0.108    0.080  ok
offsides_per_match                  4.599      4.100    1.500  ok
subs_per_team                       2.744      2.740    0.200  ok
penalties_per_match                 0.213      0.211    0.080  ok
penalty_conversion                  0.679      0.700    0.100  ok
corner_shot_15s                     0.303      0.297    0.060  ok
team_shots_log_sd                   0.189      0.220    0.060  ok
half1_minutes                      47.027     46.900    1.000  ok
half2_minutes                      49.247     49.100    1.000  ok
season_points_sd                   17.594     18.690    4.500  ok
season_points_max                  99.000    100.000   18.000  ok
season_points_min                  25.000     31.000   12.000  ok
completion_ground                   0.912      0.917    0.050  ok
completion_high                     0.552      0.537    0.050  ok
completion_head                     0.624      0.625    0.050  ok
completion_cross                    0.294      0.307    0.050  ok
completion_launch                   0.526      0.538    0.050  ok
completion_through                  0.421      0.392    0.050  ok
shot_share_0-6                      0.064      0.037    0.040  ok
shot_share_6-11                     0.172      0.157    0.040  ok
shot_share_11-16.5                  0.284      0.287    0.040  ok
shot_share_16.5-22                  0.181      0.187    0.040  ok
shot_share_22-30                    0.228      0.251    0.040  ok
shot_share_30-99                    0.071      0.081    0.040  ok
frames_distance_vs_profile          0.971      1.000    0.060  ok
frames_sprints_vs_profile           1.011      1.000    0.350  ok
frames_team_width_m                37.900     37.000    4.000  ok
frames_team_depth_m                33.700     31.000    5.000  ok

48/48 metrics within band
```

Notes
- `season_points_*` targets come from a single, record season (champions on 100 points), so their bands are wide.
- `frames_*_vs_profile` are ratios of what the frames produce to each player's own profile (1.0 = exact).
- Possessions are counted with the calibration's rule (the ball changes hands only when the other team takes control).
