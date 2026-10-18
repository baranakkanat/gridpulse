import csv, numpy as np
rows=[r for r in csv.DictReader(open("outputs/dual_study/evaluation_daily_outcomes.csv")) if r['network']=='1-LV-rural3--2-sw' and r['information']=='forecast' and r['truth']=='nominal']
rows.sort(key=lambda r:int(r['day']))
for r in rows:
    d=int(r['day'])
    if d<250 and (int(r['replay_aci__daylight_violation_steps'])>0 or d%7==0 or int(r['static_dev__daylight_violation_steps'])>0):
        print(r['date'], d, "tau %.3f" % float(r['replay_aci__tau']), "viol", r['replay_aci__daylight_violation_steps'], "curt %.3f static %.3f" % (float(r['replay_aci__curtailed_mwh']), float(r['static_dev__curtailed_mwh'])), "static viol", r['static_dev__daylight_violation_steps'], "replay_robust viol", r['replay_robust__daylight_violation_steps'])
