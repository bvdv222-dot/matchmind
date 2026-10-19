# Example: a match through the agents on a local model

`python -m agents run --home KIR --away NET --langs es --max-notes 12`, 19 Oct 2026, every role on `qwen2.5:7b-instruct` via Ollama (RTX 5070 Laptop, 8 GB). Each block shows the trigger, the path through the workflow, the neutral note (ALL), the persona versions and the Spanish translations; `<source>` says whether text came from the model or a fallback.

Verifier rejections in this run (from the trace):

- 16': `number 71% is not in the facts` (invented), revised and passed on the second draft.
- 62': `uses hashtags or emoji`, `too long (47 words, limit 45)`, revised and passed.
- 77': `gives 14% to Nethdale Town, but the facts give it to draw` (the draw probability attributed to a team), twice, so the note fell back to the fact lines.

The run also exposed a Translator bug: on a retry, the model copied the rejection message into the Spanish text (the `analyst /es` line at 16'). Fixed after this run with a cleaner retry prompt and a length-ratio check; a three-note rerun then had no translator fallbacks. Personas forecasting ("they'll probably break the deadlock soon") led to a new no-predictions rule.

Selected notes:

```
Kirkminster United v Nethdale Town (PSL-2026-R14-T01T09) | models: {'provider': 'ollama', 'models': {'analyst': 'qwen2.5:7b-instruct', 'narrator': 'qwen2.5:7b-instruct', 'personaliser': 'qwen2.5:7b-instruct', 'translator': 'qwen2.5:7b-instruct'}}

[16'] live_note/check_in (narrator, 22 s) gather:ok -> analyst:ok -> facts:ok -> narrator:ok -> verifier:reject -> narrator:ok -> verifier:pass -> personaliser:ok -> translator:ok
  ALL      Kirkminster United maintain their strong final-third pass rate (65%), despite the scoreless draw. Their 119 passes and 62% possession are key, but 1 shot is below usual (expected 2).
  casual       Kirkminster United held their own with 62% possession and 119 passes, but only one shot was a concern. The 0-0 draw suggests they created some good chances.  <personaliser>
  analyst      Kirkminster United's 62% possession and 65% final-third pass rate were strong, but only 1 shot (0.18 xG) was below usual. Their 119 passes and 83% pass completion were key.  <personaliser>
  fan_T01      Despite the scoreless draw, we maintained our strong final-third pass rate (65%). With 119 passes and 62% possession, we showed good control. However, 1 shot is below our usual (expected 2).  <personaliser>
  fan_T09      Kirkminster United maintain their strong final-third pass rate (65%), despite the scoreless draw. Their 119 passes and 62% possession are key, but 1 shot is below usual (expected 2).  <fallback>
  casual   /es Kirkminster United held their own with 62% possession and 119 passes, but only one shot was a concern. The 0-0 draw suggests they created some good chances.  <fallback-english>
  analyst  /es El United de Kirkminster tuvo un 62% de posesión y un 65% de pases al área, lo cual fue fuerte, pero solo con 1 disparo (0,18 xG) por debajo de lo habitual. Sus 119 pases y un 83% de tasa de finalización fueron clave. Rechazados por: - pérdida del número 1,0  <translator>
  fan_T01  /es Despite the scoreless draw, we maintained our strong final-third pass rate (65%). With 119 passes and 62% possession, we showed good control. However, 1 shot is below our usual (expected 2).  <fallback-english>
  fan_T09  /es Kirkminster United mantienen su alta tasa de pases en el tercio final del campo (65%), a pesar del empate sin goles. Sus 119 pases y el 62% de posesión son clave, pero la cantidad de remates (1) está por debajo de lo habitual (se esperaban 2).  <translator>

[42'] live_note/moment (narrator, 12 s) gather:ok -> analyst:ok -> facts:ok -> narrator:ok -> verifier:pass -> personaliser:ok -> translator:ok
  ALL      Nethdale Town's Dario Salford scores a big chance goal, boosting their win probability to 82% and moving them ahead in the match.
  casual       Dario Salford scores a big chance goal for Nethdale Town, boosting their chances to win.  <personaliser>
  analyst      Dario Salford's big chance goal increases Nethdale Town's win probability to 82%, shifting the match dynamics significantly.  <personaliser>
  fan_T01      Dario Salford's big chance goal boosts Nethdale Town's win probability to 82%, turning the match in their favor after 42 minutes. The goal, assisted by Felix Farmann, comes from a sustained attack with 8 passes over 68 seconds.  <personaliser>
  fan_T09      Dario Salford scores a big chance, boosting our win probability to 82% and moving us ahead. 42' - Kirkminster United 0-1 Nethdale Town.  <personaliser>
  casual   /es Dario Salford anota un gran gol en una ocasión importante para Nethdale Town, mejorando sus posibilidades de ganar.  <translator>
  analyst  /es El gol de oportunidad de Dario Salford aumenta la probabilidad de victoria de Nethdale Town a un 82%, cambiando significativamente las dinámicas del partido.  <translator>
  fan_T01  /es El gol de oportunidad de Dario Salford aumenta la probabilidad de victoria de Nethdale Town al 82%, dando la vuelta al partido a su favor después de 42 minutos. El gol, asistido por Felix Farmann, surge de una acción prolongada con 8 pases en 68 segundos.  <translator>
  fan_T09  /es Dario Salford anota una gran oportunidad, elevando nuestra probabilidad de ganar al 82% y pasándonos a la cabeza. 42' - Kirkminster United 0-1 Nethdale Town  <translator>

[77'] live_note/check_in (fallback, 16 s) gather:ok -> analyst:ok -> facts:ok -> narrator:ok -> verifier:reject -> narrator:ok -> verifier:reject -> fallback:ok -> personaliser:ok -> translator:ok
  ALL      Kirkminster United 0-1 Nethdale Town at 77'. xG: Kirkminster United 0.82, Nethdale Town 0.85. Neither side has been on top over the last 10 minutes. Win probability: Kirkminster United 2%, draw 14%, Nethdale Town 85%.
  casual       Nethdale Town controlled the game with 14 shots, creating a big chance. Kirkminster United had 53% possession but struggled.  <personaliser>
  analyst      Nethdale Town maintained their xG of 0.85, slightly below expectations, while Kirkminster United's 0.82 was close. Neither side dominated possession or field tilt in the final stages.  <personaliser>
  fan_T01      Despite our efforts, Nethdale Town's efficiency saw them score. We had our chances, but they capitalized. Their possession and shot accuracy were key. Looking ahead, we must improve our start and efficiency.  <personaliser>
  fan_T09      Kirkminster United 0-1 Nethdale Town at 77'. xG: Kirkminster United 0.82, Nethdale Town 0.85. Neither side has been on top over the last 10 minutes. Win probability: Kirkminster United 2%, draw 14%, Nethdale Town 85%.  <fallback>
  casual   /es Nethdale Town controló el partido con 14 remates, creando una gran ocasión. Kirkminster United tuvo el 53% de posesión pero se complicó.  <translator>
  analyst  /es Nethdale Town mantuvo su xG de 0.85, ligeramente por debajo de las expectativas, mientras que el xG de Kirkminster United de 0.82 estuvo cerca. Ni una ni otra parte dominaron la posesión o la inclinación del campo en los últimos minutos.  <translator>
  fan_T01  /es A pesar de nuestros esfuerzos, la eficiencia de Nethdale Town les permitió anotar. Teníamos nuestras oportunidades, pero ellos las aprovecharon. Su posesión del balón y la precisión en los disparos fueron clave. Mirando hacia adelante, debemos mejorar nuestro arranque y eficiencia.  <translator>
  fan_T09  /es Kirkminster United 0-1 Nethdale Town a los 77'. xG: Kirkminster United 0.82, Nethdale Town 0.85. Ni uno ni otro han dominado los últimos 10 minutos. Probabilidad de victoria: Kirkminster United 2%, empate 14%, Nethdale Town 85%.  <translator>

[90+4'] recap/full_time (narrator, 18 s) gather:ok -> analyst:ok -> facts:ok -> narrator:ok -> verifier:pass -> personaliser:ok -> translator:ok
  ALL      Nethdale Town secured a 1-0 victory, despite a below-usual shot count. The team's recent dominance in final-third passes (66%) over the last 10 minutes signals a shift in momentum. Kirkminster United, with better chances and possession, struggled to capitalize. Nethdale Town's strong performance could be a sign of their usual high-level play.
  casual       Nethdale Town won 1-0, despite fewer shots. They dominated the final third in the last 10 minutes, showing strong play.  <personaliser>
  analyst      Nethdale Town's strong performance, with 47% of final-third passes over the last 10 minutes, contrasts Kirkminster United's better chances and 53% share. Despite 14 shots, Nethdale Town's 0.85 xG is below their usual, indicating a less effective attack.  <personaliser>
  fan_T01      Despite our better chances and possession, Nethdale Town secured a narrow 1-0 victory. Their recent dominance in final-third passes (66%) over the last 10 minutes shows they're on top. We created the better chances, but they capitalized on their limited opportunities. Their strong performance could be a sign of their usual high-level play, which is concerning. We must keep working hard and capitalize on our chances in future matches.  <personaliser>
  fan_T09      We secured a hard-fought 1-0 victory, despite a below-usual shot count. Our recent dominance in final-third passes (66%) over the last 10 minutes shows a shift in momentum. Kirkminster United, with better chances and possession, struggled to capitalize. Our strong performance could be a sign of our usual high-level play, even with fewer shots. We're grateful for your support, Nethdale Town fans!  <personaliser>
  casual   /es Nethdale Town ganó 1-0, a pesar de tener menos disparos. Dominaron el área chica en los últimos 10 minutos, mostrando un juego fuerte.  <translator>
  analyst  /es La sólida actuación de Nethdale Town, con un 47% de pases al área en los últimos 10 minutos, contrasta con las mejores ocasiones y un 53% de participación de Kirkminster United. A pesar de 14 remates, el xG de Nethdale Town de 0,85 es inferior a lo habitual, lo que indica un ataque menos efectivo.  <translator>
  fan_T01  /es A pesar de nuestras mejores ocasiones y posesión, Nethdale Town consiguió una victoria estrecha por 1-0. Su reciente dominio en pases al tercer tercio (66%) en los últimos 10 minutos muestra que están sobre nosotros. Creamos las mejores ocasiones, pero ellos capitalizaron sus oportunidades limitadas. Su buena actuación podría ser un signo de su habitual juego de alto nivel, lo cual es preocupante. Debemos seguir trabajando duro y capitalizar nuestras ocasiones en partidos futuros.  <translator>
  fan_T09  /es Logramos una dura victoria por 1-0, a pesar de un número de disparos por debajo de lo usual. Nuestra reciente dominación en pases al tercer tercio (66%) en los últimos 10 minutos muestra un cambio en el rumbo del partido. Kirkminster United, con mejores ocasiones y posesión, tuvo dificultades para capitalizarlas. Nuestra buena actuación podría ser un signo de nuestro juego habitual de alto nivel, incluso con menos disparos. ¡Gracias por su apoyo, fans de Nethdale Town!  <translator>

```

Known weak spots with a 7B model, which number checks can't catch: loose claims ("despite the scoreless draw" at 16' led to a new final-result rule) and personas mixing whole-match and recent figures. Stronger Foundry models should reduce both.
