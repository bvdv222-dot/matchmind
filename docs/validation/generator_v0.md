# Generator v0 validation

`python -m generator.validate --seasons 3` on 2026-10-19: three synthetic seasons (3 leagues x 380 fixtures = 1,140 matches) compared with the Wyscout Premier League 2017/18 calibration targets. Bands are the tolerances in `generator/validate.py`; CI fails if any metric leaves its band.

```
1140 matches in 33.6 s

metric                          synthetic     target     band  
goals_per_match                     2.744      2.679    0.150  ok
home_goals                          1.582      1.532    0.150  ok
away_goals                          1.161      1.147    0.150  ok
home_win                            0.468      0.455    0.050  ok
draw                                0.221      0.261    0.050  ok
away_win                            0.311      0.284    0.050  ok
shots_per_match                    25.107     23.370    2.000  ok
open_play_conversion                0.106      0.108    0.015  ok
on_target_share                     0.347      0.353    0.040  ok
header_share                        0.187      0.156    0.040  ok
second_half_goal_share              0.542      0.580    0.040  ok
passes_per_match                  900.769    864.890   60.000  ok
pass_completion_open_play           0.809      0.825    0.030  ok
possessions_per_match             160.635    156.100   15.000  ok
corners_per_match                   9.268     10.290    1.500  ok
throw_ins_per_match                48.555     44.870    7.000  ok
goal_kicks_per_match               13.421     15.950    3.000  ok
free_kicks_per_match               27.970     24.540    4.000  ok
fouls_per_match                    23.597     21.420    3.000  ok
yellows_per_match                   3.030      3.105    0.600  ok
reds_per_match                      0.156      0.108    0.080  ok
offsides_per_match                  4.609      4.100    1.500  ok
subs_per_team                       2.730      2.740    0.200  ok
penalties_per_match                 0.214      0.211    0.080  ok
penalty_conversion                  0.689      0.700    0.080  ok
corner_shot_15s                     0.305      0.297    0.060  ok
team_shots_log_sd                   0.205      0.220    0.060  ok
half1_minutes                      47.086     46.900    1.000  ok
half2_minutes                      49.147     49.100    1.000  ok
completion_ground                   0.915      0.917    0.050  ok
completion_high                     0.564      0.537    0.050  ok
completion_head                     0.634      0.625    0.050  ok
completion_cross                    0.300      0.307    0.050  ok
completion_launch                   0.543      0.538    0.050  ok
completion_through                  0.430      0.392    0.050  ok
shot_share_0-6                      0.063      0.037    0.040  ok
shot_share_6-11                     0.171      0.157    0.040  ok
shot_share_11-16.5                  0.288      0.287    0.040  ok
shot_share_16.5-22                  0.178      0.187    0.040  ok
shot_share_22-30                    0.228      0.251    0.040  ok
shot_share_30-99                    0.072      0.081    0.040  ok

41/41 metrics within band
```

Close to a band edge (watch these when changing the engine): shots per match (+1.7), draws (-0.04), free kicks (+3.4), header share (+0.03), goal kicks (-2.5).
